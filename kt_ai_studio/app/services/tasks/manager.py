import threading
import time
import traceback
import json
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db import models
# Import services lazily to avoid circular imports if any
from app.services.llm.openai_provider import generate_player_prompts, generate_scene_prompts
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
        else:
            raise ValueError(f"Unknown task type: {task.task_type}")

    def _handle_gen_prompt(self, db: Session, task: models.Task):
        player = task.player
        if not player:
            raise ValueError("Player not found")
        
        # Get Project Style
        style = player.project.style
        
        # Get Default LLM Profile
        llm_profile = db.query(models.LLMProfile).filter(models.LLMProfile.is_default == True).first()
        if not llm_profile:
             # Try to seed again? Or just fail?
             # If no profile, openai_provider will fallback to env if passed None, 
             # but we want to log the fallback in payload.
             # So let's handle fallback here or let provider handle it?
             # Provider handles it.
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
            "model": llm_profile.model if llm_profile else "env"
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
                # If data has 'value' and 'max', calculate percentage
                val = data.get('value', 0)
                max_val = data.get('max', 1)
                
                if max_val > 0:
                    progress = int((val / max_val) * 100)
                    progress = min(progress, 99)
                    task.progress = progress
                    db.commit()
        
        # Prepend Style Prompts
        # NOTE: Player prompts (generated by LLM) already should align with style, 
        # but as a safeguard, we prepend the mandatory style prompts from the preset.
        style = task.player.project.style
        if style:
            # We don't modify the player record, just the runtime injection?
            # Or we assume LLM did its job. 
            # Requirement 4: "所有给 Qwen / Wan2.2 的提示词，画风只能来自项目 preset"
            # Requirement 5: "解决因人物描述导致画风漂移的问题"
            
            # Implementation:
            # ComfyRunner uses player.prompt_pos. 
            # We should inject style prompts into the workflow runner or modify player prompts temporarily?
            # Better to inject in ComfyRunner or modify task payload?
            # Let's modify ComfyRunner to accept style prompts override/prepend.
            # But ComfyRunner reads from task.player.
            
            # STRATEGY: Update player.prompt_pos with Style Prefix just before running? 
            # No, that changes DB state permanently.
            # Let's update ComfyRunner to look at task.project.style
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
        except InterruptedError:
            print("Gen Base Interrupted")
            raise

    def _handle_gen_scene_prompt(self, db: Session, task: models.Task):
        scene = task.scene
        if not scene:
            raise ValueError("Scene not found")
        
        # Get Project Style (Dynamic fetch as per user request)
        # User instruction: "根据project_id查找到kt_ai_project的最新style_id,然后到kt_ai_style_preset里面去查找"
        # We ignore scene.style_id (snapshot) and use current project style.
        style = scene.project.style
        
        # Get Default LLM Profile
        llm_profile = db.query(models.LLMProfile).filter(models.LLMProfile.is_default == True).first()
        
        task.progress = 10
        db.commit()
            
        # Payload
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
            llm_profile=llm_profile
        )
        
        task.progress = 80
        db.commit()
        
        # Usage
        usage = prompts.pop("_usage", None)
        
        # Update Scene
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
        
        # Run Gen Base using ComfyRunner (Need to update ComfyRunner to handle Scene Task)
        # ComfyRunner.run_gen_base usually takes a task and expects task.player.
        # We need to adapt ComfyRunner or create run_gen_scene_base.
        # Let's create run_gen_scene_base in ComfyRunner to keep things clean.
        
        try:
            result = self.comfy_runner.run_gen_scene_base(
                task,
                callback=progress_callback,
                cancel_check_func=lambda: not self.running
            )
            
            # Update Scene
            scene = task.scene
            scene.base_image_path = result["base_image_path"]
            scene.status = "generated"
            
            task.result_json = json.dumps(result)
        except InterruptedError:
            print("Gen Scene Base Interrupted")
            raise

    def _handle_gen_8views(self, db: Session, task: models.Task):
        def progress_callback(event, data):
            # Check if task was cancelled
            try:
                db.refresh(task)
                if task.status == 'failed':
                    raise InterruptedError("Task cancelled by user")
            except Exception:
                raise InterruptedError("Task deleted")

            if event == 'progress':
                # Update progress and ETA
                progress = data.get('value', 0)
                eta = data.get('eta', 0)
                
                task.progress = int(progress)
                task.eta = int(eta)
                
                # Don't commit on every single step if it's too fast, but ComfyUI steps are slow enough.
                db.commit()
            
            elif event == 'view_generated':
                # data = {'view_name': ..., 'path': ..., 'views_json': ...}
                views_json = data['views_json']
                
                # Update Player incrementally
                player = task.player
                player.views_json = json.dumps(views_json)
                
                # Update Task incrementally
                task.result_json = json.dumps({"views_json": views_json})
                
                db.commit()
                print(f"Incremental update: {data['view_name']} ready.")

        try:
            result = self.comfy_runner.run_gen_8views(
                task, 
                callback=progress_callback,
                cancel_check_func=lambda: not self.running
            )
            
            # Update Player
            player = task.player
            # Merge views_json if exists? Or overwrite. User said "DB write back views_json".
            player.views_json = json.dumps(result["views_json"])
            player.status = "done"
            
            # Update Task
            task.result_json = json.dumps(result)
        except InterruptedError:
            print("Gen 8Views Interrupted")
            raise

# Global Instance
task_manager = TaskManager()
# task_manager.start() # Controlled by main.py startup event
