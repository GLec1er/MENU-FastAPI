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

SYNC_DATABASE_URL = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}" f"@{DB_HOST}:5432/{DB_NAME}"
)

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
TEST_ASYNC_DATABASE_URL = os.getenv("TEST_ASYNC_DATABASE_URL")

BROKER_USER = os.getenv("RABBITMQ_USER")
BROKER_PASSWORD = os.getenv("RABBITMQ_PASSWORD")
BROKER_HOST = os.getenv("RABBITMQ_HOST")

BROKER_URL = f"amqp://{BROKER_USER}:{BROKER_PASSWORD}@{BROKER_HOST}//"


def _float_list(name: str, default: str) -> list[float]:
    return [float(x) for x in os.getenv(name, default).split(",") if x.strip()]


class Settings(BaseSettings):
    app_title: str = "Меню ресторана"
    database_url: str = DATABASE_URL
    sync_database_url: str = SYNC_DATABASE_URL

    # Надёжные фоновые задания. Значения по умолчанию соответствуют спецификации,
    # тестовый профиль сокращает интервалы через переменные окружения.
    job_max_attempts: int = int(os.getenv("JOB_MAX_ATTEMPTS", "3"))
    retry_delays: list[float] = _float_list("JOB_RETRY_DELAYS", "5,30")
    job_time_limit: int = int(os.getenv("JOB_TIME_LIMIT", "300"))
    job_lease_seconds: float = float(os.getenv("JOB_LEASE_SECONDS", "360"))
    dispatcher_poll_interval: float = float(os.getenv("DISPATCHER_POLL_INTERVAL", "1"))
    reconcile_interval: float = float(os.getenv("RECONCILE_INTERVAL", "10"))
    redelivery_timeout: float = float(os.getenv("REDELIVERY_TIMEOUT", "120"))
    publish_timeout: float = float(os.getenv("PUBLISH_TIMEOUT", "5"))
    publish_retry_delay: float = float(os.getenv("PUBLISH_RETRY_DELAY", "5"))
    # Только для тестового профиля: остановка worker до/после коммита результата.
    job_test_barrier: str = os.getenv("JOB_TEST_BARRIER", "")
    job_test_fail: str = os.getenv("JOB_TEST_FAIL", "")
    job_test_barrier_dir: str = os.getenv("JOB_TEST_BARRIER_DIR", "/barriers")


settings = Settings()
