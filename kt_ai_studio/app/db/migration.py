from sqlalchemy import engine_from_config, pool
from sqlalchemy import text
from app.db.session import engine, Base
from app.db import models

def check_and_migrate_db():
    """
    Simple migration logic to ensure new columns exist.
    Run this on app startup.
    """
    print("Checking database schema...")
    
    # Check for player_desc column in kt_ai_player
    with engine.connect() as conn:
        try:
            # This query works for SQLite. For other DBs, syntax might differ.
            # Assuming SQLite for this project based on context.
            columns = conn.execute(text("PRAGMA table_info(kt_ai_player)")).fetchall()
            column_names = [col[1] for col in columns]
            
            if "player_desc" not in column_names:
                print("Migrating: Adding player_desc column to kt_ai_player...")
                conn.execute(text("ALTER TABLE kt_ai_player ADD COLUMN player_desc TEXT"))
                print("Migration successful: player_desc added.")
            else:
                print("Schema check: player_desc column exists.")
                
        except Exception as e:
            print(f"Migration check failed: {e}")
            # Don't raise, let the app try to run, maybe it's a new DB init

    # Check for scene_id column in kt_ai_task (Phase 2 Migration)
    with engine.connect() as conn:
        try:
            columns = conn.execute(text("PRAGMA table_info(kt_ai_task)")).fetchall()
            column_names = [col[1] for col in columns]
            
            if "scene_id" not in column_names:
                print("Migrating: Adding scene_id column to kt_ai_task...")
                conn.execute(text("ALTER TABLE kt_ai_task ADD COLUMN scene_id INTEGER REFERENCES kt_ai_scene(id)"))
                print("Migration successful: scene_id added.")
            else:
                print("Schema check: scene_id column exists.")
                
        except Exception as e:
            print(f"Migration check failed for Task table: {e}")

    # Check for style_id column in kt_ai_scene (Phase 3 Migration: Drop Column)
    with engine.connect() as conn:
        try:
            columns = conn.execute(text("PRAGMA table_info(kt_ai_scene)")).fetchall()
            column_names = [col[1] for col in columns]
            
            if "style_id" in column_names:
                print("Migrating: Dropping style_id column from kt_ai_scene...")
                try:
                    conn.execute(text("ALTER TABLE kt_ai_scene DROP COLUMN style_id"))
                    print("Migration successful: style_id dropped.")
                except Exception as e:
                    print(f"Migration failed (SQLite version might be too old for DROP COLUMN): {e}")
                    # Optional: Recreate table logic if strictly needed, but for now just warn
            else:
                print("Schema check: style_id column already removed.")
                
        except Exception as e:
            print(f"Migration check failed for Scene table: {e}")

    # Check for episode/shot columns in kt_ai_scene (Phase 4 Migration)
    with engine.connect() as conn:
        try:
            columns = conn.execute(text("PRAGMA table_info(kt_ai_scene)")).fetchall()
            column_names = [col[1] for col in columns]
            
            if "episode" not in column_names:
                print("Migrating: Adding episode column to kt_ai_scene...")
                conn.execute(text("ALTER TABLE kt_ai_scene ADD COLUMN episode INTEGER NOT NULL DEFAULT 1"))
                
            if "shot" not in column_names:
                print("Migrating: Adding shot column to kt_ai_scene...")
                conn.execute(text("ALTER TABLE kt_ai_scene ADD COLUMN shot INTEGER NOT NULL DEFAULT 1"))
                
        except Exception as e:
            print(f"Migration check failed for Scene columns: {e}")

    # Create tables if they don't exist (standard behavior)
    Base.metadata.create_all(bind=engine)
