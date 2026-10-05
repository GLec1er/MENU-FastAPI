from celery import Celery
from kombu import Queue

from app.core.config import BROKER_URL, settings
from app.jobs.states import QUEUE_EXECUTE

celery = Celery("tasks", broker=BROKER_URL, include=["app.report.tasks"])
celery.conf.update(
    task_default_queue=QUEUE_EXECUTE,
    task_queues=(Queue(QUEUE_EXECUTE, durable=True),),
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Состояние заданий хранится в PostgreSQL, result backend не используется.
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=settings.job_time_limit,
    worker_prefetch_multiplier=1,
)
