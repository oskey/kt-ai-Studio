import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    PROJECT_NAME = "KT AI Studio"
    DATABASE_URL = "sqlite:///./kt_ai_studio.db"
    
    COMFYUI_BASE_URL = os.getenv("COMFYUI_BASE_URL", "http://127.0.0.1:8188")
    COMFYUI_WS_URL = os.getenv("COMFYUI_WS_URL", "ws://127.0.0.1:8188/ws")
    COMFYUI_OUTPUT_DIR = os.getenv("COMFYUI_OUTPUT_DIR")
    
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com")
    LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
    
    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "Asia/Shanghai")
    
    # Logging Config
    SQL_LOG = os.getenv("SQL_LOG", "0") == "1"
    API_LOG = os.getenv("API_LOG", "1") == "1"
    LLM_LOG = os.getenv("LLM_LOG", "1") == "1"
    
    OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "output")

config = Config()

# Ensure output directory exists
os.makedirs(config.OUTPUT_DIR, exist_ok=True)
