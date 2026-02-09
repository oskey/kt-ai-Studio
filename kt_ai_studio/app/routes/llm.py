from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.db import session, models
from pathlib import Path
import json

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

@router.get("/settings/llm", response_class=HTMLResponse)
async def list_llm_profiles(request: Request, db: Session = Depends(session.get_db)):
    profiles = db.query(models.LLMProfile).order_by(models.LLMProfile.id.asc()).all()
    # Check if we have any profiles, if not, maybe seed didn't run or empty env
    return templates.TemplateResponse("settings_llm.html", {"request": request, "profiles": profiles})

@router.post("/settings/llm")
async def create_llm_profile(
    name: str = Form(...),
    provider: str = Form(...),
    base_url: str = Form(...),
    api_key: str = Form(...),
    model: str = Form(None),
    db: Session = Depends(session.get_db)
):
    # Check duplicate name
    if db.query(models.LLMProfile).filter(models.LLMProfile.name == name).first():
        return HTMLResponse("Name already exists", status_code=400)
        
    # If this is the first profile, make it default
    is_first = db.query(models.LLMProfile).count() == 0
    
    new_profile = models.LLMProfile(
        name=name,
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
        is_default=is_first
    )
    db.add(new_profile)
    db.commit()
    return RedirectResponse(url="/settings/llm", status_code=303)

@router.post("/settings/llm/{profile_id}/update")
async def update_llm_profile(
    profile_id: int,
    name: str = Form(...),
    provider: str = Form(...),
    base_url: str = Form(...),
    api_key: str = Form(...),
    model: str = Form(None),
    db: Session = Depends(session.get_db)
):
    profile = db.query(models.LLMProfile).filter(models.LLMProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
        
    profile.name = name
    profile.provider = provider
    profile.base_url = base_url
    # If api_key is masked or empty, don't update it unless user provided new one
    # But here we assume form sends current value if unchanged? 
    # Usually UI sends masked value like '******'. We should check.
    if api_key and not api_key.startswith("***"):
        profile.api_key = api_key
        
    profile.model = model
    db.commit()
    return RedirectResponse(url="/settings/llm", status_code=303)

@router.post("/settings/llm/{profile_id}/delete")
async def delete_llm_profile(profile_id: int, db: Session = Depends(session.get_db)):
    profile = db.query(models.LLMProfile).filter(models.LLMProfile.id == profile_id).first()
    if profile:
        if profile.is_default:
            # Cannot delete default, or warn? 
            # Let's prevent deleting default for safety
            # Unless it's the only one?
            count = db.query(models.LLMProfile).count()
            if count > 1:
                return HTMLResponse("Cannot delete the default profile. Please set another profile as default first.", status_code=400)
        
        db.delete(profile)
        db.commit()
        
        # If we deleted the only profile (which was default), fine.
        # If we deleted a non-default, fine.
        
    return RedirectResponse(url="/settings/llm", status_code=303)

@router.post("/settings/llm/{profile_id}/default")
async def set_default_llm_profile(profile_id: int, db: Session = Depends(session.get_db)):
    # Set all to false
    db.query(models.LLMProfile).update({models.LLMProfile.is_default: False})
    
    # Set target to true
    profile = db.query(models.LLMProfile).filter(models.LLMProfile.id == profile_id).first()
    if profile:
        profile.is_default = True
        db.commit()
        
    return RedirectResponse(url="/settings/llm", status_code=303)

@router.get("/api/llm/current")
async def get_current_llm(db: Session = Depends(session.get_db)):
    profile = db.query(models.LLMProfile).filter(models.LLMProfile.is_default == True).first()
    if profile:
        return {
            "provider": profile.provider,
            "model": profile.model,
            "name": profile.name
        }
    return {"provider": "None", "model": "None", "name": "No Profile Configured"}

@router.get("/api/llm/profiles/{profile_id}")
async def get_llm_profile(profile_id: int, db: Session = Depends(session.get_db)):
    profile = db.query(models.LLMProfile).filter(models.LLMProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
        
    return {
        "id": profile.id,
        "name": profile.name,
        "provider": profile.provider,
        "base_url": profile.base_url,
        "model": profile.model,
        # Don't send full API key, mask it
        "api_key_masked": profile.api_key[:3] + "****" + profile.api_key[-4:] if len(profile.api_key) > 8 else "****"
    }
