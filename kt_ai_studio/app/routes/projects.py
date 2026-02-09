from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.db import crud, session, models
from pathlib import Path
import shutil
import os
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
