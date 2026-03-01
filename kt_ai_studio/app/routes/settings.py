from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.db import crud, session, models
from pathlib import Path

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(session.get_db)):
    configs = db.query(models.SystemConfig).all()
    config_dict = {c.key: c.value for c in configs}
    
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "config": config_dict
    })

@router.post("/settings/update")
async def update_settings(
    request: Request,
    image_model: str = Form(...),
    video_model: str = Form(...),
    player_gen_width: int = Form(...),
    player_gen_height: int = Form(...),
    player_gen_seed: int = Form(...),
    scene_gen_width: int = Form(...),
    scene_gen_height: int = Form(...),
    scene_gen_seed: int = Form(...),
    video_gen_width: int = Form(...),
    video_gen_height: int = Form(...),
    video_gen_length: int = Form(...),
    video_gen_fps: int = Form(...),
    video_gen_seed: int = Form(...),
    optimize_ancient_costume: str = Form(None),
    db: Session = Depends(session.get_db)
):
    updates = {
        "image_model": str(image_model),
        "video_model": str(video_model),
        "player_gen_width": str(player_gen_width),
        "player_gen_height": str(player_gen_height),
        "player_gen_seed": str(player_gen_seed),
        "scene_gen_width": str(scene_gen_width),
        "scene_gen_height": str(scene_gen_height),
        "scene_gen_seed": str(scene_gen_seed),
        "video_gen_width": str(video_gen_width),
        "video_gen_height": str(video_gen_height),
        "video_gen_length": str(video_gen_length),
        "video_gen_fps": str(video_gen_fps),
        "video_gen_seed": str(video_gen_seed),
        "optimize_ancient_costume": "on" if optimize_ancient_costume else "off"
    }
    
    for key, val in updates.items():
        conf = db.query(models.SystemConfig).filter(models.SystemConfig.key == key).first()
        if conf:
            conf.value = val
        else:
            new_conf = models.SystemConfig(key=key, value=val)
            db.add(new_conf)
            
    db.commit()
    return RedirectResponse(url="/settings", status_code=303)
