from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.orm import Session
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.db.session import get_db
from app.db import models, crud
from app.services.tasks.manager import task_manager
from app.utils import to_web_path
import json
import os

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["to_web_path"] = to_web_path

@router.get("/manage", response_class=HTMLResponse)
async def video_manage_page(request: Request, scene_id: int, db: Session = Depends(get_db)):
    scene = db.query(models.Scene).filter(models.Scene.id == scene_id).first()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
        
    project = scene.project
    
    # Get System Defaults
    configs = db.query(models.SystemConfig).all()
    config_dict = {c.key: c.value for c in configs}
    
    default_width = int(config_dict.get("video_gen_width", 640))
    default_height = int(config_dict.get("video_gen_height", 640))
    default_length = int(config_dict.get("video_gen_length", 81))
    default_fps = int(config_dict.get("video_gen_fps", 16))
    default_seed = int(config_dict.get("video_gen_seed", 264590))

    # Find existing video or create placeholder in memory (not DB yet unless we want to persist defaults)
    video = db.query(models.Video).filter(models.Video.scene_id == scene_id).first()
    
    if not video:
        # Create a default video record if it doesn't exist, to simplify state management
        video = models.Video(
            project_id=project.id,
            scene_id=scene.id,
            status="draft",
            width=default_width,
            height=default_height,
            length=default_length,
            fps=default_fps,
            seed=default_seed
        )
        db.add(video)
        db.commit()
        db.refresh(video)
    elif video.status == "draft":
        # Sync defaults if video is in draft mode
        # This ensures that if the user updates system settings, draft videos reflect those changes
        video.width = default_width
        video.height = default_height
        video.length = default_length
        video.fps = default_fps
        video.seed = default_seed
        db.commit()

    # Get Tasks for this video
    tasks = db.query(models.Task).filter(models.Task.video_id == video.id).order_by(models.Task.created_at.desc()).all()

    return templates.TemplateResponse("video_detail.html", {
        "request": request,
        "project": project,
        "scene": scene,
        "video": video,
        "tasks": tasks,
        "sys_config": config_dict
    })

@router.post("/{video_id}/update")
async def update_video_settings(
    video_id: int, 
    request: Request, 
    db: Session = Depends(get_db)
):
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        return JSONResponse(status_code=404, content={"error": "Video not found"})
        
    form = await request.form()
    
    try:
        video.width = int(form.get("width", 640))
        video.height = int(form.get("height", 640))
        video.length = int(form.get("length", 81))
        video.fps = int(form.get("fps", 16))
        video.seed = int(form.get("seed", 0))
        video.prompt_pos = form.get("prompt_pos", "")
        video.prompt_neg = form.get("prompt_neg", "")
        
        db.commit()
        return JSONResponse(content={"status": "success"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/{video_id}/generate_prompts")
async def generate_video_prompts_route(
    video_id: int, 
    db: Session = Depends(get_db)
):
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        return JSONResponse(status_code=404, content={"error": "Video not found"})
        
    # Check if context exists
    if not video.scene.video_llm_context:
        return JSONResponse(status_code=400, content={"error": "Scene context missing. Please regenerate Scene Merge."})

    # Create Task
    task = models.Task(
        project_id=video.project_id,
        scene_id=video.scene_id,
        video_id=video.id,
        task_type="GEN_VIDEO_PROMPT",
        status="queued"
    )
    db.add(task)
    db.commit()
    
    # Trigger worker (in real app, worker polls, but here we can ensure it's running)
    task_manager.start()
    
    return JSONResponse(content={"status": "success", "task_id": task.id})

@router.post("/{video_id}/generate")
async def generate_video_route(
    video_id: int, 
    db: Session = Depends(get_db)
):
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        return JSONResponse(status_code=404, content={"error": "Video not found"})
        
    # Verify we have prompts
    if not video.prompt_pos:
        return JSONResponse(status_code=400, content={"error": "Please generate or enter prompts first."})
        
    # Verify scene has merged image
    if not video.scene.merged_image_path:
        return JSONResponse(status_code=400, content={"error": "Scene merged image missing."})

    # Create Task
    task = models.Task(
        project_id=video.project_id,
        scene_id=video.scene_id,
        video_id=video.id,
        task_type="GEN_VIDEO",
        status="queued",
        payload_json=json.dumps({
            "width": video.width,
            "height": video.height,
            "length": video.length,
            "fps": video.fps,
            "seed": video.seed,
            "prompt_pos": video.prompt_pos,
            "prompt_neg": video.prompt_neg
        })
    )
    db.add(task)
    video.status = "queued"
    db.commit()
    
    task_manager.start()
    
    return JSONResponse(content={"status": "success", "task_id": task.id})

@router.post("/{video_id}/delete")
async def delete_video(video_id: int, db: Session = Depends(get_db)):
    video = db.query(models.Video).filter(models.Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    # Optional: Delete file
    # if video.video_path and os.path.exists(video.video_path):
    #     os.remove(video.video_path)
        
    # Reset video fields but keep record? Or delete record?
    # User said "Manager only", but usually we might want to reset.
    # Let's just reset status and path.
    video.status = "draft"
    video.video_path = None
    db.commit()
    
    return JSONResponse(content={"status": "success"})
