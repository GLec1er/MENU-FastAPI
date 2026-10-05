"""Outbox-диспетчер и цикл сверки: отдельный процесс (python -m app.jobs.dispatcher)."""
import logging
import signal
import time

from sqlalchemy import text

from app.core.config import settings
from app.jobs import states
from app.jobs.publisher import (
    Publisher,
    PublishError,
    execute_message,
    failed_message,
)
from app.jobs.sync_db import SessionLocal
from app.jobs.transitions import add_outbox, fail_or_retry
from app.report.celery import celery

log = logging.getLogger("dispatcher")


def dispatch_one(publisher: Publisher) -> str:
    """Публикует одну доступную запись outbox. Возвращает none | sent | error."""
    with SessionLocal() as session:
        row = session.execute(
            text(
                """
                SELECT o.id, o.job_id, o.kind, o.attempt, j.error_code, j.error_message
                FROM outbox o JOIN jobs j ON j.id = o.job_id
                WHERE o.published_at IS NULL AND o.available_at <= now()
                ORDER BY o.available_at
                LIMIT 1
                FOR UPDATE OF o SKIP LOCKED
                """
            )
        ).first()
        if row is None:
            return "none"
        try:
            if row.kind == states.EVENT_EXECUTE:
                message = execute_message(celery, row.id, row.job_id, row.attempt)
                queue = states.QUEUE_EXECUTE
            else:
                message = failed_message(
                    row.id, row.job_id, row.attempt, row.error_code, row.error_message
                )
                queue = states.QUEUE_FAILED
            publisher.publish(queue, message)
        except PublishError as exc:
            log.warning("publish of %s failed: %s", row.id, exc)
            session.execute(
                text(
                    """
                    UPDATE outbox SET publish_failures = publish_failures + 1,
                           last_error = :err,
                           available_at = now() + (:delay * interval '1 second')
                    WHERE id = :id
                    """
                ),
                {"err": str(exc)[:255], "delay": settings.publish_retry_delay, "id": row.id},
            )
            session.commit()
            return "error"
        session.execute(
            text("UPDATE outbox SET published_at = now(), last_error = NULL WHERE id = :id"),
            {"id": row.id},
        )
        session.commit()
        return "sent"


def dispatch_pending(publisher: Publisher, limit: int = 100) -> int:
    sent = 0
    for _ in range(limit):
        result = dispatch_one(publisher)
        if result == "sent":
            sent += 1
        else:
            break
    return sent


def reconcile() -> int:
    """Задания с истёкшим владением и неподхваченные опубликованные события."""
    changed = 0
    with SessionLocal() as session:
        expired = session.execute(
            text(
                """
                SELECT id, attempts, max_attempts FROM jobs
                WHERE status = 'running' AND lease_expires_at < now()
                LIMIT 100
                FOR UPDATE SKIP LOCKED
                """
            )
        ).all()
        for job in expired:
            outcome = fail_or_retry(
                session,
                job.id,
                job.attempts,
                job.max_attempts,
                states.ERR_LEASE_EXPIRED,
                "Worker lost or timed out",
            )
            log.warning("job %s lease expired -> %s", job.id, outcome)
            changed += 1
        session.commit()

        stuck = session.execute(
            text(
                """
                SELECT j.id, j.attempts,
                       (SELECT max(o.publish_seq) FROM outbox o
                        WHERE o.job_id = j.id AND o.kind = 'job.execute'
                          AND o.attempt = j.attempts + 1) AS last_seq
                FROM jobs j
                WHERE j.status IN ('queued', 'retry_wait') AND j.next_run_at <= now()
                  AND NOT EXISTS (
                        SELECT 1 FROM outbox o
                        WHERE o.job_id = j.id AND o.kind = 'job.execute'
                          AND o.attempt = j.attempts + 1 AND o.published_at IS NULL)
                  AND (SELECT max(o.published_at) FROM outbox o
                       WHERE o.job_id = j.id AND o.kind = 'job.execute'
                         AND o.attempt = j.attempts + 1)
                      < now() - (:timeout * interval '1 second')
                LIMIT 100
                FOR UPDATE OF j SKIP LOCKED
                """
            ),
            {"timeout": settings.redelivery_timeout},
        ).all()
        for job in stuck:
            add_outbox(
                session, job.id, states.EVENT_EXECUTE, job.attempts + 1, seq=job.last_seq + 1
            )
            log.warning("job %s was not picked up; republishing", job.id)
            changed += 1
        session.commit()
    return changed


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    stop = {"flag": False}

    def _stop(*_):
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    publisher = Publisher()
    next_reconcile = 0.0
    log.info("dispatcher started")
    while not stop["flag"]:
        try:
            now = time.monotonic()
            if now >= next_reconcile:
                reconcile()
                next_reconcile = now + settings.reconcile_interval
            sent = dispatch_pending(publisher)
        except Exception:  # БД недоступна и т.п.: процесс не должен падать
            log.exception("dispatcher iteration failed")
            sent = 0
            time.sleep(settings.dispatcher_poll_interval)
        if sent == 0:
            time.sleep(settings.dispatcher_poll_interval)
    publisher.close()


if __name__ == "__main__":
    main()
