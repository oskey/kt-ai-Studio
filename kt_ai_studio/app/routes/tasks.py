from fastapi import APIRouter, Depends, Form, Request, Query
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from app.db import crud, session, models
from typing import List
from datetime import datetime
import json

router = APIRouter()

@router.post("/tasks/create")
async def create_task_endpoint(
    player_id: int = Form(...),
    task_type: str = Form(...),
    width: int = Form(1024),
    height: int = Form(768),
    seed: int = Form(264590),
    db: Session = Depends(session.get_db)
):
    player = crud.get_player(db, player_id)
    if player:
        # Construct payload with optional parameters
        payload = {}
        if task_type == "GEN_BASE":
            payload = {
                "width": width,
                "height": height,
                "seed": seed
            }
            
        crud.create_task(
            db, 
            project_id=player.project_id, 
            player_id=player.id, 
            task_type=task_type,
            payload=payload
        )
    
    return RedirectResponse(url=f"/players/{player_id}", status_code=303)

@router.post("/tasks/clear_logs")
async def clear_task_logs(
    player_id: int = Form(...),
    db: Session = Depends(session.get_db)
):
    # Only delete tasks for this player that are done or failed
    db.query(models.Task).filter(
        models.Task.player_id == player_id,
        models.Task.status.in_(["done", "failed"])
    ).delete(synchronize_session=False)
    db.commit()
    
    return RedirectResponse(url=f"/players/{player_id}", status_code=303)

@router.post("/tasks/clear_logs_scene")
async def clear_task_logs_scene(
    scene_id: int = Form(...),
    db: Session = Depends(session.get_db)
):
    # Only delete tasks for this scene that are done or failed
    db.query(models.Task).filter(
        models.Task.scene_id == scene_id,
        models.Task.status.in_(["done", "failed"])
    ).delete(synchronize_session=False)
    db.commit()
    
    return RedirectResponse(url=f"/scenes/{scene_id}", status_code=303)

@router.post("/tasks/force_reset_scene")
async def force_reset_tasks_scene(
    scene_id: int = Form(...),
    db: Session = Depends(session.get_db)
):
    """
    Force delete ALL tasks for a scene (Pure SQL Delete).
    """
    try:
        print(f"Force Reset: Deleting all tasks for scene {scene_id} (Pure SQL)...")
        
        db.query(models.Task).filter(
            models.Task.scene_id == scene_id
        ).delete(synchronize_session=False)
        
        db.commit()
        
        return JSONResponse({"status": "success", "message": "Tasks deleted successfully."})
        
    except Exception as e:
        print(f"Force Reset Failed: {e}")
        db.rollback()
        return JSONResponse({"detail": str(e)}, status_code=500)

@router.post("/tasks/force_reset")
async def force_reset_tasks(
    player_id: int = Form(...),
    db: Session = Depends(session.get_db)
):
    """
    Force delete ALL tasks for a player (Pure SQL Delete).
    As requested by user: "Don't worry about ComfyUI, just delete the SQL records".
    """
    try:
        # 1. Pure DB Delete
        # We trust that the background thread handles 'task deleted' errors gracefully 
        # (via the try/except blocks we added in manager.py) or that the DB is not locked.
        # With timeout=30 in session.py, we should be safe even if locked briefly.
        
        print(f"Force Reset: Deleting all tasks for player {player_id} (Pure SQL)...")
        
        db.query(models.Task).filter(
            models.Task.player_id == player_id
        ).delete(synchronize_session=False)
        
        db.commit()
        
        return JSONResponse({"status": "success", "message": "Tasks deleted successfully."})
        
    except Exception as e:
        print(f"Force Reset Failed: {e}")
        db.rollback()
        return JSONResponse({"detail": str(e)}, status_code=500)

@router.get("/api/tasks/status")
async def get_tasks_status(
    task_ids: str = Query("", description="Comma separated task IDs"),
    db: Session = Depends(session.get_db)
):
    try:
        if not task_ids:
            return JSONResponse({})
            
        ids = [int(id) for id in task_ids.split(",") if id.isdigit()]
        if not ids:
            return JSONResponse({})
            
        tasks = db.query(models.Task).filter(models.Task.id.in_(ids)).all()
        
        # Timezone conversion
        from app.config import config
        import pytz
        local_tz = pytz.timezone(config.APP_TIMEZONE)
        
        result = {}
        for task in tasks:
            # Time Calculations
            now = datetime.utcnow() # Naive UTC
            run_time_str = ""
            started_at_local = ""
            completed_at_local = ""
            duration_str = ""
            
            if task.started_at:
                # 1. Local display string
                # Ensure it's timezone aware for conversion
                if task.started_at.tzinfo is None:
                    dt_utc = task.started_at.replace(tzinfo=pytz.utc)
                else:
                    dt_utc = task.started_at
                    
                dt_local = dt_utc.astimezone(local_tz)
                started_at_local = dt_local.strftime('%H:%M:%S')
                
                # 2. Runtime / Duration (UTC Delta)
                if task.status == 'running':
                    # Ensure both are naive for subtraction (or both aware)
                    # task.started_at from DB is usually naive UTC
                    started_at_naive = task.started_at.replace(tzinfo=None)
                    delta = now - started_at_naive
                    
                    seconds = int(delta.total_seconds())
                    run_time_str = f"{seconds}s"
                    if seconds > 60:
                        run_time_str = f"{seconds // 60}m {seconds % 60}s"
                        
                elif task.duration:
                    seconds = task.duration
                    duration_str = f"{seconds}s"
                    if seconds > 60:
                        duration_str = f"{seconds // 60}m {seconds % 60}s"
            
            if task.completed_at:
                if task.completed_at.tzinfo is None:
                     dt_utc = task.completed_at.replace(tzinfo=pytz.utc)
                else:
                     dt_utc = task.completed_at
                     
                dt_local = dt_utc.astimezone(local_tz)
                completed_at_local = dt_local.strftime('%H:%M:%S')

            # Incremental Results
            result_len = 0
            views_status = []
            if task.result_json:
                result_len = len(task.result_json)
                try:
                    data = json.loads(task.result_json)
                    if "views_json" in data:
                        views_status = list(data["views_json"].keys())
                except:
                    pass
                
            result[task.id] = {
                "status": task.status, 
                "progress": task.progress or 0,
                "eta": getattr(task, 'eta', 0),
                "result_len": result_len,
                "run_time": run_time_str,
                "duration": duration_str,
                "started_at": started_at_local,
                "completed_at": completed_at_local,
                "views_status": views_status 
            }
        return JSONResponse(result)
        
    except Exception as e:
        print(f"Error in get_tasks_status: {e}")
        # Return empty or error to avoid frontend loop crash
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get("/api/tasks/{task_id}")
async def get_task_detail(
    task_id: int,
    db: Session = Depends(session.get_db)
):
    task = crud.get_task(db, task_id)
    if not task:
        return JSONResponse({"error": "Task not found"}, status_code=404)
        
    return JSONResponse({
        "id": task.id,
        "status": task.status,
        "progress": task.progress or 0,
        "result_json": task.result_json,
        "error": task.error, # Assuming error field exists or we parse it from result
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None
    })

@router.post("/tasks/interrupt")
async def interrupt_task(
    task_id: int = Form(None),
    db: Session = Depends(session.get_db)
):
    """
    Interrupts a running task. 
    If task_id is provided, marks it as failed/cancelled in DB.
    Always sends interrupt signal to ComfyUI to stop any execution.
    """
    import traceback
    
    try:
        # Import lazily to ensure it's initialized
        from app.services.tasks.manager import task_manager
        
        # 1. Send interrupt to ComfyUI (Global interrupt)
        if task_manager and hasattr(task_manager, 'comfy_client'):
            try:
                print("Sending interrupt to ComfyUI...")
                task_manager.comfy_client.interrupt()
            except Exception as e:
                print(f"Warning: Failed to send interrupt to ComfyUI: {e}")
                traceback.print_exc()
        else:
            print("Error: task_manager or comfy_client not available")
            # Don't fail hard, try to update DB at least
    
        # 2. Update Task Status in DB
        if task_id:
            task = crud.get_task(db, task_id)
            if task and task.status in ['queued', 'running']:
                print(f"Marking task {task_id} as failed (Interrupted)...")
                task.status = 'failed'
                task.result_json = json.dumps({"error": "Interrupted by user"})
                task.completed_at = datetime.utcnow()
                db.commit()
                
        return JSONResponse({"status": "interrupted"})
        
    except Exception as e:
        print(f"Critical Error in interrupt_task: {e}")
        traceback.print_exc()
        # Return 200 even on error to prevent frontend crash loop, but log it
        return JSONResponse({"status": "error", "message": str(e)}, status_code=200)

@router.post("/tasks/stop_all")
async def stop_all_tasks(db: Session = Depends(session.get_db)):
    """
    Stops ALL running and queued tasks globally.
    1. Interrupts ComfyUI.
    2. Clears ComfyUI Queue.
    3. Marks all running/queued tasks in DB as failed.
    """
    import traceback
    from app.services.tasks.manager import task_manager
    from app.db import models # Re-import just in case
    
    count = 0
    try:
        # 1. Interrupt ComfyUI
        if task_manager and hasattr(task_manager, 'comfy_client'):
            try:
                print("Global Stop: Interrupting ComfyUI...")
                task_manager.comfy_client.interrupt()
                
                print("Global Stop: Clearing ComfyUI Queue...")
                task_manager.comfy_client.clear_queue()
                
            except Exception as e:
                print(f"Global Stop: Failed to interrupt ComfyUI: {e}")
                
        # 2. Mark all running/queued tasks as failed
        tasks = db.query(models.Task).filter(
            models.Task.status.in_(['queued', 'running'])
        ).all()
        
        for task in tasks:
            task.status = 'failed'
            task.result_json = json.dumps({"error": "Stopped by user (Global Stop)"})
            task.completed_at = datetime.utcnow()
            count += 1
            
        db.commit()
        
        # Also log to system log
        try:
            log = models.SystemLog(
                module="Task Control",
                progress_info="STOP",
                content=f"用户执行了一键停止，{count} 个任务被终止，ComfyUI队列已清空。",
                level="WARNING"
            )
            db.add(log)
            db.commit()
        except:
            pass
            
        return JSONResponse({"status": "success", "count": count})
        
    except Exception as e:
        print(f"Global Stop Failed: {e}")
        traceback.print_exc()
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
