import hashlib
import logging
import time
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import text

from app.core.config import settings
from app.jobs import states
from app.jobs.report_builder import InvalidSnapshot, build_menu_report
from app.jobs.sync_db import SessionLocal
from app.jobs.transitions import fail_or_retry

log = logging.getLogger(__name__)

SKIPPED = "skipped"
LOST = "lost"


def barrier(point: str, job_id: UUID) -> None:
    """Тестовая точка остановки: создаёт файл-сигнал и ждёт, пока процесс убьют."""
    if settings.job_test_barrier != point:
        return
    directory = Path(settings.job_test_barrier_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{job_id}.{point}").write_text("reached")
    log.warning("test barrier %s reached for job %s", point, job_id)
    while True:
        time.sleep(1)


def claim_job(job_id: UUID, attempt: int):
    token = uuid4()
    with SessionLocal() as session:
        row = session.execute(
            text(
                """
                UPDATE jobs SET attempts = attempts + 1, status = :running,
                       owner_token = :token,
                       lease_expires_at = now() + (:lease * interval '1 second'),
                       updated_at = now()
                WHERE id = :id AND attempts = :prev
                  AND status IN ('queued', 'retry_wait') AND next_run_at <= now()
                RETURNING snapshot
                """
            ),
            {
                "running": states.RUNNING,
                "token": token,
                "lease": settings.job_lease_seconds,
                "id": job_id,
                "prev": attempt - 1,
            },
        ).first()
        session.commit()
    return (token, row.snapshot) if row else None


def record_failure(job_id: UUID, token: UUID, code: str, message: str, permanent: bool) -> str:
    with SessionLocal() as session:
        row = session.execute(
            text(
                """
                SELECT attempts, max_attempts FROM jobs
                WHERE id = :id AND owner_token = :token AND status = 'running'
                FOR UPDATE
                """
            ),
            {"id": job_id, "token": token},
        ).first()
        if row is None:
            return LOST
        outcome = fail_or_retry(
            session, job_id, row.attempts, row.max_attempts, code, message, permanent
        )
        session.commit()
        return outcome


def complete_job(job_id: UUID, token: UUID, content: bytes) -> str:
    """Результат и переход в `succeeded` — одна транзакция, под проверкой токена."""
    with SessionLocal() as session:
        updated = session.execute(
            text(
                """
                UPDATE jobs SET status = :ok, owner_token = NULL, lease_expires_at = NULL,
                       error_code = NULL, error_message = NULL, updated_at = now()
                WHERE id = :id AND owner_token = :token AND status = 'running'
                """
            ),
            {"ok": states.SUCCEEDED, "id": job_id, "token": token},
        ).rowcount
        if updated != 1:
            session.rollback()
            return LOST
        session.execute(
            text(
                """
                INSERT INTO job_results (job_id, content_type, content, sha256)
                VALUES (:id, :ct, :content, :sha)
                """
            ),
            {
                "id": job_id,
                "ct": states.XLSX_MIME,
                "content": content,
                "sha": hashlib.sha256(content).hexdigest(),
            },
        )
        session.commit()
    return states.SUCCEEDED


def run_job(job_id: UUID, attempt: int, event_id: str = "") -> str:
    claimed = claim_job(job_id, attempt)
    if claimed is None:
        log.info("job %s attempt %s event %s skipped", job_id, attempt, event_id)
        return SKIPPED
    token, snapshot = claimed
    try:
        if settings.job_test_fail:  # только тестовый профиль
            raise RuntimeError("injected failure")
        content = build_menu_report(snapshot)
    except InvalidSnapshot:
        log.exception("job %s has invalid snapshot", job_id)
        return record_failure(
            job_id, token, states.ERR_INVALID_SNAPSHOT, "Menu snapshot is invalid", True
        )
    except Exception:
        log.exception("job %s attempt %s failed", job_id, attempt)
        return record_failure(
            job_id, token, states.ERR_EXECUTION, "Report generation failed", False
        )
    barrier("before_commit", job_id)
    outcome = complete_job(job_id, token, content)
    barrier("after_commit", job_id)
    return outcome
