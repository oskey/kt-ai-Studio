from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.db import crud, session, models
from pathlib import Path
import json

from app.config import config
from app.utils import to_web_path

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")
templates.env.globals["to_web_path"] = to_web_path

@router.post("/projects/{project_id}/scenes")
async def create_scene(
    project_id: int,
    name: str = Form(...),
    scene_type: str = Form("indoor"),
    base_desc: str = Form(...),
    episode: int = Form(1),
    shot: int = Form(1),
    related_players: list[int] = Form([]), # Receives list of IDs
    db: Session = Depends(session.get_db)
):
    project = crud.get_project(db, project_id)
    if not project:
        return RedirectResponse(url="/projects", status_code=303)
        
    crud.create_scene(
        db, 
        project_id, 
        name, 
        scene_type, 
        base_desc,
        episode,
        shot,
        related_players
    )
    return RedirectResponse(url=f"/projects/{project_id}", status_code=303)

@router.get("/scenes/{scene_id}", response_class=HTMLResponse)
async def view_scene(request: Request, scene_id: int, db: Session = Depends(session.get_db)):
    scene = crud.get_scene(db, scene_id)
    if not scene:
        return HTMLResponse("Scene not found", status_code=404)
        
    tasks = crud.get_tasks_by_scene(db, scene_id)
    
    # Pre-process tasks for display (same as player_detail)
    from app.config import config
    import pytz
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

    is_generating = any(task.status in ['queued', 'running'] for task in tasks)
    
    return templates.TemplateResponse("scene_detail.html", {
        "request": request, 
        "scene": scene, 
        "tasks": tasks,
        "is_generating": is_generating,
        "openai_configured": bool(config.OPENAI_API_KEY and not config.OPENAI_API_KEY.startswith("sk-..."))
    })

@router.post("/scenes/{scene_id}/update")
async def update_scene(
    scene_id: int, 
    name: str = Form(...),
    scene_type: str = Form(...),
    base_desc: str = Form(...),
    episode: int = Form(...),
    shot: int = Form(...),
    related_players: list[int] = Form([]),
    db: Session = Depends(session.get_db)
):
    scene = crud.get_scene(db, scene_id)
    if scene:
        scene.name = name
        scene.scene_type = scene_type
        scene.base_desc = base_desc
        scene.episode = episode
        scene.shot = shot
        
        # Update related players
        if related_players:
            players = db.query(models.Player).filter(models.Player.id.in_(related_players)).all()
            scene.related_players = players
        else:
            scene.related_players = []
            
        db.commit()
        return RedirectResponse(url=f"/projects/{scene.project_id}", status_code=303)
    return RedirectResponse(url="/projects", status_code=303)

@router.post("/scenes/{scene_id}/update_prompts")
async def update_scene_prompts(
    scene_id: int, 
    prompt_pos: str = Form(""),
    prompt_neg: str = Form(""),
    scene_desc: str = Form(""),
    db: Session = Depends(session.get_db)
):
    crud.update_scene_prompts(db, scene_id, prompt_pos, prompt_neg, scene_desc)
    return RedirectResponse(url=f"/scenes/{scene_id}", status_code=303)

@router.post("/scenes/{scene_id}/gen_prompt")
async def gen_scene_prompt(scene_id: int, db: Session = Depends(session.get_db)):
    scene = crud.get_scene(db, scene_id)
    if scene:
        crud.create_task(db, scene.project_id, "GEN_SCENE_PROMPT", scene_id=scene_id)
        crud.update_scene_status(db, scene_id, "generating_prompt")
    return RedirectResponse(url=f"/scenes/{scene_id}", status_code=303)

@router.post("/scenes/{scene_id}/gen_base")
async def gen_scene_base(
    scene_id: int, 
    seed: int = Form(0),
    width: int = Form(1024),
    height: int = Form(768),
    db: Session = Depends(session.get_db)
):
    scene = crud.get_scene(db, scene_id)
    if scene:
        # Check if prompts exist
        if not scene.prompt_pos:
            # Maybe auto-generate prompt?
            # User said: "生成 Scene Prompt (LLM)" -> "生成 Scene Base Image (ComfyUI)"
            # Better to require prompt first.
            pass
            
        payload = {
            "seed": seed,
            "width": width,
            "height": height
        }
        crud.create_task(db, scene.project_id, "GEN_SCENE_BASE", scene_id=scene_id, payload=payload)
        crud.update_scene_status(db, scene_id, "generating")
    return RedirectResponse(url=f"/scenes/{scene_id}", status_code=303)

@router.post("/scenes/{scene_id}/clear_files")
async def clear_scene_files(scene_id: int, db: Session = Depends(session.get_db)):
    """
    Physically deletes all generated files for a scene and resets its status.
    Clears prompts, scene_desc, and base_image_path (Full Reset).
    """
    import os
    import shutil
    from app.config import config
    
    scene = crud.get_scene(db, scene_id)
    if scene:
        project_code = scene.project.project_code
        scene_folder_name = f"{scene.id}_{scene.name}"
        scene_dir = os.path.join(config.OUTPUT_DIR, project_code, "scenes", scene_folder_name)
        
        # Physical Deletion
        if os.path.exists(scene_dir):
            try:
                shutil.rmtree(scene_dir)
                print(f"[Clear Files] Deleted directory: {scene_dir}")
            except Exception as e:
                print(f"[Clear Files] Failed to delete directory {scene_dir}: {e}")
                
        # Reset Scene State (Clear Prompts Too)
        scene.base_image_path = None
        scene.prompt_pos = ""
        scene.prompt_neg = ""
        scene.scene_desc = ""
        scene.status = "draft"
        db.commit()
        
    return RedirectResponse(url=f"/scenes/{scene_id}", status_code=303)

@router.post("/scenes/{scene_id}/delete")
async def delete_scene(scene_id: int, db: Session = Depends(session.get_db)):
    scene = crud.get_scene(db, scene_id)
    if scene:
        project_id = scene.project_id
        
        # Physical deletion (Optional but good practice)
        import os
        import shutil
        from app.config import config
        
        project_code = scene.project.project_code
        scene_folder_name = f"{scene.id}_{scene.name}"
        scene_dir = os.path.join(config.OUTPUT_DIR, project_code, "scenes", scene_folder_name)
        
        if os.path.exists(scene_dir):
            try:
                shutil.rmtree(scene_dir)
            except:
                pass
                
        crud.delete_scene(db, scene_id)
        return RedirectResponse(url=f"/projects/{project_id}", status_code=303)
    return RedirectResponse(url="/projects", status_code=303)
