from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

engine = create_engine(settings.sync_database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False, future=True)
