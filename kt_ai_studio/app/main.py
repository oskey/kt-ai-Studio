from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import os
from pathlib import Path

from app.config import config
from app.db.session import engine
from app.db import models
from app.routes import projects, players, tasks
# Import the global task_manager instance instead of class
from app.services.tasks.manager import task_manager
import asyncio
from app.db.migration import check_and_migrate_db
import logging
import time

# Configure Logging to UTC+8
class UTCPlus8Formatter(logging.Formatter):
    def converter(self, timestamp):
        # Convert timestamp to UTC, then add 8 hours
        return time.gmtime(timestamp + 28800)

    def formatTime(self, record, datefmt=None):
        ct = self.converter(record.created)
        if datefmt:
            s = time.strftime(datefmt, ct)
        else:
            t = time.strftime("%Y-%m-%d %H:%M:%S", ct)
            s = "%s,%03d" % (t, record.msecs)
        return s

# Apply formatter to root logger
handler = logging.StreamHandler()
handler.setFormatter(UTCPlus8Formatter(fmt='[%(asctime)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
logging.getLogger().handlers = [] # Clear existing
logging.getLogger().addHandler(handler)

# Control API logging via env
if config.API_LOG:
    logging.getLogger().setLevel(logging.INFO)
else:
    logging.getLogger().setLevel(logging.WARNING) # Suppress INFO logs

if config.API_LOG:
    logging.info("KT AI Studio Logging initialized (UTC+8)")

# Run simple migration check
check_and_migrate_db()

# Create tables
models.Base.metadata.create_all(bind=engine)

# Seed Style Presets (Architecture Requirement)
try:
    from app.db.seeds import seed_style_presets, seed_llm_profiles
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        seed_style_presets(db)
        seed_llm_profiles(db)
        if config.API_LOG:
            logging.info("Style presets and LLM profiles seeded successfully.")
    except Exception as e:
        logging.error(f"Failed to seed style presets: {e}")
    finally:
        db.close()
except ImportError:
    logging.warning("Seeds module not found, skipping seeding.")

app = FastAPI(title="KT AI Studio")

# Task Manager is now imported as a singleton instance
# task_manager = TaskManager()

@app.on_event("startup")
async def startup_event():
    # Start task worker
    task_manager.start()

@app.on_event("shutdown")
async def shutdown_event():
    task_manager.stop()

# Mount static files
static_path = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_path), name="static")
app.mount("/output", StaticFiles(directory=config.OUTPUT_DIR), name="output")

# Templates
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# Include Routers
app.include_router(projects.router)
app.include_router(players.router)
app.include_router(tasks.router)
from app.routes import styles, llm, scenes, settings, system
app.include_router(scenes.router)
app.include_router(styles.router)
app.include_router(llm.router)
app.include_router(settings.router)
app.include_router(system.router)

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("base.html", {"request": request, "title": "KT AI Studio"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
