import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.config import settings
from app.jobs import dispatcher, executor
from app.jobs.publisher import PublishError
from tests.conftest import Session
from tests.helpers import execute, fetch, insert_job, scalar


@pytest.fixture(autouse=True)
def sync_sessions(monkeypatch):
    monkeypatch.setattr(executor, "SessionLocal", Session)
    monkeypatch.setattr(dispatcher, "SessionLocal", Session)
    monkeypatch.setattr(settings, "retry_delays", [0.0])


def job(job_id):
    return fetch("SELECT * FROM jobs WHERE id=:id", id=job_id)[0]


def test_success_commits_one_result_and_ignores_redelivery():
    job_id = insert_job()
    assert executor.run_job(job_id, 1) == "succeeded"
    row = job(job_id)
    assert (row.status, row.attempts, row.owner_token) == ("succeeded", 1, None)
    result = fetch("SELECT content, sha256 FROM job_results WHERE job_id=:id", id=job_id)
    assert len(result) == 1
    assert result[0].sha256 == hashlib.sha256(bytes(result[0].content)).hexdigest()

    # Повторная доставка того же сообщения не создаёт второй результат.
    assert executor.run_job(job_id, 1) == executor.SKIPPED
    assert scalar("SELECT count(*) FROM job_results WHERE job_id=:id", id=job_id) == 1
    assert job(job_id).status == "succeeded"


def test_stale_or_future_attempt_is_skipped():
    job_id = insert_job()
    assert executor.run_job(job_id, 2) == executor.SKIPPED
    assert job(job_id).attempts == 0


def test_concurrent_claims_give_one_winner():
    job_id = insert_job()
    with ThreadPoolExecutor(8) as pool:
        claims = list(pool.map(lambda _: executor.claim_job(job_id, 1), range(8)))
    assert sum(c is not None for c in claims) == 1
    assert job(job_id).attempts == 1


def test_three_failures_end_in_failed_with_event(monkeypatch):
    def boom(_):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(executor, "build_menu_report", boom)
    job_id = insert_job()

    assert executor.run_job(job_id, 1) == "retry_wait"
    assert job(job_id).status == "retry_wait"
    assert executor.run_job(job_id, 2) == "retry_wait"
    assert executor.run_job(job_id, 3) == "failed"
    row = job(job_id)
    assert (row.status, row.attempts) == ("failed", 3)
    assert row.error_code == "execution_error"
    assert "secret" not in row.error_message
    assert scalar("SELECT count(*) FROM job_results") == 0

    events = fetch(
        "SELECT kind, attempt FROM outbox WHERE job_id=:id ORDER BY kind, attempt", id=job_id
    )
    assert [(e.kind, e.attempt) for e in events] == [
        ("job.execute", 1),
        ("job.execute", 2),
        ("job.execute", 3),
        ("job.failed", 3),
    ]
    # Терминальное состояние не меняется ни повтором, ни сверкой.
    assert executor.run_job(job_id, 4) == executor.SKIPPED
    dispatcher.reconcile()
    assert job(job_id).status == "failed"


def test_retry_is_not_runnable_before_next_run_at(monkeypatch):
    monkeypatch.setattr(settings, "retry_delays", [3600.0])
    monkeypatch.setattr(executor, "build_menu_report", lambda _: 1 / 0)
    job_id = insert_job()
    assert executor.run_job(job_id, 1) == "retry_wait"
    assert executor.run_job(job_id, 2) == executor.SKIPPED
    assert job(job_id).attempts == 1


def test_invalid_snapshot_fails_without_retries():
    job_id = insert_job(snapshot=[{"title": "no other keys"}])
    assert executor.run_job(job_id, 1) == "failed"
    row = job(job_id)
    assert (row.status, row.attempts, row.error_code) == ("failed", 1, "invalid_snapshot")
    assert scalar(
        "SELECT count(*) FROM outbox WHERE job_id=:id AND kind='job.failed'", id=job_id
    ) == 1


def test_expired_lease_is_retried_and_late_worker_cannot_commit():
    job_id = insert_job()
    token, _ = executor.claim_job(job_id, 1)
    execute("UPDATE jobs SET lease_expires_at = now() - interval '1 second'")
    assert dispatcher.reconcile() == 1
    row = job(job_id)
    assert (row.status, row.error_code) == ("retry_wait", "lease_expired")
    assert scalar(
        "SELECT count(*) FROM outbox WHERE job_id=:id AND kind='job.execute' AND attempt=2",
        id=job_id,
    ) == 1
    # Опоздавший worker не может зафиксировать результат.
    assert executor.complete_job(job_id, token, b"late") == executor.LOST
    assert scalar("SELECT count(*) FROM job_results") == 0
    assert executor.run_job(job_id, 2) == "succeeded"


def test_expired_lease_on_last_attempt_fails_job():
    job_id = insert_job(status="running", attempts=3)
    execute(
        "UPDATE jobs SET owner_token = gen_random_uuid(),"
        " lease_expires_at = now() - interval '1 second'"
    )
    dispatcher.reconcile()
    assert job(job_id).status == "failed"
    assert scalar(
        "SELECT count(*) FROM outbox WHERE job_id=:id AND kind='job.failed'", id=job_id
    ) == 1


def test_unclaimed_published_event_is_republished_once():
    job_id = insert_job(published=True)
    assert dispatcher.reconcile() == 0  # опубликовано только что
    execute("UPDATE outbox SET published_at = now() - interval '300 seconds'")
    assert dispatcher.reconcile() == 1
    seqs = fetch("SELECT publish_seq FROM outbox WHERE job_id=:id ORDER BY 1", id=job_id)
    assert [s.publish_seq for s in seqs] == [0, 1]
    # Пока новая публикация ждёт отправки, дублей не создаётся.
    assert dispatcher.reconcile() == 0


def test_retry_wait_is_not_republished_before_due_time():
    job_id = insert_job(status="retry_wait", attempts=1, published=True)
    execute(
        "UPDATE outbox SET published_at = now() - interval '300 seconds';"
        "UPDATE jobs SET next_run_at = now() + interval '1 hour'"
    )
    assert dispatcher.reconcile() == 0
    assert scalar("SELECT count(*) FROM outbox WHERE job_id=:id", id=job_id) == 1


class FakePublisher:
    def __init__(self, fail=False):
        self.fail, self.sent = fail, []

    def publish(self, queue, message):
        if self.fail:
            raise PublishError("broker down")
        self.sent.append((queue, message))


def test_dispatch_marks_published_only_after_confirm():
    job_id = insert_job()
    broken = FakePublisher(fail=True)
    assert dispatcher.dispatch_one(broken) == "error"
    row = fetch("SELECT published_at, publish_failures, last_error FROM outbox")[0]
    assert row.published_at is None and row.publish_failures == 1
    assert "broker down" in row.last_error
    assert job(job_id).status == "queued"

    execute("UPDATE outbox SET available_at = now()")
    ok = FakePublisher()
    assert dispatcher.dispatch_one(ok) == "sent"
    assert scalar("SELECT published_at FROM outbox") is not None
    queue, message = ok.sent[0]
    assert queue == "jobs.execute"
    body = json.loads(message.body)
    assert body[0][0] == str(job_id) and body[0][1] == 1
    assert message.properties["delivery_mode"] == 2
    assert message.properties["application_headers"]["task"] == "execute_job"
    assert dispatcher.dispatch_one(ok) == "none"


def test_failed_event_goes_to_failed_queue_with_stable_id():
    job_id = insert_job()
    executor.claim_job(job_id, 1)
    execute("UPDATE jobs SET attempts = 3")
    execute("UPDATE jobs SET lease_expires_at = now() - interval '1 second'")
    dispatcher.reconcile()
    execute("UPDATE outbox SET published_at = now() WHERE kind='job.execute'")
    fake = FakePublisher()
    assert dispatcher.dispatch_one(fake) == "sent"
    queue, message = fake.sent[0]
    event_id = scalar("SELECT id FROM outbox WHERE kind='job.failed'")
    assert queue == "jobs.failed"
    assert json.loads(message.body)["event_id"] == str(event_id)
    assert json.loads(message.body)["job_id"] == str(job_id)
