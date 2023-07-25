import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseSettings

load_dotenv()

FORMAT = "%d-%m-%Y_%H-%M"

BASE_DIR = Path(__file__).resolve().parent.parent
BASE_URL = "http://localhost:8000"

DB_HOST = os.getenv("POSTGRES_HOST")
DB_NAME = os.getenv("POSTGRES_DB")
DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")

DATABASE_URL = (
    f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}" f"@{DB_HOST}:5432/{DB_NAME}"
)


class Settings(BaseSettings):
    app_title: str = "Меню ресторана"
    database_url: str = DATABASE_URL


settings = Settings()