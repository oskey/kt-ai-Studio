from sqlalchemy import engine_from_config, pool, inspect
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

    # Check for merged_image_path in kt_ai_scene (Phase 5 Migration)
    with engine.connect() as conn:
        try:
            # Check columns for Scene
            columns = conn.execute(text("PRAGMA table_info(kt_ai_scene)")).fetchall()
            column_names = [col[1] for col in columns]
            
            if "merged_image_path" not in column_names:
                print("Migrating: Adding merged_image_path column to kt_ai_scene...")
                conn.execute(text("ALTER TABLE kt_ai_scene ADD COLUMN merged_image_path TEXT"))
                print("Migration successful: merged_image_path added.")
            else:
                print("Schema check: merged_image_path column exists.")

            if "merged_prompts_json" not in column_names:
                print("Migrating: Adding merged_prompts_json column to kt_ai_scene...")
                conn.execute(text("ALTER TABLE kt_ai_scene ADD COLUMN merged_prompts_json TEXT"))
                print("Migration successful: merged_prompts_json added.")
            else:
                print("Schema check: merged_prompts_json column exists.")

            if "video_llm_context" not in column_names:
                print("Migrating: Adding video_llm_context column to kt_ai_scene...")
                conn.execute(text("ALTER TABLE kt_ai_scene ADD COLUMN video_llm_context TEXT"))
                print("Migration successful: video_llm_context added.")
            else:
                print("Schema check: video_llm_context column exists.")

        except Exception as e:
            print(f"Migration check failed for merged_image_path/prompts: {e}")

    # Check for video_id column in kt_ai_task (Phase 6 Migration: Video)
    with engine.connect() as conn:
        try:
            columns = conn.execute(text("PRAGMA table_info(kt_ai_task)")).fetchall()
            column_names = [col[1] for col in columns]
            
            if "video_id" not in column_names:
                print("Migrating: Adding video_id column to kt_ai_task...")
                conn.execute(text("ALTER TABLE kt_ai_task ADD COLUMN video_id INTEGER REFERENCES kt_ai_video(id)"))
                print("Migration successful: video_id added.")
            else:
                print("Schema check: video_id column exists.")
                
        except Exception as e:
            print(f"Migration check failed for video_id in Task: {e}")

    # Check for SystemConfig table
    try:
        inspector = inspect(engine)
        if "kt_ai_system_config" not in inspector.get_table_names():
            print("Migrating: Creating kt_ai_system_config table...")
            models.SystemConfig.__table__.create(bind=engine)
            
            # Seed defaults
            with engine.connect() as conn:
                defaults = [
                    ("player_gen_width", "1024", "人物生成默认宽度"),
                    ("player_gen_height", "768", "人物生成默认高度"),
                    ("player_gen_seed", "264590", "人物生成默认随机种子"),
                    ("scene_gen_width", "1024", "场景生成默认宽度"),
                    ("scene_gen_height", "768", "场景生成默认高度"),
                    ("scene_gen_seed", "264590", "场景生成默认随机种子")
                ]
                for key, val, desc in defaults:
                    # Use INSERT OR REPLACE to ensure new defaults are applied if they exist but were set by previous migration
                    # OR we can check if it exists and update if it matches old default?
                    # User said: "if I haven't entered this page... write default value directly".
                    # Let's use INSERT OR REPLACE to force these values on migration run, 
                    # assuming this is a dev environment or first run. 
                    # But if user changed them, we shouldn't overwrite?
                    # "如果初次我没有进入过这个页面的话" -> implies initialization.
                    # Since we are changing the "factory defaults", we should probably update them 
                    # ONLY IF they are currently set to the OLD factory defaults?
                    # Or just use INSERT OR IGNORE, and I will manually update the DB for the user?
                    # Let's use INSERT OR REPLACE for now as per user instruction to "write directly".
                    # Actually, better logic: INSERT OR IGNORE. 
                    # But I will add a specific UPDATE for the player width/height correction this time.
                    
                    conn.execute(text("INSERT OR IGNORE INTO kt_ai_system_config (key, value, description) VALUES (:key, :val, :desc)"), {"key": key, "val": val, "desc": desc})
                
                # Explicit fix for Player Width/Height if they are the old swapped values
                conn.execute(text("UPDATE kt_ai_system_config SET value='1024' WHERE key='player_gen_width' AND value='768'"))
                conn.execute(text("UPDATE kt_ai_system_config SET value='768' WHERE key='player_gen_height' AND value='1024'"))
                
                conn.commit()
            print("Migration successful: SystemConfig table created and seeded.")
    except Exception as e:
        print(f"Migration check failed for SystemConfig: {e}")

    # Create tables if they don't exist (standard behavior)
    Base.metadata.create_all(bind=engine)
