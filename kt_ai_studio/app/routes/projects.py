from typing import List
from fastapi import APIRouter, Depends, Request, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.db import crud, session, models
from pathlib import Path
import shutil
import os
import json
from pydantic import BaseModel
from app.config import config
from app.utils import to_web_path

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")
templates.env.globals["to_web_path"] = to_web_path

@router.get("/projects", response_class=HTMLResponse)
async def list_projects(request: Request, db: Session = Depends(session.get_db)):
    projects = crud.get_projects(db)
    styles = crud.get_style_presets(db)
    return templates.TemplateResponse("projects.html", {
        "request": request, 
        "projects": projects,
        "styles": styles
    })

@router.post("/projects")
async def create_project(
    name: str = Form(...),
    project_code: str = Form(...),
    style_id: int = Form(...),
    mark: str = Form(None),
    db: Session = Depends(session.get_db)
):
    try:
        crud.create_project(db, name, project_code, style_id, mark)
    except Exception as e:
        # Simplified error handling
        print(f"Error creating project: {e}")
    return RedirectResponse(url="/projects", status_code=303)

class StoryGenRequest(BaseModel):
    content: str
    mode: str = "append"
    episode_start: int = 1
    max_characters: int = 5
    max_scenes: int = 10
    single_only: bool = False

@router.post("/projects/{project_id}/auto_generate_story")
async def auto_generate_story(
    project_id: int,
    req: StoryGenRequest,
    db: Session = Depends(session.get_db)
):
    project = crud.get_project(db, project_id)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)
        
    task = models.Task(
        project_id=project.id,
        task_type="AUTO_GENERATE_STORY",
        status="queued",
        payload_json=json.dumps({
            "content": req.content,
            "mode": req.mode,
            "episode_start": req.episode_start,
            "max_characters": req.max_characters,
            "max_scenes": req.max_scenes,
            "single_only": req.single_only
        })
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    
    return {"status": "success", "task_id": task.id}

@router.get("/projects/{project_id}", response_class=HTMLResponse)
async def view_project(request: Request, project_id: int, db: Session = Depends(session.get_db)):
    project = crud.get_project(db, project_id)
    if not project:
        return HTMLResponse("Project not found", status_code=404)
    players = crud.get_players_by_project(db, project_id)
    scenes = crud.get_scenes_by_project(db, project_id)
    return templates.TemplateResponse("project_detail.html", {
        "request": request, 
        "project": project, 
        "players": players,
        "scenes": scenes
    })

@router.post("/projects/{project_id}/edit")
async def edit_project(
    project_id: int,
    name: str = Form(...),
    style_id: int = Form(...),
    mark: str = Form(None),
    db: Session = Depends(session.get_db)
):
    crud.update_project(db, project_id, name, style_id, mark)
    return RedirectResponse(url="/projects", status_code=303)

@router.post("/projects/{project_id}/delete")
async def delete_project(project_id: int, db: Session = Depends(session.get_db)):
    # 1. Get project info first to get project_code for file deletion
    project = crud.get_project(db, project_id)
    if not project:
        return RedirectResponse(url="/projects", status_code=303)
        
    project_code = project.project_code
    
    # 2. Delete from DB (Cascades to Players/Tasks)
    deleted = crud.delete_project(db, project_id)
    
    # 3. Physical Deletion (Files)
    if deleted and project_code:
        project_dir = os.path.join(config.OUTPUT_DIR, project_code)
        if os.path.exists(project_dir):
            try:
                shutil.rmtree(project_dir)
                print(f"[Project Deletion] Physically deleted directory: {project_dir}")
            except Exception as e:
                print(f"[Project Deletion] Error deleting directory {project_dir}: {e}")
                
    return RedirectResponse(url="/projects", status_code=303)

@router.post("/projects/{project_id}/scenes")
async def create_scene(
    project_id: int, 
    name: str = Form(...), 
    episode: int = Form(...), 
    shot: int = Form(...), 
    scene_type: str = Form(...), 
    base_desc: str = Form(...), 
    related_players: List[int] = Form([]),
    db: Session = Depends(session.get_db)
):
    # Validate Scene Type
    valid_types = ["Indoor", "Outdoor", "Special"]
    normalized_type = scene_type
    if normalized_type not in valid_types:
        for vt in valid_types:
            if normalized_type.lower() == vt.lower():
                normalized_type = vt
                break
        if normalized_type not in valid_types:
            normalized_type = "Special"
            
    crud.create_scene(
        db, 
        project_id, 
        name, 
        episode, 
        shot, 
        normalized_type, 
        base_desc, 
        related_players
    )

@router.post("/projects/{project_id}/batch_gen_complete")
async def batch_gen_complete(
    project_id: int, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(session.get_db)
):
    from app.services.tasks.batch import process_batch_gen_complete
    
    project = crud.get_project(db, project_id)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)
        
    background_tasks.add_task(process_batch_gen_complete, project_id)
    
    return JSONResponse({"status": "success", "message": "Batch task started"})

@router.post("/projects/{project_id}/batch_gen_scene_base")
async def batch_gen_scene_base(
    project_id: int, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(session.get_db)
):
    from app.services.tasks.batch import process_batch_gen_scene_base
    
    project = crud.get_project(db, project_id)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)
        
    background_tasks.add_task(process_batch_gen_scene_base, project_id)
    
    return JSONResponse({"status": "success", "message": "Batch scene base task started"})

@router.post("/projects/{project_id}/batch_gen_scene_merge")
async def batch_gen_scene_merge(
    project_id: int, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(session.get_db)
):
    from app.services.tasks.batch import process_batch_gen_scene_merge
    
    project = crud.get_project(db, project_id)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)
        
    background_tasks.add_task(process_batch_gen_scene_merge, project_id)
    
    return JSONResponse({"status": "success", "message": "Batch scene merge task started"})

@router.post("/projects/{project_id}/batch_regenerate_all")
async def batch_regenerate_all(
    project_id: int, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(session.get_db)
):
    from app.services.tasks.batch import process_batch_regenerate_all
    
    project = crud.get_project(db, project_id)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)
        
    background_tasks.add_task(process_batch_regenerate_all, project_id)
    
    return JSONResponse({"status": "success", "message": "Batch regenerate all started"})

@router.post("/projects/{project_id}/batch_gen_video")
async def batch_gen_video(
    project_id: int, 
    background_tasks: BackgroundTasks,
    db: Session = Depends(session.get_db)
):
    from app.services.tasks.batch import process_batch_gen_video
    
    project = crud.get_project(db, project_id)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)
        
    background_tasks.add_task(process_batch_gen_video, project_id)
    
    return JSONResponse({"status": "success", "message": "Batch video task started"})
