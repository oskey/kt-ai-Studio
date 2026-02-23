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
