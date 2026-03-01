from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.db import session, models
from pathlib import Path
from app.utils import to_web_path
from app.config import config
import pytz

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")
templates.env.globals["to_web_path"] = to_web_path

def format_timestamp(dt):
    if not dt: return ""
    local_tz = pytz.timezone(config.APP_TIMEZONE)
    # Check if naive (assume UTC if naive, as DB stores UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=pytz.utc)
    return dt.astimezone(local_tz).strftime('%Y-%m-%d %H:%M:%S')

templates.env.globals["format_timestamp"] = format_timestamp

@router.get("/system/logs", response_class=HTMLResponse)
async def view_system_logs(request: Request, db: Session = Depends(session.get_db)):
    # Initial load of logs (last 100)
    logs = db.query(models.SystemLog).order_by(models.SystemLog.timestamp.desc()).limit(100).all()
    return templates.TemplateResponse("system_logs.html", {
        "request": request,
        "logs": logs
    })

@router.get("/api/system/logs")
async def get_system_logs_api(
    last_id: int = 0, 
    limit: int = 100, 
    db: Session = Depends(session.get_db)
):
    """
    API to fetch logs newer than last_id.
    """
    query = db.query(models.SystemLog)
    if last_id > 0:
        query = query.filter(models.SystemLog.id > last_id)
    
    logs = query.order_by(models.SystemLog.id.asc()).limit(limit).all()
    
    result = []
    for log in logs:
        result.append({
            "id": log.id,
            "timestamp": format_timestamp(log.timestamp),
            "module": log.module,
            "progress_info": log.progress_info,
            "content": log.content,
            "level": log.level
        })
        
    return JSONResponse(result)

@router.get("/api/system/version")
async def get_system_version():
    """
    Get current system version from version.txt
    """
    try:
        # File path resolution:
        # __file__ = .../kt_ai_studio/app/routes/system.py
        # parent.parent.parent = .../kt_ai_studio/
        # version.txt should be at .../kt_ai_studio/version.txt OR .../version.txt (project root)
        
        # Check both potential locations
        current_dir = Path(__file__).parent
        
        # Option 1: Project Root (where requirements.txt is) -> x:\Comfyui\KT-AI-Studio\version.txt
        root_version_file = current_dir.parent.parent.parent / "version.txt"
        
        # Option 2: Inner Package Root -> x:\Comfyui\KT-AI-Studio\kt_ai_studio\version.txt
        inner_version_file = current_dir.parent.parent / "version.txt"
        
        version_file = None
        if root_version_file.exists():
            version_file = root_version_file
        elif inner_version_file.exists():
            version_file = inner_version_file
            
        if version_file:
            version = version_file.read_text(encoding="utf-8").strip()
            return JSONResponse({"version": version})
        else:
            return JSONResponse({"version": "1.0.0"})
    except Exception as e:
        return JSONResponse({"version": "Unknown", "error": str(e)})

# Global variable to track update check status (True means user has been notified or checked)
# Reset on server restart
UPDATE_CHECK_DONE = False
CACHED_REMOTE_VERSION = None

@router.get("/api/system/check_update")
async def check_system_update(request: Request, force: bool = False):
    """
    Check for updates from GitHub (Backend Proxy to avoid CORS)
    Added random timestamp param support to bypass cache
    
    Args:
        force: If True, ignore UPDATE_CHECK_DONE flag and check anyway.
    """
    global UPDATE_CHECK_DONE, CACHED_REMOTE_VERSION
    
    # If already checked and not forced, return cached status (empty or previously fetched?)
    # Requirement: "Stop requesting GitHub". So we just return cached version if available.
    if UPDATE_CHECK_DONE and not force:
        if CACHED_REMOTE_VERSION:
             return JSONResponse({"remote_version": CACHED_REMOTE_VERSION, "cached": True})
        else:
             return JSONResponse({"status": "skipped", "message": "Update check already performed in this session"})

    import httpx
    # Add timestamp to github url as well just in case
    import time
    # Use Cache-Busting via random query param
    github_url = f"https://raw.githubusercontent.com/oskey/kt-ai-Studio/main/version.txt?_t={int(time.time())}"
    try:
        async with httpx.AsyncClient() as client:
            # Force headers to avoid cache
            headers = {"Cache-Control": "no-cache", "Pragma": "no-cache"}
            resp = await client.get(github_url, headers=headers, timeout=5.0)
            
            # Mark as done regardless of result, to prevent spamming
            UPDATE_CHECK_DONE = True
            
            if resp.status_code == 200:
                remote_version = resp.text.strip()
                CACHED_REMOTE_VERSION = remote_version # Cache it!
                return JSONResponse({"remote_version": remote_version})
            else:
                return JSONResponse({"error": f"GitHub returned {resp.status_code}"}, status_code=500)
    except Exception as e:
        # If failed, we might want to retry later? No, user said "stop requesting".
        # But if failed, maybe we shouldn't mark done? 
        # User requirement: "Once run, check once, then stop". So we mark done.
        UPDATE_CHECK_DONE = True
        return JSONResponse({"error": str(e)}, status_code=500)

@router.post("/api/system/ack_update")
async def ack_update():
    """
    Frontend calls this when user clicks "Yes" or "No" or closes the modal.
    Sets the global flag to prevent further checks.
    """
    global UPDATE_CHECK_DONE
    UPDATE_CHECK_DONE = True
    return JSONResponse({"status": "ok"})
