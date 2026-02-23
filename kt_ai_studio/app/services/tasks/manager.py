import threading
import time
import traceback
import json
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db import models
# Import services lazily to avoid circular imports if any
from app.services.llm.openai_provider import generate_player_prompts, generate_scene_prompts, generate_story_assets, generate_video_prompts
from app.services.comfyui.runner import ComfyRunner

class TaskManager:
    def __init__(self):
        self.running = False
        self.thread = None
        self.comfy_runner = ComfyRunner()
        
    @property
    def comfy_client(self):
        return self.comfy_runner.client

    def start(self):
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.thread.start()
            print("Task Manager started.")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
            print("Task Manager stopped.")
            
    def cancel_task(self, task_id):
        """Called by API to cancel a task"""
        # We don't have direct access to the worker loop's current task variable easily 
        # unless we store it.
        # But we can assume the ComfyClient.interrupt() has been called.
        # This function just helps clean up DB state if needed.
        pass

    def log_system(self, db: Session, module: str, progress: str, content: str):
        """Helper to write to SystemLog table"""
        try:
            log = models.SystemLog(
                module=module,
                progress_info=progress,
                content=content
            )
            db.add(log)
            db.commit()
        except Exception as e:
            print(f"Failed to write system log: {e}")

    def _worker_loop(self):
        while self.running:
            try:
                db = SessionLocal()
                # Check for queued tasks
                task = db.query(models.Task).filter(models.Task.status == "queued").order_by(models.Task.created_at.asc()).first()
                
                if task:
                    print(f"Processing task {task.id}: {task.task_type}")
                    task.status = "running"
                    task.started_at = models.datetime.utcnow()
                    task.progress = 0
                    db.commit()
                    
                    try:
                        self._process_task(db, task)
                        
                        # Re-fetch task to check if it was cancelled/interrupted externally
                        # If task was force deleted, refresh might fail or return None if using get?
                        # refresh() on a deleted object raises InvalidRequestError or ObjectDeletedError
                        try:
                            db.refresh(task)
                            if task.status != 'failed':
                                task.status = "done"
                                task.progress = 100
                        except Exception:
                             # Task likely deleted
                             print("Task object missing or deleted during processing.")
                             raise InterruptedError("Task force deleted")
                            
                    except Exception as e:
                        # Check if it was an interrupt (which might cause connection error or similar)
                        # or if task was marked failed by API
                        try:
                            db.refresh(task)
                            if task.status == 'failed':
                                 print(f"Task {task.id} was interrupted/failed externally.")
                            else:
                                print(f"Task {task.id} failed: {e}")
                                traceback.print_exc()
                                task.status = "failed"
                                task.error = str(e)
                        except Exception:
                            print(f"Task processing aborted (Task deleted): {e}")
                            # If task is deleted, we can't update it. Just continue.
                            continue
                    
                    # Final update if task still exists
                    try:
                        if not task.completed_at:
                            task.completed_at = models.datetime.utcnow()
                            
                        if task.started_at and task.completed_at:
                            delta = task.completed_at - task.started_at
                            task.duration = int(delta.total_seconds())
                        
                        task.updated_at = models.datetime.utcnow()
                        db.commit()
                    except Exception:
                        pass
                        
                else:
                    db.close()
                    time.sleep(2) # Sleep if no tasks
            except Exception as e:
                print(f"Worker loop error: {e}")
                time.sleep(5)
            finally:
                if 'db' in locals():
                    db.close()

    def _find_list_in_json(self, data: dict, target_keys: list) -> list:
        """
        鲁棒地从 JSON 字典中查找列表，处理大小写和嵌套情况。
        """
        if not isinstance(data, dict):
            return []
            
        target_keys_lower = [k.lower() for k in target_keys]
        
        # 1. 当前层级搜索 (忽略大小写)
        for k, v in data.items():
            if k.lower() in target_keys_lower and isinstance(v, list):
                return v
                
        # 2. 嵌套层级搜索 (支持一层嵌套，如 data/result/content)
        for k, v in data.items():
            if isinstance(v, dict):
                # 递归查找 (仅限一层，防止过深)
                for nested_k, nested_v in v.items():
                    if nested_k.lower() in target_keys_lower and isinstance(nested_v, list):
                        return nested_v
                        
        return []

    def _process_task(self, db: Session, task: models.Task):
        if task.task_type == "GEN_PROMPT":
            self._handle_gen_prompt(db, task)
        elif task.task_type == "GEN_BASE":
            self._handle_gen_base(db, task)
        elif task.task_type == "GEN_8VIEWS":
            self._handle_gen_8views(db, task)
        elif task.task_type == "GEN_SCENE_PROMPT":
            self._handle_gen_scene_prompt(db, task)
        elif task.task_type == "GEN_SCENE_BASE":
            self._handle_gen_scene_base(db, task)
        elif task.task_type == "AUTO_GENERATE_STORY":
            self._handle_auto_generate_story(db, task)
        elif task.task_type == "SCENE_MERGE":
            self._handle_scene_merge(db, task)
        elif task.task_type == "GEN_VIDEO_PROMPT":
            self._handle_gen_video_prompt(db, task)
        elif task.task_type == "GEN_VIDEO":
            self._handle_gen_video(db, task)
        else:
            raise ValueError(f"Unknown task type: {task.task_type}")

    def _get_batch_info(self, task):
        try:
            if task.payload_json:
                payload = json.loads(task.payload_json)
                if payload.get("is_batch"):
                    return payload
        except:
            pass
        return None

    def _handle_gen_prompt(self, db: Session, task: models.Task):
        player = task.player
        if not player:
            raise ValueError("Player not found")
        
        batch_info = self._get_batch_info(task)
        if batch_info:
            module = batch_info.get("batch_module", "批量生成")
            count_str = f"[{batch_info.get('batch_index')}/{batch_info.get('batch_total')}个]"
            self.log_system(db, module, count_str, f"生成 {player.player_name} 的数据，目前正在请求LLM。")

        # Get Project Style
        style = player.project.style
        
        # Get Default LLM Profile
        llm_profile = db.query(models.LLMProfile).filter(models.LLMProfile.is_default == True).first()
        if not llm_profile:
             pass
        
        # Fake progress for UX
        task.progress = 10
        db.commit()
            
        # 记录 Payload
        task.payload_json = json.dumps({
            "player_id": player.id,
            "player_name": player.player_name,
            "player_sex": player.player_sex,
            "player_mark": player.player_mark,
            "style_preset": style.name if style else "None",
            "provider": llm_profile.provider if llm_profile else "env-fallback",
            "base_url": llm_profile.base_url if llm_profile else "env",
            "model": llm_profile.model if llm_profile else "env",
            # Preserve batch info
            "is_batch": batch_info.get("is_batch") if batch_info else False,
            "batch_module": batch_info.get("batch_module") if batch_info else None,
            "batch_index": batch_info.get("batch_index") if batch_info else None,
            "batch_total": batch_info.get("batch_total") if batch_info else None
        })
        
        task.progress = 30
        db.commit()
            
        prompts = generate_player_prompts(
            player.player_name, 
            player.player_sex, 
            player.player_mark,
            style_preset=style,
            llm_profile=llm_profile
        )
        
        if batch_info:
            module = batch_info.get("batch_module", "批量生成")
            count_str = f"[{batch_info.get('batch_index')}/{batch_info.get('batch_total')}个]"
            self.log_system(db, module, count_str, f"生成 {player.player_name} 的数据，LLM数据返回，正在生成数据。")

        task.progress = 80
        db.commit()
        
        # Extract usage if present and clean prompts for DB
        usage = prompts.pop("_usage", None)
        
        # Update Player
        player.prompt_pos = prompts.get("prompt_pos")
        player.prompt_neg = prompts.get("prompt_neg")
        player.player_desc = prompts.get("player_desc") # New field
        
        # Update Task result (include usage)
        if usage:
            prompts["usage"] = usage
            
        task.result_json = json.dumps(prompts)
        task.progress = 100

    def _handle_gen_base(self, db: Session, task: models.Task):
        def progress_callback(event, data):
            # Check if task was cancelled
            try:
                db.refresh(task)
                if task.status == 'failed':
                    raise InterruptedError("Task cancelled by user")
            except Exception:
                raise InterruptedError("Task deleted")
                
            if event == 'progress':
                # Pass through progress from ComfyUI
                val = data.get('value', 0)
                max_val = data.get('max', 1)
                
                if max_val > 0:
                    progress = int((val / max_val) * 100)
                    progress = min(progress, 99)
                    task.progress = progress
                    db.commit()
        
        batch_info = self._get_batch_info(task)
        if batch_info:
            module = batch_info.get("batch_module", "批量生成")
            count_str = f"[{batch_info.get('batch_index')}/{batch_info.get('batch_total')}个]"
            self.log_system(db, module, count_str, f"生成 {task.player.player_name} 的基础图，正在生成数据。")

        # Prepend Style Prompts
        style = task.player.project.style
        if style:
            pass

        try:
            result = self.comfy_runner.run_gen_base(
                task, 
                callback=progress_callback,
                cancel_check_func=lambda: not self.running
            )
            
            # Update Player
            player = task.player
            player.base_image_path = result["base_image_path"]
            player.status = "ready" # or "base_generated"
            
            # Update Task
            task.result_json = json.dumps(result)
            
            if batch_info:
                module = batch_info.get("batch_module", "批量生成")
                count_str = f"[{batch_info.get('batch_index')}/{batch_info.get('batch_total')}个]"
                self.log_system(db, module, count_str, f"生成 {player.player_name} 的数据，数据生成成功。")

        except InterruptedError:
            print("Gen Base Interrupted")
            raise

    def _handle_gen_scene_prompt(self, db: Session, task: models.Task):
        scene = task.scene
        if not scene:
            raise ValueError("Scene not found")
        
        style = scene.project.style
        llm_profile = db.query(models.LLMProfile).filter(models.LLMProfile.is_default == True).first()
        
        task.progress = 10
        db.commit()
            
        task.payload_json = json.dumps({
            "scene_id": scene.id,
            "scene_name": scene.name,
            "base_desc": scene.base_desc,
            "style_preset": style.name if style else "None",
            "provider": llm_profile.provider if llm_profile else "env",
            "model": llm_profile.model if llm_profile else "env"
        })
        
        task.progress = 30
        db.commit()
            
        prompts = generate_scene_prompts(
            scene.base_desc,
            style_preset=style,
            llm_profile=llm_profile,
            scene_type=scene.scene_type or "Indoor"
        )
        
        task.progress = 80
        db.commit()
        
        usage = prompts.pop("_usage", None)
        
        scene.prompt_pos = prompts.get("prompt_pos")
        scene.prompt_neg = prompts.get("prompt_neg")
        scene.scene_desc = prompts.get("scene_desc", "")
        scene.status = "generated_prompt"
        
        if usage:
            prompts["usage"] = usage
            
        task.result_json = json.dumps(prompts)
        task.progress = 100

    def _handle_gen_scene_base(self, db: Session, task: models.Task):
        def progress_callback(event, data):
            try:
                db.refresh(task)
                if task.status == 'failed':
                    raise InterruptedError("Task cancelled by user")
            except Exception:
                raise InterruptedError("Task deleted")
                
            if event == 'progress':
                val = data.get('value', 0)
                max_val = data.get('max', 1)
                if max_val > 0:
                    progress = int((val / max_val) * 100)
                    progress = min(progress, 99)
                    task.progress = progress
                    db.commit()
        
        try:
            result = self.comfy_runner.run_gen_scene_base(
                task,
                callback=progress_callback,
                cancel_check_func=lambda: not self.running
            )
            
            # Update Scene
            scene = task.scene
            scene.base_image_path = result["base_image_path"]
            scene.status = "generated" # Keep as 'generated' (Base done)
            
            task.result_json = json.dumps(result)
        except InterruptedError:
            print("Gen Scene Base Interrupted")
            raise

    def _handle_gen_8views(self, db: Session, task: models.Task):
        def progress_callback(event, data):
            try:
                db.refresh(task)
                if task.status == 'failed':
                    raise InterruptedError("Task cancelled by user")
            except Exception:
                raise InterruptedError("Task deleted")

            if event == 'progress':
                progress = data.get('value', 0)
                eta = data.get('eta', 0)
                
                task.progress = int(progress)
                task.eta = int(eta)
                
                db.commit()
            
            elif event == 'view_generated':
                views_json = data['views_json']
                
                player = task.player
                player.views_json = json.dumps(views_json)
                
                task.result_json = json.dumps({"views_json": views_json})
                
                db.commit()
                print(f"Incremental update: {data['view_name']} ready.")

        batch_info = self._get_batch_info(task)
        if batch_info:
            module = batch_info.get("batch_module", "批量生成")
            count_str = f"[{batch_info.get('batch_index')}/{batch_info.get('batch_total')}个]"
            self.log_system(db, module, count_str, f"生成 {task.player.player_name} 的8镜图，正在生成数据。")

        try:
            result = self.comfy_runner.run_gen_8views(
                task, 
                callback=progress_callback,
                cancel_check_func=lambda: not self.running
            )
            
            player = task.player
            player.views_json = json.dumps(result["views_json"])
            player.status = "done" # Completed
            
            task.result_json = json.dumps(result)
            
            if batch_info:
                module = batch_info.get("batch_module", "批量生成")
                count_str = f"[{batch_info.get('batch_index')}/{batch_info.get('batch_total')}个]"
                self.log_system(db, module, count_str, f"生成 {player.player_name} 的8镜图，数据生成成功。")

        except InterruptedError:
            print("Gen 8Views Interrupted")
            raise

    def _handle_auto_generate_story(self, db: Session, task: models.Task):
        project = task.project
        if not project:
            raise ValueError("Project not found")
        
        try:
            payload = json.loads(task.payload_json)
        except:
            payload = {}
            
        content = payload.get("content", "")
        mode = payload.get("mode", "append")
        episode_start = int(payload.get("episode_start", 1))
        max_characters = int(payload.get("max_characters", 5))
        max_scenes = int(payload.get("max_scenes", 10))
        
        style = project.style
        llm_profile = db.query(models.LLMProfile).filter(models.LLMProfile.is_default == True).first()
        
        task.progress = 10
        db.commit()
        
        assets = generate_story_assets(
            content, 
            style_preset=style, 
            llm_profile=llm_profile,
            episode_start=episode_start,
            max_characters=max_characters,
            max_scenes=max_scenes
        )
        
        task.progress = 50
        db.commit()
        
        usage = assets.pop("_usage", None)
        
        if mode == "overwrite":
            db.query(models.ScenePlayerLink).filter(
                models.ScenePlayerLink.scene_id.in_(
                    db.query(models.Scene.id).filter(models.Scene.project_id == project.id)
                )
            ).delete(synchronize_session=False)
            db.query(models.Scene).filter(models.Scene.project_id == project.id).delete(synchronize_session=False)
            db.query(models.Player).filter(models.Player.project_id == project.id).delete(synchronize_session=False)
            db.query(models.Task).filter(
                models.Task.project_id == project.id,
                models.Task.id != task.id
            ).delete(synchronize_session=False)
            db.flush()

        existing_players = {} 
        def normalize_name(name):
            return name.strip().replace(" ", "")
            
        p_rows = db.query(models.Player).filter(models.Player.project_id == project.id).all()
        for p in p_rows:
            existing_players[normalize_name(p.player_name)] = p.id
                
        created_players = 0
        reused_players = 0
        name_to_id_map = {} 
        
        char_list = self._find_list_in_json(assets, ["characters", "character_list", "chars", "players"])
        
        for char in char_list:
            raw_name = char.get("player_name", "Unknown").strip()
            if not raw_name:
                continue
            
            norm_name = normalize_name(raw_name)
            
            if norm_name in existing_players:
                pid = existing_players[norm_name]
                player = db.query(models.Player).filter(models.Player.id == pid).first()
                if player:
                    new_mark = char.get("player_mark", "")
                    if new_mark and len(new_mark) > len(player.player_mark or ""):
                         player.player_mark = new_mark
                    
                    name_to_id_map[norm_name] = pid
                    reused_players += 1
            else:
                player = models.Player(
                    project_id=project.id,
                    player_name=raw_name,
                    player_sex=char.get("player_sex", "other"),
                    player_mark=char.get("player_mark", ""),
                    status="draft",
                    player_desc=None,
                    prompt_pos=None,
                    prompt_neg=None,
                    base_image_path=None,
                    views_json=None
                )
                db.add(player)
                db.flush() 
                name_to_id_map[norm_name] = player.id
                existing_players[norm_name] = player.id 
                created_players += 1
            
        created_scenes = 0
        linked_associations = 0
        scene_warnings = []
        scene_type_counts = {"Indoor": 0, "Outdoor": 0, "Special": 0}
        
        from sqlalchemy import func
        max_shot_res = db.query(func.max(models.Scene.shot)).filter(
            models.Scene.project_id == project.id,
            models.Scene.episode == episode_start
        ).scalar()
        
        current_max_shot = max_shot_res if max_shot_res is not None else 0
        
        scene_list = self._find_list_in_json(assets, ["scenes", "scene_list", "shots"])
            
        for idx, sc in enumerate(scene_list):
            target_ep = episode_start
            target_shot = current_max_shot + idx + 1
            
            raw_type = sc.get("scene_type", "")
            valid_types = ["Indoor", "Outdoor", "Special"]
            
            normalized_type = None
            for vt in valid_types:
                if raw_type == vt:
                    normalized_type = vt
                    break
            
            if not normalized_type:
                for vt in valid_types:
                    if raw_type.lower() == vt.lower():
                        normalized_type = vt
                        break
            
            if not normalized_type:
                normalized_type = "Special"
                if raw_type:
                    scene_warnings.append(f"Scene '{sc.get('name')}' has invalid type '{raw_type}', fallback to Special.")
            
            scene_type_counts[normalized_type] += 1

            scene = models.Scene(
                project_id=project.id,
                name=sc.get("name", "Unknown Scene"),
                episode=target_ep,
                shot=target_shot,
                base_desc=sc.get("base_desc", ""),
                scene_type=normalized_type,
                status="draft",
                scene_desc=None,
                prompt_pos=None,
                prompt_neg=None,
                base_image_path=None
            )
            db.add(scene)
            db.flush() 
            created_scenes += 1
            
            sc_chars = sc.get("characters", [])
            if not isinstance(sc_chars, list):
                sc_chars = []
                
            linked_count = 0
            for char_name in sc_chars:
                norm_char_name = normalize_name(char_name)
                if norm_char_name in name_to_id_map:
                    pid = name_to_id_map[norm_char_name]
                    
                    exists_link = db.query(models.ScenePlayerLink).filter(
                        models.ScenePlayerLink.scene_id == scene.id,
                        models.ScenePlayerLink.player_id == pid
                    ).count() > 0
                    
                    if not exists_link:
                        link = models.ScenePlayerLink(
                            scene_id=scene.id,
                            player_id=pid
                        )
                        db.add(link)
                        linked_count += 1
                        linked_associations += 1
                else:
                    pass
            
            if len(sc_chars) > 0 and linked_count == 0:
                scene_warnings.append(f"Scene {scene.id} ({scene.name}): Characters {sc_chars} not found in player list.")

        db.commit()
        
        result = {
            "status": "success",
            "players_created": created_players,
            "players_reused": reused_players,
            "scenes_created": created_scenes,
            "associations_created": linked_associations,
            "scene_type_counts": scene_type_counts,
            "warnings": scene_warnings
        }
        if usage:
            result["usage"] = usage
            
        task.result_json = json.dumps(result)
        task.progress = 100

    def _handle_gen_video_prompt(self, db: Session, task: models.Task):
        """
        Generates prompts for video generation using LLM.
        """
        video = task.video
        if not video:
            raise ValueError("Task has no associated video")
            
        scene = video.scene
        if not scene.video_llm_context:
            raise ValueError("Scene context missing")
            
        # Get LLM Profile
        project = task.project
        # Should we allow user to select profile per task? 
        # For now use default or first available.
        # But wait, LLM profiles are global.
        # Let's pick default profile.
        llm_profile = db.query(models.LLMProfile).filter(models.LLMProfile.is_default == True).first()
        if not llm_profile:
            llm_profile = db.query(models.LLMProfile).first()
            
        if not llm_profile:
            raise ValueError("No LLM Profile configured")
            
        from app.services.llm.openai_provider import generate_video_prompts
        
        prompts = generate_video_prompts(
            video_context=scene.video_llm_context,
            style_preset=project.style,
            llm_profile=llm_profile
        )
        
        # Save Result
        task.result_json = json.dumps(prompts)
        
        # Update Video Fields
        video.prompt_pos = prompts.get("prompt_pos")
        video.prompt_neg = prompts.get("prompt_neg")
        
        # Update FPS/Length if provided by LLM
        if "fps" in prompts and prompts["fps"]:
            try:
                video.fps = int(prompts["fps"])
            except:
                pass
                
        if "length" in prompts and prompts["length"]:
            try:
                video.length = int(prompts["length"])
            except:
                pass

        # video.status = "prompt_generated" 
        
        db.commit()

    def _handle_gen_video(self, db: Session, task: models.Task):
        def progress_callback(event, data):
            try:
                db.refresh(task)
                if task.status == 'failed':
                    raise InterruptedError("Task cancelled by user")
            except Exception:
                raise InterruptedError("Task deleted")
                
            if event == 'progress':
                val = data.get('value', 0)
                max_val = data.get('max', 1)
                if max_val > 0:
                    progress = int((val / max_val) * 100)
                    progress = min(progress, 99)
                    task.progress = progress
                    db.commit()
        
        try:
            result = self.comfy_runner.run_gen_video(
                task,
                callback=progress_callback,
                cancel_check_func=lambda: not self.running
            )
            
            # Update Video
            video = task.video
            video.video_path = result["video_path"]
            video.status = "completed"
            
            task.result_json = json.dumps(result)
            task.progress = 100
            db.commit()
            
        except InterruptedError:
            print("Gen Video Interrupted")
            raise

    def _handle_scene_merge(self, db: Session, task: models.Task):
        import os
        import random
        from app.config import config
        from app.services.llm.openai_provider import generate_merge_prompts

        project = task.project
        scene = task.scene
        if not scene:
            raise ValueError("Scene not found")
            
        if not scene.base_image_path:
            raise ValueError("Scene base image not generated yet.")
            
        links = db.query(models.ScenePlayerLink).filter(models.ScenePlayerLink.scene_id == scene.id).all()
        players = []
        for link in links:
            p = db.query(models.Player).filter(models.Player.id == link.player_id).first()
            if p:
                players.append(p)
                
        if not players:
            task.progress = 100
            task.result_json = json.dumps({"status": "no_players", "merged_image_path": scene.base_image_path})
            scene.merged_image_path = scene.base_image_path
            scene.status = "completed" # Completed even if no players
            db.commit()
            return

        base_dir = os.path.dirname(config.OUTPUT_DIR)
        current_img_path = os.path.join(base_dir, scene.base_image_path.lstrip("/\\")) 
        
        if not os.path.exists(current_img_path):
             if os.path.exists(scene.base_image_path):
                 current_img_path = scene.base_image_path
             else:
                 if "output" not in scene.base_image_path:
                     current_img_path = os.path.join(config.OUTPUT_DIR, scene.base_image_path.lstrip("/\\"))
        
        players_data = []
        player_map = {} 
        for p in players:
            views_keys = []
            if p.views_json:
                try:
                    v = json.loads(p.views_json)
                    views_keys = list(v.keys())
                except:
                    pass
            
            players_data.append({
                "player_id": p.id,
                "player_name": p.player_name,
                "sex": p.player_sex, 
                "appearance": p.player_mark or p.player_desc or "",
                "views_keys": views_keys
            })
            player_map[p.player_name] = p
            
        payload = {}
        if task.payload_json:
            try:
                payload = json.loads(task.payload_json)
            except:
                pass
        
        seed_from_payload = payload.get("seed", 0)
            
        llm_profile = db.query(models.LLMProfile).filter(models.LLMProfile.is_default == True).first()
        style = project.style
        
        task.result_json = json.dumps({"status_message": "正在请求 LLM 生成合成方案..."})
        task.progress = 5
        db.commit()
        
        try:
            merge_plan = generate_merge_prompts(
                scene_base_desc=scene.base_desc,
                players=players_data,
                style_preset=style,
                llm_profile=llm_profile,
                scene_desc=scene.scene_desc or "",
                scene_type=scene.scene_type or "Indoor"
            )
            
            if "layout_reasoning" in merge_plan:
                print(f"[LLM Layout Reasoning] {merge_plan['layout_reasoning']}")
                
            steps = merge_plan.get("steps", [])
        except Exception as e:
            print(f"LLM Merge Planning Failed: {e}")
            steps = []
            for p in players:
                steps.append({
                    "player_id": p.id,
                    "player_name": p.player_name,
                    "view_key": "right45",
                    "merge_pos": f"{p.player_name} standing in scene, natural lighting",
                    "merge_neg": "floating, bad shadow"
                })

        total_steps = len(steps)
        if total_steps == 0:
             task.progress = 100
             db.commit()
             return

        task.result_json = json.dumps({"status_message": f"LLM 规划完成，准备合成 {total_steps} 个角色..."})
        task.progress = 10
        db.commit()
        
        merge_records = [] 
        
        for idx, step in enumerate(steps):
            if not self.running:
                raise InterruptedError("Task cancelled")
            
            step_pid = step.get("player_id")
            step_pname = step.get("player_name")
            
            player = None
            if step_pid:
                for p in players:
                    if p.id == step_pid:
                        player = p
                        break
            
            if not player and step_pname:
                player = player_map.get(step_pname)
            
            if not player:
                print(f"Skipping unknown player in step: {step_pname} (ID: {step_pid})")
                continue

            p_name = player.player_name
            p_id = player.id

            progress = int((idx / total_steps) * 100)
            task.progress = progress
            
            status_msg = f"正在合成角色: {p_name} ({idx+1}/{total_steps})"
            
            try:
                if task.result_json:
                    current_result = json.loads(task.result_json)
                else:
                    current_result = {}
            except:
                current_result = {}
                
            current_result["status_message"] = status_msg
            task.result_json = json.dumps(current_result)
            
            db.commit()
            print(f"[Merge Progress] {status_msg}")
            
            view_key = step.get("view_key", "right45")
            player_img_path = None
            
            if player.views_json:
                try:
                    views = json.loads(player.views_json)
                    if view_key in views:
                        player_img_path = views[view_key]
                    elif "right45" in views:
                        player_img_path = views["right45"]
                    elif "front" in views:
                        player_img_path = views["front"]
                    elif views:
                        player_img_path = list(views.values())[0]
                except:
                    pass
            
            if not player_img_path and player.base_image_path:
                player_img_path = player.base_image_path
                
            if not player_img_path:
                print(f"Skipping player {p_name}: No image found.")
                continue
                
            base_dir = os.path.dirname(config.OUTPUT_DIR) 
            
            if os.path.isabs(player_img_path):
                abs_player_path = player_img_path
            else:
                clean_path = player_img_path.lstrip("/\\")
                abs_player_path = os.path.join(base_dir, clean_path)
            
            if not os.path.exists(abs_player_path):
                 print(f"  !! Image file missing at {abs_player_path}")
                 fallback_path = os.path.join(config.OUTPUT_DIR, clean_path)
                 if os.path.exists(fallback_path):
                     abs_player_path = fallback_path
                     print(f"  -> Found at fallback: {abs_player_path}")
                 else:
                     print(f"Skipping player {p_name}: Image file missing.")
                     continue

            context_prompt = ""
            if idx > 0:
                context_prompt = " (Keep existing characters unchanged, only add new character)"
            
            final_pos = f"{step.get('merge_pos', '')}{context_prompt}"
            final_neg = f"{step.get('merge_neg', '')}"
            
            merge_records.append({
                "step_index": idx,
                "player_name": p_name,
                "view_key": view_key,
                "prompt_pos": final_pos,
                "prompt_neg": final_neg,
                "player_img_path": player_img_path
            })
            
            if seed_from_payload and int(seed_from_payload) > 0:
                seed = int(seed_from_payload)
                pass 
            else:
                seed = random.randint(1, 1000000000000)
            
            try:
                if not os.path.exists(current_img_path):
                    raise FileNotFoundError(f"Previous merge result not found at: {current_img_path}")
                
                result = self.comfy_runner.run_scene_merge(
                    task,
                    current_img_path=current_img_path, 
                    player_img_path=abs_player_path,   
                    prompt_pos=final_pos,
                    prompt_neg=final_neg,
                    seed=seed,
                    cancel_check_func=lambda: not self.running
                )
                
                new_img_rel = result["merge_image_path"]
                
                if os.path.isabs(new_img_rel):
                    current_img_path = new_img_rel
                else:
                    current_img_path = os.path.join(base_dir, new_img_rel.lstrip("/\\"))
                
                print(f"[Merge Step {idx+1}] Result saved to: {current_img_path}")
                
                try:
                    abs_output = os.path.abspath(config.OUTPUT_DIR)
                    abs_current = os.path.abspath(current_img_path)
                    
                    if abs_current.startswith(abs_output):
                         rel_from_output = os.path.relpath(abs_current, abs_output)
                         intermediate_rel_path = os.path.join("output", rel_from_output).replace("\\", "/")
                    else:
                         base_dir_check = os.path.dirname(config.OUTPUT_DIR)
                         intermediate_rel_path = os.path.relpath(abs_current, base_dir_check).replace("\\", "/")
                except:
                    intermediate_rel_path = ""

                scene.merged_image_path = intermediate_rel_path
                
                try:
                    if task.result_json:
                        current_result = json.loads(task.result_json)
                    else:
                        current_result = {}
                except:
                    current_result = {}
                
                current_result["merged_image_path"] = intermediate_rel_path
                task.result_json = json.dumps(current_result)
                
                db.add(task)
                db.add(scene) 
                db.commit()
                db.refresh(task) 
                db.refresh(scene) 
                
            except Exception as e:
                print(f"Merge failed for step {idx} ({p_name}): {e}")
                raise e

        scene.merged_image_path = current_img_path 
        scene.merged_prompts_json = json.dumps(merge_records, ensure_ascii=False)
        
        try:
            import re
            
            shot_type = "Unknown"
            if scene.prompt_pos:
                match = re.search(r"【镜头景别】\s*(.*?)\s*(?=【|$)", scene.prompt_pos, re.DOTALL)
                if match:
                    shot_type = match.group(1).strip()
            
            video_context = {
                "scene": {
                    "name": scene.name,
                    "type": scene.scene_type,
                    "base_desc": scene.base_desc,
                    "visual_desc": scene.scene_desc, 
                    "shot_type": shot_type
                },
                "characters": []
            }
            
            for p in players:
                record = next((r for r in merge_records if r["player_name"] == p.player_name), None)
                
                char_data = {
                    "name": p.player_name,
                    "visual_desc": p.player_mark, 
                    "action_desc": record["prompt_pos"] if record else "", 
                    "view": record["view_key"] if record else ""
                }
                video_context["characters"].append(char_data)
                
            scene.video_llm_context = json.dumps(video_context, ensure_ascii=False, indent=2)
            print(f"[Video Context] Generated for Scene {scene.id}")
            
        except Exception as e:
            print(f"Failed to generate video context: {e}")
            traceback.print_exc()

        rel_path = ""
        try:
            abs_output = os.path.abspath(config.OUTPUT_DIR)
            abs_current = os.path.abspath(current_img_path)
            
            if abs_current.startswith(abs_output):
                 rel_from_output = os.path.relpath(abs_current, abs_output)
                 rel_path = os.path.join("output", rel_from_output).replace("\\", "/")
            else:
                 parts = abs_current.replace("\\", "/").split("/")
                 if "output" in parts:
                     idx = parts.index("output")
                     rel_path = "/".join(parts[idx:])
                 else:
                     rel_path = current_img_path
            
        except ValueError:
            print(f"Warning: Could not calculate relative path for {current_img_path}")
            rel_path = current_img_path 
        
        print(f"Final Merged Image Path: {rel_path}")
             
        scene.merged_image_path = rel_path
        
        # Update Status to Completed
        scene.status = "completed"
        
        final_data = {}
        if task.result_json:
             final_data = json.loads(task.result_json)
        final_data["merged_image_path"] = rel_path
        final_data["status_message"] = "合成完成"
        
        task.result_json = json.dumps(final_data)
        task.progress = 100
        db.commit()

task_manager = TaskManager()
