from uuid import UUID

from app.jobs.executor import run_job
from app.report.celery import celery


@celery.task(name="execute_job")
def execute_job(job_id: str, attempt: int, event_id: str = "") -> str:
    return run_job(UUID(job_id), attempt, event_id)
