"""Переходы состояний заданий. Всё выполняется в транзакции вызывающего."""
from sqlalchemy import text

from app.core.config import settings
from app.jobs import states


def add_outbox(conn, job_id, kind, attempt, delay=0.0, seq=0):
    conn.execute(
        text(
            """
            INSERT INTO outbox (id, job_id, kind, attempt, publish_seq, available_at)
            VALUES (gen_random_uuid(), :job_id, :kind, :attempt, :seq,
                    now() + (:delay * interval '1 second'))
            ON CONFLICT ON CONSTRAINT uq_outbox_event DO NOTHING
            """
        ),
        {"job_id": job_id, "kind": kind, "attempt": attempt, "seq": seq, "delay": delay},
    )


def retry_delay(attempts: int) -> float:
    delays = settings.retry_delays
    return delays[min(attempts - 1, len(delays) - 1)] if delays else 0.0


def fail_or_retry(conn, job_id, attempts, max_attempts, code, message, permanent=False):
    """Заблокированное задание `running` -> `retry_wait` либо `failed` (+ outbox)."""
    if permanent or attempts >= max_attempts:
        conn.execute(
            text(
                """
                UPDATE jobs SET status = :st, owner_token = NULL, lease_expires_at = NULL,
                       error_code = :code, error_message = :msg, updated_at = now()
                WHERE id = :id
                """
            ),
            {"st": states.FAILED, "code": code, "msg": message[:255], "id": job_id},
        )
        add_outbox(conn, job_id, states.EVENT_FAILED, attempts)
        return states.FAILED
    delay = retry_delay(attempts)
    conn.execute(
        text(
            """
            UPDATE jobs SET status = :st, owner_token = NULL, lease_expires_at = NULL,
                   error_code = :code, error_message = :msg,
                   next_run_at = now() + (:delay * interval '1 second'), updated_at = now()
            WHERE id = :id
            """
        ),
        {
            "st": states.RETRY_WAIT,
            "code": code,
            "msg": message[:255],
            "delay": delay,
            "id": job_id,
        },
    )
    add_outbox(conn, job_id, states.EVENT_EXECUTE, attempts + 1, delay=delay)
    return states.RETRY_WAIT
