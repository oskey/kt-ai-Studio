from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.db import session, models
from pathlib import Path
import json

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

@router.get("/styles", response_class=HTMLResponse)
async def list_styles(request: Request, db: Session = Depends(session.get_db)):
    styles = db.query(models.StylePreset).all()
    return templates.TemplateResponse("styles.html", {"request": request, "styles": styles})

@router.post("/styles")
async def create_style(
    name: str = Form(...),
    engine_hint: str = Form(...),
    style_pos: str = Form(...),
    style_neg: str = Form(...),
    llm_style_guard: str = Form(...),
    db: Session = Depends(session.get_db)
):
    # Check duplicate name
    existing = db.query(models.StylePreset).filter(models.StylePreset.name == name).first()
    if existing:
        return HTMLResponse(content="Style name already exists", status_code=400)
        
    new_style = models.StylePreset(
        name=name,
        engine_hint=engine_hint,
        style_pos=style_pos,
        style_neg=style_neg,
        llm_style_guard=llm_style_guard
    )
    db.add(new_style)
    db.commit()
    db.refresh(new_style)
    
    return RedirectResponse(url="/styles", status_code=303)

@router.get("/styles/{style_id}", response_class=JSONResponse)
async def get_style_detail(style_id: int, db: Session = Depends(session.get_db)):
    style = db.query(models.StylePreset).filter(models.StylePreset.style_id == style_id).first()
    if not style:
        raise HTTPException(status_code=404, detail="Style not found")
        
    return {
        "style_id": style.style_id,
        "name": style.name,
        "engine_hint": style.engine_hint,
        "style_pos": style.style_pos,
        "style_neg": style.style_neg,
        "llm_style_guard": style.llm_style_guard
    }

@router.post("/styles/{style_id}/update")
async def update_style(
    style_id: int,
    name: str = Form(...),
    engine_hint: str = Form(...),
    style_pos: str = Form(...),
    style_neg: str = Form(...),
    llm_style_guard: str = Form(...),
    db: Session = Depends(session.get_db)
):
    style = db.query(models.StylePreset).filter(models.StylePreset.style_id == style_id).first()
    if not style:
        raise HTTPException(status_code=404, detail="Style not found")
        
    style.name = name
    style.engine_hint = engine_hint
    style.style_pos = style_pos
    style.style_neg = style_neg
    style.llm_style_guard = llm_style_guard
    
    db.commit()
    return RedirectResponse(url="/styles", status_code=303)

@router.post("/styles/{style_id}/delete")
async def delete_style(style_id: int, db: Session = Depends(session.get_db)):
    style = db.query(models.StylePreset).filter(models.StylePreset.style_id == style_id).first()
    if style:
        # Check if used by any project?
        # If Cascade delete is set on Project->Style relationship, it might be dangerous.
        # Project definition: style_id = Column(..., ForeignKey(...))
        # It's better to prevent delete if used.
        project_count = db.query(models.Project).filter(models.Project.style_id == style_id).count()
        if project_count > 0:
            # Simple error page or flash message
            return HTMLResponse(content=f"Cannot delete style '{style.name}' because it is used by {project_count} projects.", status_code=400)
            
        db.delete(style)
        db.commit()
        
    return RedirectResponse(url="/styles", status_code=303)
