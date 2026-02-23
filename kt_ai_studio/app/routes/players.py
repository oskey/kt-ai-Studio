from fastapi import APIRouter, Depends, Request, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.db import crud, session, models
from pathlib import Path
from app.services.tasks.batch import process_batch_gen_base, process_batch_gen_complete
import json

from app.config import config
from app.utils import to_web_path

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")
templates.env.globals["to_web_path"] = to_web_path

@router.post("/projects/{project_id}/players")
async def create_player(
    project_id: int,
    player_name: str = Form(...),
    player_sex: str = Form(...),
    player_mark: str = Form(None),
    db: Session = Depends(session.get_db)
):
    crud.create_player(db, project_id, player_name, player_sex, player_mark)
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)

@router.post("/players/{player_id}/edit")
async def edit_player(
    player_id: int,
    player_name: str = Form(...),
    player_sex: str = Form(...),
    player_mark: str = Form(None),
    db: Session = Depends(session.get_db)
):
    player = crud.get_player(db, player_id)
    if player:
        crud.update_player(db, player_id, player_name, player_sex, player_mark)
        return RedirectResponse(url=f"/projects/{player.project_id}", status_code=303)
    return RedirectResponse(url="/projects", status_code=303)

@router.post("/players/{player_id}/delete")
async def delete_player(player_id: int, db: Session = Depends(session.get_db)):
    player = crud.get_player(db, player_id)
    if player:
        project_id = player.project_id
        crud.delete_player(db, player_id)
        return RedirectResponse(url=f"/projects/{project_id}", status_code=303)
    return RedirectResponse(url="/projects", status_code=303)

@router.get("/players/{player_id}", response_class=HTMLResponse)
async def view_player(request: Request, player_id: int, db: Session = Depends(session.get_db)):
    player = crud.get_player(db, player_id)
    if not player:
        return HTMLResponse("Player not found", status_code=404)
    tasks = crud.get_tasks_by_player(db, player_id)
    
    # Pre-process tasks for timezone and duration display
    import pytz
    from datetime import datetime
    local_tz = pytz.timezone(config.APP_TIMEZONE)
    
    for task in tasks:
        if task.started_at:
             dt_utc = task.started_at.replace(tzinfo=pytz.utc) if task.started_at.tzinfo is None else task.started_at
             task._started_at_display = dt_utc.astimezone(local_tz).strftime('%H:%M:%S')
        elif task.created_at:
             dt_utc = task.created_at.replace(tzinfo=pytz.utc) if task.created_at.tzinfo is None else task.created_at
             task._started_at_display = dt_utc.astimezone(local_tz).strftime('%H:%M:%S')
             
        if task.status in ['done', 'failed'] and not task.duration and task.started_at and task.completed_at:
             delta = task.completed_at - task.started_at
             task.duration = int(delta.total_seconds())
             
        if task.duration:
             seconds = task.duration
             if seconds > 60:
                 task._duration_display = f"{seconds // 60}m {seconds % 60}s"
             else:
                 task._duration_display = f"{seconds}s"
    
    # Parse JSON fields for display
    views = {}
    if player.views_json:
        try:
            views = json.loads(player.views_json)
        except:
            pass
            
    # Check if there are any running tasks
    is_generating = any(task.status in ['queued', 'running'] for task in tasks)
            
    # Fetch System Config for Defaults
    sys_configs = db.query(models.SystemConfig).all()
    sys_conf_dict = {c.key: c.value for c in sys_configs}
    
    return templates.TemplateResponse("player_detail.html", {
        "request": request, 
        "player": player, 
        "tasks": tasks,
        "views": views,
        "is_generating": is_generating,
        "openai_configured": db.query(models.LLMProfile).count() > 0,
        "sys_config": sys_conf_dict
    })

@router.post("/players/{player_id}/update_prompts")
async def update_prompts(
    player_id: int,
    prompt_pos: str = Form(...),
    prompt_neg: str = Form(...),
    player_desc: str = Form(None),
    db: Session = Depends(session.get_db)
):
    crud.update_player_prompts(db, player_id, prompt_pos, prompt_neg, player_desc)
    return RedirectResponse(url=f"/players/{player_id}", status_code=303)

@router.post("/players/{player_id}/clear_config")
async def clear_player_config(player_id: int, db: Session = Depends(session.get_db)):
    old_base, old_views_json = crud.clear_player_config(db, player_id)
    
    # Physical deletion
    import os
    import shutil
    
    # Delete Base Image
    if old_base:
        abs_base = os.path.join(os.path.dirname(config.OUTPUT_DIR), old_base)
        if os.path.exists(abs_base):
            try:
                os.remove(abs_base)
                print(f"Deleted base image: {abs_base}")
            except Exception as e:
                print(f"Error deleting base image: {e}")
                
    # Delete Views Folder
    player = crud.get_player(db, player_id)
    if player:
        project_code = player.project.project_code
        player_folder_name = f"{player.id}_{player.player_name}"
        player_dir = os.path.join(config.OUTPUT_DIR, project_code, "players", player_folder_name)
        
        base_dir = os.path.join(player_dir, "base")
        views_dir = os.path.join(player_dir, "views")
        
        if os.path.exists(base_dir):
            shutil.rmtree(base_dir, ignore_errors=True)
        if os.path.exists(views_dir):
            shutil.rmtree(views_dir, ignore_errors=True)
            
    return RedirectResponse(url=f"/players/{player_id}", status_code=303)

@router.post("/projects/{project_id}/batch_gen_base")
async def batch_gen_base(
    project_id: int, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(session.get_db)
):
    project = crud.get_project(db, project_id)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)
        
    background_tasks.add_task(process_batch_gen_base, project_id)
    return JSONResponse({"status": "success", "message": "Batch task started. Check System Logs."})

@router.post("/projects/{project_id}/batch_gen_complete")
async def batch_gen_complete(
    project_id: int, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(session.get_db)
):
    project = crud.get_project(db, project_id)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)
        
    background_tasks.add_task(process_batch_gen_complete, project_id)
    return JSONResponse({"status": "success", "message": "Batch task started. Check System Logs."})
