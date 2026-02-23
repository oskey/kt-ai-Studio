from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
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
    
    # Fetch System Config for Defaults
    sys_configs = db.query(models.SystemConfig).all()
    sys_conf_dict = {c.key: c.value for c in sys_configs}

    # Check if all related players are ready (status == 'done')
    all_players_ready = True
    for p in scene.related_players:
        if p.status != 'done':
            all_players_ready = False
            break

    return templates.TemplateResponse("scene_detail.html", {
        "request": request, 
        "scene": scene, 
        "tasks": tasks,
        "is_generating": is_generating,
        "openai_configured": db.query(models.LLMProfile).count() > 0,
        "sys_config": sys_conf_dict,
        "all_players_ready": all_players_ready
    })

@router.post("/scenes/{scene_id}/update")
async def update_scene(
    scene_id: int, 
    name: str = Form(...), 
    episode: int = Form(...),
    shot: int = Form(...),
    scene_type: str = Form(...),
    base_desc: str = Form(...),
    related_players: list[int] = Form([]),
    db: Session = Depends(session.get_db)
):
    scene = crud.get_scene(db, scene_id)
    if scene:
        scene.name = name
        scene.episode = episode
        scene.shot = shot
        
        # Validate Scene Type
        valid_types = ["Indoor", "Outdoor", "Special"]
        normalized_type = scene_type
        
        # Exact match check
        if normalized_type in valid_types:
            scene.scene_type = normalized_type
        else:
            # Case-insensitive check
            found = False
            for vt in valid_types:
                if normalized_type.lower() == vt.lower():
                    scene.scene_type = vt
                    found = True
                    break
            # Fallback
            if not found:
                scene.scene_type = "Special"
        
        scene.base_desc = base_desc
        
        # Update Related Players
        # Clear existing links
        db.query(models.ScenePlayerLink).filter(models.ScenePlayerLink.scene_id == scene.id).delete()
        
        # Add new links
        for pid in related_players:
            link = models.ScenePlayerLink(scene_id=scene.id, player_id=pid)
            db.add(link)
            
        db.commit()
        
    return RedirectResponse(url=f"/projects/{scene.project_id}", status_code=303)

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
    Clears prompts, scene_desc, base_image_path, AND merged_image_path (Full Reset).
    """
    import os
    import shutil
    from app.config import config
    
    scene = crud.get_scene(db, scene_id)
    if not scene:
        return JSONResponse({"error": "Scene not found"}, status_code=404)

    project_code = scene.project.project_code
    # Logic: Scene files are stored in output/project/scenes/{id}_{name}/...
    # The 'base_image' is usually inside 'base' folder
    # The 'merged_image' is usually inside 'merge' folder
    
    # We can just delete the entire scene folder?
    # Yes, typically scene folder structure is:
    # output/project/scenes/{id}_{name}/base/
    # output/project/scenes/{id}_{name}/merge/
    
    # Wait, where does ComfyRunner save them?
    # ComfyRunner usually saves based on task ID or project structure.
    # Let's check ComfyRunner or manager.py logic.
    # manager.py: current_img_path = os.path.join(base_dir, scene.base_image_path)
    # The path usually contains the folder structure.
    
    # If we assume standard structure, we can try to delete the scene specific folder.
    # But ComfyUI output filename prefix logic:
    # Base: f"{task.id}_scene_base" -> Default Comfy output dir?
    # Wait, ComfyRunner saves to default output unless moved?
    # If using 'Save Image' node with prefix, it saves to ComfyUI/output/prefix_...
    # KT-AI-Studio might need to move them or just reference them.
    
    # If we are deleting, we should try to delete the file referenced in DB.
    
    # 1. Delete Base Image
    if scene.base_image_path:
        try:
            # Construct absolute path
            # base_image_path is relative "output/..."
            abs_path = os.path.abspath(os.path.join(config.PROJECT_ROOT, "..", scene.base_image_path))
            if os.path.exists(abs_path):
                os.remove(abs_path)
                print(f"[Clear Files] Deleted base image: {abs_path}")
        except Exception as e:
            print(f"[Clear Files] Error deleting base image: {e}")

    # 2. Delete Merged Image
    if scene.merged_image_path:
        try:
            abs_path = os.path.abspath(os.path.join(config.PROJECT_ROOT, "..", scene.merged_image_path))
            if os.path.exists(abs_path):
                os.remove(abs_path)
                print(f"[Clear Files] Deleted merged image: {abs_path}")
        except Exception as e:
            print(f"[Clear Files] Error deleting merged image: {e}")

    # 3. Try to delete Scene Directory if it exists (for organized storage)
    # output/project_code/scenes/{id}_{name}
    try:
        scene_dir_name = f"{scene.id}_{scene.name}"
        # We need to guess where it is relative to output.
        # Usually: output/project_code/scenes/...
        scene_dir = os.path.join(config.OUTPUT_DIR, project_code, "scenes", scene_dir_name)
        if os.path.exists(scene_dir):
            shutil.rmtree(scene_dir)
            print(f"[Clear Files] Deleted scene directory: {scene_dir}")
    except Exception as e:
         pass

    # Reset Scene State (Clear Prompts + Merged Fields)
    scene.base_image_path = None
    scene.merged_image_path = None
    scene.merged_prompts_json = None
    scene.video_llm_context = None
    
    scene.prompt_pos = ""
    scene.prompt_neg = ""
    scene.scene_desc = ""
    scene.status = "draft"
    
    db.commit()
        
    return RedirectResponse(url=f"/scenes/{scene_id}", status_code=303)

@router.post("/scenes/{scene_id}/merge")
async def start_scene_merge(
    scene_id: int, 
    seed: int = Form(0),
    db: Session = Depends(session.get_db)
):
    from fastapi.responses import JSONResponse
    scene = crud.get_scene(db, scene_id)
    if not scene:
        return JSONResponse({"error": "Scene not found"}, status_code=404)
        
    if not scene.base_image_path:
        return JSONResponse({"error": "Scene base image not ready"}, status_code=400)
        
    # Check if task already running
    existing_task = db.query(models.Task).filter(
        models.Task.scene_id == scene.id,
        models.Task.task_type == "SCENE_MERGE",
        models.Task.status.in_(["queued", "running"])
    ).first()
    
    if existing_task:
        return JSONResponse({"status": "running", "task_id": existing_task.id})
        
    # Create new task
    payload = {
        "seed": seed
    }
    
    task = models.Task(
        project_id=scene.project_id,
        scene_id=scene.id,
        task_type="SCENE_MERGE",
        status="queued",
        payload_json=json.dumps(payload)
    )
    db.add(task)
    db.commit()
    
    return JSONResponse({"status": "success", "task_id": task.id})

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

@router.get("/scenes/{scene_id}/video_context")
async def get_video_context(scene_id: int, db: Session = Depends(session.get_db)):
    scene = crud.get_scene(db, scene_id)
    if not scene:
        return JSONResponse({"error": "Scene not found"}, status_code=404)
        
    try:
        context = json.loads(scene.video_llm_context) if scene.video_llm_context else None
        return JSONResponse({"status": "success", "context": context})
    except:
        return JSONResponse({"status": "error", "context": None})
