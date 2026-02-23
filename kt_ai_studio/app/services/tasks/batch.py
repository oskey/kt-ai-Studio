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
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        # Refresh task from DB
        # We need a fresh session or refresh the object?
        # Using the passed db session might be stale if we don't refresh.
        # But for safety in a long loop, let's query directly.
        task = db.query(models.Task).filter(models.Task.id == task_id).first()
        if not task:
            return False
            
        if task.status == 'done':
            return True
        if task.status == 'failed':
            return False
            
        await asyncio.sleep(2)
        db.refresh(task) # Important to see updates
        
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
                # Step 1: Generate Prompt
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
                success = await wait_for_task(db, task.id)
                db.refresh(task)
                if not success:
                    # Check for Global Stop
                    if task.result_json and "Global Stop" in task.result_json:
                        log_system(db, "[一键生成所有基图]", current_progress, "用户终止任务，批量处理停止。", "WARNING")
                        return

                    log_system(db, "[一键生成所有基图]", current_progress, f"角色 {player.player_name} 提示词生成失败", "ERROR")
                    continue
                    
                log_system(db, "[一键生成所有基图]", current_progress, f"角色 {player.player_name} 提示词生成成功，开始生成基图...")
                
                # Step 2: Generate Base
                # Need payload with defaults
                sys_configs = db.query(models.SystemConfig).all()
                sys_conf = {c.key: c.value for c in sys_configs}
                payload = {
                    "seed": int(sys_conf.get('default_seed', 0)),
                    "width": int(sys_conf.get('default_width', 512)),
                    "height": int(sys_conf.get('default_height', 768))
                }
                
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
                payload = {
                    "seed": int(sys_conf.get('default_seed', 0)),
                    "width": int(sys_conf.get('default_width', 512)),
                    "height": int(sys_conf.get('default_height', 768))
                }
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
