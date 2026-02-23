from sqlalchemy.orm import Session
from app.db import models
from typing import Optional, List
import json

# Project CRUD
def create_project(db: Session, name: str, project_code: str, style_id: int, mark: Optional[str] = None):
    db_project = models.Project(
        name=name, 
        project_code=project_code, 
        style_id=style_id,
        mark=mark
    )
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    return db_project

def get_projects(db: Session, skip: int = 0, limit: int = 100):
    # Eager load style
    from sqlalchemy.orm import joinedload
    return db.query(models.Project).options(joinedload(models.Project.style)).offset(skip).limit(limit).all()

def get_project(db: Session, project_id: int):
    from sqlalchemy.orm import joinedload
    return db.query(models.Project).options(joinedload(models.Project.style)).filter(models.Project.id == project_id).first()

def update_project(db: Session, project_id: int, name: str, style_id: int, mark: Optional[str] = None):
    db_project = get_project(db, project_id)
    if db_project:
        db_project.name = name
        db_project.style_id = style_id
        db_project.mark = mark
        db.commit()
        db.refresh(db_project)
    return db_project

def get_style_presets(db: Session):
    return db.query(models.StylePreset).all()

def delete_project(db: Session, project_id: int):
    db_project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if db_project:
        db.delete(db_project)
        db.commit()
        return True
    return False

# Player CRUD
def create_player(db: Session, project_id: int, name: str, sex: str, mark: Optional[str] = None):
    db_player = models.Player(
        project_id=project_id,
        player_name=name,
        player_sex=sex,
        player_mark=mark,
        status="draft"
    )
    db.add(db_player)
    db.commit()
    db.refresh(db_player)
    return db_player

def get_players_by_project(db: Session, project_id: int):
    return db.query(models.Player).filter(models.Player.project_id == project_id).all()

def get_player(db: Session, player_id: int):
    return db.query(models.Player).filter(models.Player.id == player_id).first()

def update_player(db: Session, player_id: int, name: str, sex: str, mark: Optional[str] = None):
    db_player = get_player(db, player_id)
    if db_player:
        db_player.player_name = name
        db_player.player_sex = sex
        db_player.player_mark = mark
        db.commit()
        db.refresh(db_player)
    return db_player

def delete_player(db: Session, player_id: int):
    db_player = get_player(db, player_id)
    if db_player:
        db.delete(db_player)
        db.commit()
        return True
    return False

def update_player_prompts(db: Session, player_id: int, prompt_pos: str, prompt_neg: str, player_desc: Optional[str] = None):
    db_player = get_player(db, player_id)
    if db_player:
        db_player.prompt_pos = prompt_pos
        db_player.prompt_neg = prompt_neg
        if player_desc is not None:
            db_player.player_desc = player_desc
        db.commit()
        db.refresh(db_player)
    return db_player

def update_player_status(db: Session, player_id: int, status: str):
    db_player = get_player(db, player_id)
    if db_player:
        db_player.status = status
        db.commit()
        db.refresh(db_player)
    return db_player

def clear_player_config(db: Session, player_id: int):
    db_player = get_player(db, player_id)
    if db_player:
        # Clear fields
        db_player.player_desc = None
        db_player.prompt_pos = None
        db_player.prompt_neg = None
        
        # We need these paths to delete files physically *before* clearing them in DB, 
        # but CRUD shouldn't do OS operations. 
        # So we just return the paths to the caller, and let caller handle deletion?
        # Or we clear them here.
        # Let's return the old values so caller can delete files.
        old_base = db_player.base_image_path
        old_views = db_player.views_json
        
        db_player.base_image_path = None
        db_player.views_json = None
        db_player.status = "draft"
        
        db.commit()
        db.refresh(db_player)
        return old_base, old_views
    return None, None

# Scene CRUD
def create_scene(db: Session, project_id: int, name: str, scene_type: str, base_desc: str, episode: int, shot: int, player_ids: List[int] = []):
    db_scene = models.Scene(
        project_id=project_id,
        name=name,
        scene_type=scene_type,
        base_desc=base_desc,
        episode=episode,
        shot=shot,
        status="draft"
    )
    
    if player_ids:
        players = db.query(models.Player).filter(models.Player.id.in_(player_ids)).all()
        db_scene.related_players = players
        
    db.add(db_scene)
    db.commit()
    db.refresh(db_scene)
    return db_scene

def get_scene(db: Session, scene_id: int):
    # Eager load related players
    from sqlalchemy.orm import joinedload
    return db.query(models.Scene).options(joinedload(models.Scene.related_players)).filter(models.Scene.id == scene_id).first()

def get_scenes_by_project(db: Session, project_id: int):
    # Eager load related players
    from sqlalchemy.orm import joinedload
    return db.query(models.Scene).options(joinedload(models.Scene.related_players)).filter(models.Scene.project_id == project_id).order_by(models.Scene.episode.asc(), models.Scene.shot.asc()).all()

def update_scene_prompts(db: Session, scene_id: int, prompt_pos: str, prompt_neg: str, scene_desc: str):
    db_scene = get_scene(db, scene_id)
    if db_scene:
        db_scene.prompt_pos = prompt_pos
        db_scene.prompt_neg = prompt_neg
        db_scene.scene_desc = scene_desc
        db.commit()
        db.refresh(db_scene)
    return db_scene

def update_scene_status(db: Session, scene_id: int, status: str):
    db_scene = get_scene(db, scene_id)
    if db_scene:
        db_scene.status = status
        db.commit()
        db.refresh(db_scene)
    return db_scene

def delete_scene(db: Session, scene_id: int):
    db_scene = get_scene(db, scene_id)
    if db_scene:
        db.delete(db_scene)
        db.commit()
        return True
    return False

# Video CRUD
def create_video(db: Session, project_id: int, scene_id: int):
    # Check if exists
    db_video = db.query(models.Video).filter(models.Video.scene_id == scene_id).first()
    if db_video:
        return db_video
        
    db_video = models.Video(
        project_id=project_id,
        scene_id=scene_id,
        status="draft"
    )
    db.add(db_video)
    db.commit()
    db.refresh(db_video)
    return db_video

def get_video(db: Session, video_id: int):
    return db.query(models.Video).filter(models.Video.id == video_id).first()

def get_video_by_scene(db: Session, scene_id: int):
    return db.query(models.Video).filter(models.Video.scene_id == scene_id).first()

def get_videos_by_project(db: Session, project_id: int):
    return db.query(models.Video).filter(models.Video.project_id == project_id).all()

def update_video_prompts(db: Session, video_id: int, prompt_pos: str, prompt_neg: str):
    db_video = get_video(db, video_id)
    if db_video:
        db_video.prompt_pos = prompt_pos
        db_video.prompt_neg = prompt_neg
        db.commit()
        db.refresh(db_video)
    return db_video

def update_video_status(db: Session, video_id: int, status: str, video_path: Optional[str] = None):
    db_video = get_video(db, video_id)
    if db_video:
        db_video.status = status
        if video_path:
            db_video.video_path = video_path
        db.commit()
        db.refresh(db_video)
    return db_video

def update_video_params(db: Session, video_id: int, seed: int, width: int, height: int, length: int, fps: int):
    db_video = get_video(db, video_id)
    if db_video:
        db_video.seed = seed
        db_video.width = width
        db_video.height = height
        db_video.length = length
        db_video.fps = fps
        db.commit()
        db.refresh(db_video)
    return db_video

# Task CRUD
def create_task(db: Session, project_id: int, task_type: str, player_id: Optional[int] = None, scene_id: Optional[int] = None, video_id: Optional[int] = None, payload: Optional[dict] = None):
    db_task = models.Task(
        project_id=project_id,
        player_id=player_id,
        scene_id=scene_id,
        video_id=video_id,
        task_type=task_type,
        status="queued",
        payload_json=json.dumps(payload) if payload else None
    )
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return db_task

def get_tasks_by_scene(db: Session, scene_id: int):
    return db.query(models.Task).filter(models.Task.scene_id == scene_id).order_by(models.Task.created_at.desc()).all()

def get_tasks_by_player(db: Session, player_id: int):
    return db.query(models.Task).filter(models.Task.player_id == player_id).order_by(models.Task.created_at.desc()).all()

def get_tasks_by_project(db: Session, project_id: int):
    return db.query(models.Task).filter(models.Task.project_id == project_id).order_by(models.Task.created_at.desc()).all()

def get_queued_tasks(db: Session):
    return db.query(models.Task).filter(models.Task.status == "queued").all()

def get_task(db: Session, task_id: int):
    return db.query(models.Task).filter(models.Task.id == task_id).first()
