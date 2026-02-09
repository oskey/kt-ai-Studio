from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import config

engine = create_engine(
    config.DATABASE_URL, 
    echo=config.SQL_LOG, # Control SQL logging via env
    connect_args={
        "check_same_thread": False,
        "timeout": 30 # Increase SQLite lock wait timeout to 30s
    }
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
