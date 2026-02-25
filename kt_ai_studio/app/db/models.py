from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.session import Base

class LLMProfile(Base):
    __tablename__ = "kt_ai_llm_profile"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True) # e.g. "DeepSeek-Default"
    provider = Column(String, nullable=False) # deepseek / openai
    base_url = Column(String, nullable=False)
    api_key = Column(String, nullable=False)
    model = Column(String, nullable=True) # e.g. deepseek-chat, gpt-4o
    is_default = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class StylePreset(Base):
    __tablename__ = "kt_ai_style_preset"

    style_id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    engine_hint = Column(Text, nullable=False)
    style_pos = Column(Text, nullable=False)
    style_neg = Column(Text, nullable=False)
    llm_style_guard = Column(Text, nullable=False)

class Project(Base):
    __tablename__ = "kt_ai_project"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    project_code = Column(String, unique=True, nullable=False, index=True)
    mark = Column(Text, nullable=True)
    
    # New Style Lock
    style_id = Column(Integer, ForeignKey("kt_ai_style_preset.style_id"), nullable=True) # Nullable for migration/existing, but logic will enforce it
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    style = relationship("StylePreset")
    players = relationship("Player", back_populates="project", cascade="all, delete-orphan")
    scenes = relationship("Scene", back_populates="project", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="project", cascade="all, delete-orphan")

# Association Table for Scene-Player Many-to-Many
class ScenePlayerLink(Base):
    __tablename__ = "kt_ai_scene_player_link"
    scene_id = Column(Integer, ForeignKey("kt_ai_scene.id"), primary_key=True)
    player_id = Column(Integer, ForeignKey("kt_ai_player.id"), primary_key=True)

class Scene(Base):
    __tablename__ = "kt_ai_scene"

    id = Column(Integer, primary_key=True, index=True) # scene_id
    project_id = Column(Integer, ForeignKey("kt_ai_project.id"), nullable=False)
    name = Column(String, nullable=False)
    scene_type = Column(String, default="indoor") # indoor/outdoor/special
    base_desc = Column(Text, nullable=False) # user intent
    
    # Episode/Shot Info
    episode = Column(Integer, default=1, nullable=False)
    shot = Column(Integer, default=1, nullable=False)
    
    prompt_pos = Column(Text, nullable=False, default="")
    prompt_neg = Column(Text, nullable=False, default="")
    scene_desc = Column(Text, nullable=False, default="") # scene fingerprint
    
    status = Column(String, default="draft", nullable=False) # draft/generated_prompt/generated/failed
    
    base_image_path = Column(Text, nullable=True) 
    merged_image_path = Column(Text, nullable=True) # Final merged result with characters
    merged_prompts_json = Column(Text, nullable=True) # Array of prompts used for merging each character
    video_llm_context = Column(Text, nullable=True) # Context for video generation (scene + characters + action)
    dialogues_json = Column(Text, nullable=True) # JSON Array of dialogues: [{"role": "Name", "content": "Hello"}]
    
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="scenes")
    tasks = relationship("Task", back_populates="scene", cascade="all, delete-orphan")
    
    # Many-to-Many relationship with Players
    related_players = relationship("Player", secondary="kt_ai_scene_player_link", back_populates="related_scenes")
    
    # Video
    videos = relationship("Video", back_populates="scene", cascade="all, delete-orphan")

class Video(Base):
    __tablename__ = "kt_ai_video"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("kt_ai_project.id"), nullable=False)
    scene_id = Column(Integer, ForeignKey("kt_ai_scene.id"), nullable=False)
    
    status = Column(String, default="draft") # draft/queued/generating/completed/failed
    
    prompt_pos = Column(Text, nullable=True) # LLM generated positive prompt for video
    prompt_neg = Column(Text, nullable=True) # LLM generated negative prompt for video
    
    video_path = Column(Text, nullable=True) # Path to generated video file
    
    # Generation Parameters
    seed = Column(Integer, default=0)
    width = Column(Integer, default=640)
    height = Column(Integer, default=640)
    length = Column(Integer, default=81)
    fps = Column(Integer, default=16)
    
    # Store LLM returned parameters separately if needed, but usually we just overwrite length/fps
    # Or maybe length/fps here are the user settings, and we overwrite them with LLM suggestions?
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    scene = relationship("Scene", back_populates="videos")
    project = relationship("Project")

class SystemConfig(Base):
    __tablename__ = "kt_ai_system_config"
    
    key = Column(String, primary_key=True, index=True)
    value = Column(String, nullable=True)
    description = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SystemLog(Base):
    __tablename__ = "kt_ai_system_log"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    module = Column(String, nullable=False) # e.g. [一键生成所有基图]
    progress_info = Column(String, nullable=True) # e.g. [1/10个]
    content = Column(Text, nullable=False)
    level = Column(String, default="INFO")

class Player(Base):
    __tablename__ = "kt_ai_player"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("kt_ai_project.id"), nullable=False)
    player_name = Column(String, nullable=False)
    player_sex = Column(String, nullable=False)  # male/female/other
    player_mark = Column(Text, nullable=True)
    
    # New field for character description (Phase 1 extension)
    player_desc = Column(Text, nullable=True)
    
    prompt_pos = Column(Text, nullable=True)
    prompt_neg = Column(Text, nullable=True)
    base_image_path = Column(Text, nullable=True)
    views_json = Column(Text, nullable=True)
    status = Column(String, default="draft")  # draft/ready/generating/done/failed
    
    # Future placeholders
    ref_images_json = Column(Text, nullable=True)
    embedding_json = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="players")
    tasks = relationship("Task", back_populates="player")
    
    # Many-to-Many relationship with Scenes
    related_scenes = relationship("Scene", secondary="kt_ai_scene_player_link", back_populates="related_players")

class Task(Base):
    __tablename__ = "kt_ai_task"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("kt_ai_project.id"), nullable=False)
    player_id = Column(Integer, ForeignKey("kt_ai_player.id"), nullable=True)
    scene_id = Column(Integer, ForeignKey("kt_ai_scene.id"), nullable=True)
    video_id = Column(Integer, ForeignKey("kt_ai_video.id"), nullable=True)
    task_type = Column(String, nullable=False) # GEN_PROMPT | GEN_BASE | GEN_8VIEWS | GEN_SCENE_PROMPT | GEN_SCENE_BASE | GEN_VIDEO_PROMPT | GEN_VIDEO
    status = Column(String, default="queued") # queued/running/done/failed
    progress = Column(Integer, default=0)
    payload_json = Column(Text, nullable=True)
    result_json = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration = Column(Integer, nullable=True)
    eta = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="tasks")
    player = relationship("Player", back_populates="tasks")
    scene = relationship("Scene", back_populates="tasks")
    video = relationship("Video")
