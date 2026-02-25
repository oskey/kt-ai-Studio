import time
import asyncio
from sqlalchemy.orm import Session
from app.db import models, crud
from app.db.session import SessionLocal
from app.services.tasks.manager import task_manager
import json

def log_system(db: Session, module: str, progress: str, content: str, level: str = "INFO"):
    log = models.SystemLog(
        module=module,
        progress_info=progress,
        content=content,
        level=level
    )
    db.add(log)
    db.commit()

async def wait_for_task(db: Session, task_id: int, timeout: int = 300) -> bool:
    """
    Polls task status until done or failed.
    Returns True if done, False if failed or timeout.
    Non-blocking version: yields control to event loop.
    """
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        # Yield control to allow other async tasks (like WebUI requests) to run
        await asyncio.sleep(2) 
        
        try:
            # OPTIMIZATION:
            # We must expire the session objects to ensure we fetch fresh data from DB,
            # otherwise SQLAlchemy might return cached 'queued' status forever in this transaction.
            db.expire_all()
            
            task = db.query(models.Task).filter(models.Task.id == task_id).first()
            
            if not task:
                return False
                
            if task.status == 'done':
                return True
            if task.status == 'failed':
                return False
                
            # Optional: commit to keep transaction short? 
            # No, we are in a loop. db.expire_all() is enough to refresh.
            
        except Exception as e:
            print(f"Error checking task status: {e}")
            return False
        
    return False

async def process_batch_gen_base(project_id: int):
    db = SessionLocal()
    try:
        project = crud.get_project(db, project_id)
        if not project:
            return
            
        players = crud.get_players_by_project(db, project_id)
        total = len(players)
        
        log_system(db, "[一键生成所有基图]", f"[0/{total}]", f"开始处理项目 {project.name} 的批量基图生成任务")
        
        count = 0
        for i, player in enumerate(players):
            current_progress = f"[{i+1}/{total}]"
            
            # Skip if already done or ready
            # User said: "Complete -> Skip; Ready -> Skip; Only Draft -> Execute"
            if player.status in ['done', 'ready']:
                log_system(db, "[一键生成所有基图]", current_progress, f"角色 {player.player_name} 状态为 {player.status}，跳过")
                count += 1
                continue
                
            if player.status == 'draft':
                # Step 1: Generate Prompt (Check if exists first? Or regenerate?)
                # User logic: "Normally used to ... regenerate all ... LLM will overwrite".
                # So we just run GEN_PROMPT.
                
                log_system(db, "[一键生成所有基图]", current_progress, f"正在为 {player.player_name} 请求 LLM 生成提示词...")
                
                # Create Task
                task = models.Task(
                    project_id=project_id,
                    player_id=player.id,
                    task_type="GEN_PROMPT",
                    status="queued",
                    payload_json="{}"
                )
                db.add(task)
                db.commit()
                
                # Wait for Prompt
                # Use a shorter sleep interval for responsive checking
                success = await wait_for_task(db, task.id)
                db.refresh(task)
                
                # Small yield to let other tasks/web requests breathe
                await asyncio.sleep(0.1)
                
                if not success:
                    # Check for Global Stop
                    if task.result_json and "Global Stop" in task.result_json:
                        log_system(db, "[一键生成所有基图]", current_progress, "用户终止任务，批量处理停止。", "WARNING")
                        return

                    log_system(db, "[一键生成所有基图]", current_progress, f"角色 {player.player_name} 提示词生成失败", "ERROR")
                    continue
                    
                log_system(db, "[一键生成所有基图]", current_progress, f"角色 {player.player_name} 提示词生成成功，开始生成基图...")
                
                # Step 2: Generate Base
                # Need payload with defaults from System Config
                sys_configs = db.query(models.SystemConfig).all()
                sys_conf = {c.key: c.value for c in sys_configs}
                
                # Fetch settings or defaults
                default_seed = int(sys_conf.get('player_gen_seed', 264590))
                default_width = int(sys_conf.get('player_gen_width', 1024))
                default_height = int(sys_conf.get('player_gen_height', 768))
                
                payload = {
                    "seed": default_seed,
                    "width": default_width,
                    "height": default_height
                }
                
                # Log payload for debugging
                log_system(db, "[一键生成所有基图]", current_progress, f"Payload: {json.dumps(payload)}")
                
                task_base = models.Task(
                    project_id=project_id,
                    player_id=player.id,
                    task_type="GEN_BASE",
                    status="queued",
                    payload_json=json.dumps(payload)
                )
                db.add(task_base)
                db.commit()
                
                success_base = await wait_for_task(db, task_base.id, timeout=600) # Longer timeout for image gen
                db.refresh(task_base)
                
                await asyncio.sleep(0.1) # Yield control
                
                if success_base:
                    log_system(db, "[一键生成所有基图]", current_progress, f"角色 {player.player_name} 基图生成成功")
                    # Update status is handled by task manager, but we can double check?
                    # Task manager sets player status to 'ready' on GEN_BASE success.
                else:
                    # Check for Global Stop
                    if task_base.result_json and "Global Stop" in task_base.result_json:
                        log_system(db, "[一键生成所有基图]", current_progress, "用户终止任务，批量处理停止。", "WARNING")
                        return
                    log_system(db, "[一键生成所有基图]", current_progress, f"角色 {player.player_name} 基图生成失败", "ERROR")
                    
            count += 1
            
        log_system(db, "[一键生成所有基图]", f"[{total}/{total}]", "批量任务执行完毕")
        
    except Exception as e:
        log_system(db, "[一键生成所有基图]", "ERROR", f"批量任务异常中断: {str(e)}", "ERROR")
    finally:
        db.close()

async def process_batch_gen_complete(project_id: int):
    db = SessionLocal()
    try:
        project = crud.get_project(db, project_id)
        if not project:
            return
            
        players = crud.get_players_by_project(db, project_id)
        total = len(players)
        
        log_system(db, "[一键生成角色完整图]", f"[0/{total}]", f"开始处理项目 {project.name} 的批量完整图生成任务")
        
        for i, player in enumerate(players):
            current_progress = f"[{i+1}/{total}]"
            
            if player.status == 'done':
                log_system(db, "[一键生成角色完整图]", current_progress, f"角色 {player.player_name} 已完成，跳过")
                continue
                
            # If Draft, do full flow (Prompt -> Base -> 8View)
            # If Ready, do 8View only
            
            if player.status == 'draft':
                # --- Prompt ---
                log_system(db, "[一键生成角色完整图]", current_progress, f"正在为 {player.player_name} 生成提示词...")
                task_p = models.Task(project_id=project_id, player_id=player.id, task_type="GEN_PROMPT", status="queued", payload_json="{}")
                db.add(task_p)
                db.commit()
                
                success_p = await wait_for_task(db, task_p.id)
                db.refresh(task_p)
                if not success_p:
                    if task_p.result_json and "Global Stop" in task_p.result_json:
                        log_system(db, "[一键生成角色完整图]", current_progress, "用户终止任务，批量处理停止。", "WARNING")
                        return
                    log_system(db, "[一键生成角色完整图]", current_progress, f"角色 {player.player_name} 提示词失败", "ERROR")
                    continue
                
                # --- Base ---
                log_system(db, "[一键生成角色完整图]", current_progress, f"提示词成功，正在生成基图...")
                sys_configs = db.query(models.SystemConfig).all()
                sys_conf = {c.key: c.value for c in sys_configs}
                
                # Fetch settings or defaults
                default_seed = int(sys_conf.get('player_gen_seed', 264590))
                default_width = int(sys_conf.get('player_gen_width', 1024))
                default_height = int(sys_conf.get('player_gen_height', 768))

                payload = {
                    "seed": default_seed,
                    "width": default_width,
                    "height": default_height
                }
                
                log_system(db, "[一键生成角色完整图]", current_progress, f"Payload: {json.dumps(payload)}")

                task_b = models.Task(project_id=project_id, player_id=player.id, task_type="GEN_BASE", status="queued", payload_json=json.dumps(payload))
                db.add(task_b)
                db.commit()
                
                success_b = await wait_for_task(db, task_b.id, timeout=600)
                db.refresh(task_b)
                if not success_b:
                    if task_b.result_json and "Global Stop" in task_b.result_json:
                        log_system(db, "[一键生成角色完整图]", current_progress, "用户终止任务，批量处理停止。", "WARNING")
                        return
                    log_system(db, "[一键生成角色完整图]", current_progress, f"角色 {player.player_name} 基图失败", "ERROR")
                    continue
                    
            # Check status again (it should be 'ready' now if it was draft and succeeded, or if it started as ready)
            db.refresh(player)
            if player.status == 'ready' or (player.base_image_path and player.status != 'done'):
                # --- 8 Views ---
                log_system(db, "[一键生成角色完整图]", current_progress, f"正在为 {player.player_name} 生成8镜图...")
                task_8 = models.Task(project_id=project_id, player_id=player.id, task_type="GEN_8VIEWS", status="queued", payload_json="{}")
                db.add(task_8)
                db.commit()
                
                success_8 = await wait_for_task(db, task_8.id, timeout=900) # 8 views take longer
                db.refresh(task_8)
                
                if success_8:
                     log_system(db, "[一键生成角色完整图]", current_progress, f"角色 {player.player_name} 8镜图生成成功")
                else:
                     if task_8.result_json and "Global Stop" in task_8.result_json:
                         log_system(db, "[一键生成角色完整图]", current_progress, "用户终止任务，批量处理停止。", "WARNING")
                         return
                     log_system(db, "[一键生成角色完整图]", current_progress, f"角色 {player.player_name} 8镜图生成失败", "ERROR")
            else:
                log_system(db, "[一键生成角色完整图]", current_progress, f"角色 {player.player_name} 状态异常 ({player.status})，无法继续", "WARNING")

        log_system(db, "[一键生成角色完整图]", f"[{total}/{total}]", "批量任务执行完毕")
        
    except Exception as e:
        log_system(db, "[一键生成角色完整图]", "ERROR", f"批量任务异常中断: {str(e)}", "ERROR")
    finally:
        db.close()

async def process_batch_gen_scene_base(project_id: int):
    db = SessionLocal()
    try:
        project = crud.get_project(db, project_id)
        if not project:
            return
            
        scenes = crud.get_scenes_by_project(db, project_id)
        total = len(scenes)
        
        log_system(db, "[一键生成所有场景基图]", f"[0/{total}]", f"开始处理项目 {project.name} 的批量场景基图生成任务")
        
        for i, scene in enumerate(scenes):
            # Refresh scene object to get latest status
            db.refresh(scene)
            
            current_progress = f"[{i+1}/{total}]"
            
            # Skip if already generated (has base image)
            if scene.base_image_path:
                log_system(db, "[一键生成所有场景基图]", current_progress, f"场景 {scene.name} 已有基图，跳过")
                continue
                
            # Process if no base image (Draft or Generating but failed/stuck)
            if not scene.base_image_path:
                # --- Prompt ---
                if not scene.prompt_pos:
                    log_system(db, "[一键生成所有场景基图]", current_progress, f"正在为 {scene.name} 生成提示词...")
                    task_p = models.Task(project_id=project_id, scene_id=scene.id, task_type="GEN_SCENE_PROMPT", status="queued", payload_json="{}")
                    db.add(task_p)
                    db.commit()
                    
                    success_p = await wait_for_task(db, task_p.id)
                    db.refresh(task_p)
                    
                    await asyncio.sleep(0.1) # Yield control
                    
                    if not success_p:
                        if task_p.result_json and "Global Stop" in task_p.result_json:
                            log_system(db, "[一键生成所有场景基图]", current_progress, "用户终止任务，批量处理停止。", "WARNING")
                            return
                        log_system(db, "[一键生成所有场景基图]", current_progress, f"场景 {scene.name} 提示词失败", "ERROR")
                        continue
                    
                    # REFRESH SCENE! The previous task updated the scene prompt in DB
                    # But our local 'scene' object is stale.
                    db.refresh(scene)
                
                # --- Base ---
                log_system(db, "[一键生成所有场景基图]", current_progress, f"提示词成功，正在生成基图...")
                
                sys_configs = db.query(models.SystemConfig).all()
                sys_conf = {c.key: c.value for c in sys_configs}
                
                # Fetch settings or defaults for scene
                default_seed = int(sys_conf.get('scene_gen_seed', 264590))
                default_width = int(sys_conf.get('scene_gen_width', 1024))
                default_height = int(sys_conf.get('scene_gen_height', 768))

                payload = {
                    "seed": default_seed,
                    "width": default_width,
                    "height": default_height
                }
                
                log_system(db, "[一键生成所有场景基图]", current_progress, f"Payload: {json.dumps(payload)}")
                
                task_b = models.Task(project_id=project_id, scene_id=scene.id, task_type="GEN_SCENE_BASE", status="queued", payload_json=json.dumps(payload))
                db.add(task_b)
                db.commit()
                
                success_b = await wait_for_task(db, task_b.id, timeout=600)
                db.refresh(task_b)
                
                await asyncio.sleep(0.1) # Yield control
                
                if not success_b:
                    if task_b.result_json and "Global Stop" in task_b.result_json:
                        log_system(db, "[一键生成所有场景基图]", current_progress, "用户终止任务，批量处理停止。", "WARNING")
                        return
                    log_system(db, "[一键生成所有场景基图]", current_progress, f"场景 {scene.name} 基图失败", "ERROR")
                    continue
                else:
                    log_system(db, "[一键生成所有场景基图]", current_progress, f"场景 {scene.name} 基图生成成功")

        log_system(db, "[一键生成所有场景基图]", f"[{total}/{total}]", "批量任务执行完毕")
        
    except Exception as e:
        log_system(db, "[一键生成所有场景基图]", "ERROR", f"批量任务异常中断: {str(e)}", "ERROR")
    finally:
        db.close()

async def process_batch_gen_scene_merge(project_id: int):
    db = SessionLocal()
    try:
        project = crud.get_project(db, project_id)
        if not project:
            return
            
        scenes = crud.get_scenes_by_project(db, project_id)
        total = len(scenes)
        
        log_system(db, "[一键生成角色合并图]", f"[0/{total}]", f"开始处理项目 {project.name} 的批量角色合并任务")
        
        for i, scene in enumerate(scenes):
            current_progress = f"[{i+1}/{total}]"
            
            # Logic: Only process if status is 'generated' (has base, no merge) or 'in_progress'
            # Or if base exists and merge does NOT exist?
            # User said: "Status in_progress only" (进行中).
            # Let's interpret 'in_progress' as: has base image, but not completed.
            # Our scene status logic: draft -> generated (base done) -> completed (merge done)
            # So we target 'generated'.
            
            if not scene.base_image_path:
                log_system(db, "[一键生成角色合并图]", current_progress, f"场景 {scene.name} 还没有基图，跳过", "WARNING")
                continue
                
            if scene.merged_image_path:
                log_system(db, "[一键生成角色合并图]", current_progress, f"场景 {scene.name} 已合并，跳过")
                continue
                
            # Check Players
            links = db.query(models.ScenePlayerLink).filter(models.ScenePlayerLink.scene_id == scene.id).all()
            if not links:
                log_system(db, "[一键生成角色合并图]", current_progress, f"场景 {scene.name} 没有绑定角色，跳过", "WARNING")
                continue
                
            all_players_ready = True
            missing_players = []
            
            for link in links:
                p = db.query(models.Player).filter(models.Player.id == link.player_id).first()
                if not p:
                    continue
                # Check if player is ready (has views or at least base)
                # Ideally 'done' (8 views)
                if not p.base_image_path:
                    all_players_ready = False
                    missing_players.append(p.player_name)
            
            if not all_players_ready:
                log_system(db, "[一键生成角色合并图]", current_progress, f"场景 {scene.name} 关联的角色 {','.join(missing_players)} 未准备好（无基图），跳过", "WARNING")
                continue
                
            # Create Merge Task
            log_system(db, "[一键生成角色合并图]", current_progress, f"正在为 {scene.name} 合并角色...")
            
            # Use default seed from system config
            sys_configs = db.query(models.SystemConfig).all()
            sys_conf = {c.key: c.value for c in sys_configs}
            default_seed = int(sys_conf.get('scene_gen_seed', 264590))
            
            payload = {"seed": default_seed} 
            
            log_system(db, "[一键生成角色合并图]", current_progress, f"Payload: {json.dumps(payload)}")
            
            task_m = models.Task(
                project_id=project_id, 
                scene_id=scene.id, 
                task_type="SCENE_MERGE", 
                status="queued", 
                payload_json=json.dumps(payload)
            )
            db.add(task_m)
            db.commit()
            
            success_m = await wait_for_task(db, task_m.id, timeout=1200) # Merge can take long if multiple chars
            db.refresh(task_m)
            
            await asyncio.sleep(0.1) # Yield control
            
            if not success_m:
                if task_m.result_json and "Global Stop" in task_m.result_json:
                    log_system(db, "[一键生成角色合并图]", current_progress, "用户终止任务，批量处理停止。", "WARNING")
                    return
                log_system(db, "[一键生成角色合并图]", current_progress, f"场景 {scene.name} 合并失败", "ERROR")
            else:
                log_system(db, "[一键生成角色合并图]", current_progress, f"场景 {scene.name} 合并成功")

        log_system(db, "[一键生成角色合并图]", f"[{total}/{total}]", "批量任务执行完毕")
        
    except Exception as e:
        log_system(db, "[一键生成角色合并图]", "ERROR", f"批量任务异常中断: {str(e)}", "ERROR")
    finally:
        db.close()

async def process_batch_regenerate_all(project_id: int):
    import os
    from app.config import config
    
    db = SessionLocal()
    try:
        project = crud.get_project(db, project_id)
        if not project:
            return
            
        log_system(db, "[一键重新生成]", "START", f"开始执行项目 {project.name} 的全流程重新生成任务")
        
        # --- Step 1: Reset & Clean ---
        log_system(db, "[一键重新生成]", "CLEAN", "正在清理历史数据和文件...")
        
        base_dir = os.path.dirname(config.OUTPUT_DIR)
        
        # 1.1 Clean Players
        players = crud.get_players_by_project(db, project_id)
        for p in players:
            # Delete files
            paths_to_delete = []
            if p.base_image_path:
                paths_to_delete.append(p.base_image_path)
            if p.views_json:
                try:
                    views = json.loads(p.views_json)
                    paths_to_delete.extend(views.values())
                except:
                    pass
            
            for path in paths_to_delete:
                try:
                    if os.path.isabs(path):
                        abs_path = path
                    else:
                        abs_path = os.path.join(base_dir, path.lstrip("/\\"))
                    
                    if os.path.exists(abs_path):
                        os.remove(abs_path)
                        # print(f"Deleted: {abs_path}")
                except Exception as e:
                    print(f"Error deleting file {path}: {e}")

            # Reset DB - Keep prompts
            p.status = 'draft'
            p.base_image_path = None
            p.views_json = None
            db.add(p)
            
        # 1.2 Clean Scenes
        scenes = crud.get_scenes_by_project(db, project_id)
        for s in scenes:
            # Delete files
            paths_to_delete = []
            if s.base_image_path:
                paths_to_delete.append(s.base_image_path)
            if s.merged_image_path:
                paths_to_delete.append(s.merged_image_path)
                
            for path in paths_to_delete:
                try:
                    if os.path.isabs(path):
                        abs_path = path
                    else:
                        abs_path = os.path.join(base_dir, path.lstrip("/\\"))
                    
                    if os.path.exists(abs_path):
                        os.remove(abs_path)
                except Exception as e:
                    print(f"Error deleting file {path}: {e}")

            # Reset DB - Keep prompts
            s.status = 'draft'
            s.base_image_path = None
            s.merged_image_path = None
            db.add(s)
            
        db.commit()
        log_system(db, "[一键重新生成]", "CLEAN", "历史数据清理完成，开始执行生成流程...")
        
        # --- Step 2: Sequential Execution ---
        
        # 2.1 Gen All Base
        await process_batch_gen_base(project_id)
        
        # 2.2 Gen All Complete (8 Views)
        # Note: process_batch_gen_complete handles 'ready' players (which they should be now)
        # IMPORTANT: We must close the current DB session before calling other async functions 
        # if those functions create their own sessions, to avoid connection pool exhaustion or locks.
        # But process_batch_gen_base creates its own session.
        # Wait, the issue is likely that we are calling functions that use `db = SessionLocal()`
        # inside an async function that also holds a session if we passed it?
        # Here `process_batch_regenerate_all` creates `db`.
        # And `process_batch_gen_base` creates `db`.
        # This is fine as long as they are separate.
        
        # However, we need to make sure the data is committed before the next step starts reading it.
        # We did db.commit() after cleaning.
        
        # Let's add a small delay to ensure DB commit propagation if needed, though commit() is synchronous.
        
        await process_batch_gen_base(project_id)
        
        # Re-check project existence or just proceed?
        # The sub-functions create their own sessions, so they will see the committed state.
        
        await process_batch_gen_complete(project_id)
        
        await process_batch_gen_scene_base(project_id)
        
        await process_batch_gen_scene_merge(project_id)
        
        log_system(db, "[一键重新生成]", "DONE", "全流程重新生成任务执行完毕", "SUCCESS")
        
    except Exception as e:
        log_system(db, "[一键重新生成]", "ERROR", f"全流程任务异常中断: {str(e)}", "ERROR")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

async def process_batch_gen_video(project_id: int):
    """
    Batch generate videos for all COMPLETED scenes (those with merged images).
    """
    db = SessionLocal()
    try:
        project = crud.get_project(db, project_id)
        if not project:
            return
            
        # Get scenes that are completed (have merged_image_path)
        scenes = crud.get_scenes_by_project(db, project_id)
        total = len(scenes)
        
        log_system(db, "[一键生成所有视频]", f"[0/{total}]", f"开始处理项目 {project.name} 的批量视频生成任务")
        
        # Filter scenes
        target_scenes = []
        for s in scenes:
            # Must have merged image
            if not s.merged_image_path:
                continue
            
            # Check if video already exists?
            # User requirement: "Only appear in Scene List... completed... then appear in list".
            # The list shows videos.
            # If we run "Batch Generate Video", we should generate for all ready scenes.
            # Check if video exists
            video = crud.get_video_by_scene(db, s.id)
            if video and video.status == 'completed' and video.video_path:
                continue
                
            target_scenes.append(s)
            
        real_total = len(target_scenes)
        log_system(db, "[一键生成所有视频]", f"准备中", f"共发现 {real_total} 个就绪场景待生成视频")
        
        for i, scene in enumerate(target_scenes):
            current_progress = f"[{i+1}/{real_total}]"
            
            # Create or Get Video Entry
            video = crud.create_video(db, project_id, scene.id)
            
            if video.status == 'completed':
                log_system(db, "[一键生成所有视频]", current_progress, f"场景 {scene.name} 视频已存在，跳过")
                continue
                
            # Step 1: Generate Prompt
            if not video.prompt_pos:
                log_system(db, "[一键生成所有视频]", current_progress, f"正在为 {scene.name} 生成视频提示词...")
                
                task_p = models.Task(
                    project_id=project_id, 
                    video_id=video.id, # Link to video
                    task_type="GEN_VIDEO_PROMPT", 
                    status="queued", 
                    payload_json="{}"
                )
                db.add(task_p)
                db.commit()
                
                success_p = await wait_for_task(db, task_p.id)
                db.refresh(task_p)
                db.refresh(video) # Refresh video to get prompts
                
                if not success_p:
                    log_system(db, "[一键生成所有视频]", current_progress, f"场景 {scene.name} 视频提示词生成失败", "ERROR")
                    continue
            
            # Step 2: Generate Video
            log_system(db, "[一键生成所有视频]", current_progress, f"提示词准备就绪，开始生成视频...")
            
            # Fetch System Defaults
            sys_configs = db.query(models.SystemConfig).all()
            sys_conf = {c.key: c.value for c in sys_configs}
            
            # Default Params
            default_seed = int(sys_conf.get('video_gen_seed', 264590))
            
            # Video params - Use DB values if available (from LLM), otherwise defaults
            # User requirement: Use LLM returned Length and FPS
            width = video.width if video.width and video.width > 0 else int(sys_conf.get('video_gen_width', 640))
            height = video.height if video.height and video.height > 0 else int(sys_conf.get('video_gen_height', 640))
            length = video.length if video.length and video.length > 0 else int(sys_conf.get('video_gen_length', 81))
            fps = video.fps if video.fps and video.fps > 0 else int(sys_conf.get('video_gen_fps', 16))
            
            # Ensure DB is updated with final values used
            video.width = width
            video.height = height
            video.length = length
            video.fps = fps
            video.seed = default_seed # Batch always uses default seed unless we want random? User said "System Default".
            db.commit()
            
            payload = {
                "seed": default_seed,
                "width": width,
                "height": height,
                "length": length,
                "fps": fps,
                "prompt_pos": video.prompt_pos,
                "prompt_neg": video.prompt_neg
            }
            
            log_system(db, "[一键生成所有视频]", current_progress, f"Payload: {json.dumps(payload, ensure_ascii=False)}")
            
            task_v = models.Task(
                project_id=project_id,
                video_id=video.id,
                task_type="GEN_VIDEO",
                status="queued",
                payload_json=json.dumps(payload, ensure_ascii=False)
            )
            db.add(task_v)
            db.commit()
            
            # Video generation takes long time (e.g. 5-10 mins for Wan2.2 14B?)
            # Set long timeout
            success_v = await wait_for_task(db, task_v.id, timeout=3600) 
            db.refresh(task_v)
            
            if success_v:
                log_system(db, "[一键生成所有视频]", current_progress, f"场景 {scene.name} 视频生成成功")
            else:
                if task_v.result_json and "Global Stop" in task_v.result_json:
                    log_system(db, "[一键生成所有视频]", current_progress, "用户终止任务，批量处理停止。", "WARNING")
                    return
                log_system(db, "[一键生成所有视频]", current_progress, f"场景 {scene.name} 视频生成失败", "ERROR")

        log_system(db, "[一键生成所有视频]", "DONE", "批量视频生成任务结束")
        
    except Exception as e:
        log_system(db, "[一键生成所有视频]", "ERROR", f"批量视频任务异常: {str(e)}", "ERROR")
        import traceback
        traceback.print_exc()
    finally:
        db.close()
