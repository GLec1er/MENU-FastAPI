import httpx

from e2e.conftest import (
    BASE,
    compose,
    create_job,
    job_row,
    results,
    seed_menu,
    sql,
    wait_barrier,
    wait_status,
)


def test_happy_path_returns_xlsx(api):
    seed_menu(api)
    job_id = create_job(api)
    wait_status(job_id, "succeeded")
    resp = api.get(f"/api/v1/jobs/{job_id}/result")
    assert resp.status_code == 200
    assert resp.content[:2] == b"PK"
    assert f"menu-report-{job_id}.xlsx" in resp.headers["content-disposition"]
    assert api.get(f"/api/v1/report/{job_id}").status_code == 200
    assert results(job_id)[0] == 1


def test_rabbitmq_down_during_post_still_accepts_and_completes(api):
    compose("stop", "rabbitmq")
    job_id = create_job(api)  # 202 без брокера
    assert job_row(job_id)[0] == "queued"
    assert sql("SELECT count(*) FROM outbox WHERE job_id = %s", job_id)[0][0] == 1
    assert sql("SELECT published_at FROM outbox WHERE job_id = %s", job_id)[0][0] is None

    compose("start", "rabbitmq")
    compose("up", "-d", "--wait", "rabbitmq")
    wait_status(job_id, "succeeded", timeout=90)
    assert results(job_id)[0] == 1


def test_worker_killed_while_building_is_retried(api):
    compose("up", "-d", "--force-recreate", "--wait", "worker", env={"JOB_TEST_BARRIER": "before_commit"})
    job_id = create_job(api)
    wait_barrier(job_id, "before_commit")
    assert job_row(job_id)[0] == "running"
    compose("kill", "worker")
    assert results(job_id)[0] == 0

    compose("up", "-d", "--force-recreate", "--wait", "worker")  # без барьера
    wait_status(job_id, "succeeded", timeout=90)
    assert job_row(job_id)[1] == 2  # две начатые попытки
    assert results(job_id)[0] == 1


def test_worker_killed_after_commit_before_ack_keeps_single_result(api):
    compose("up", "-d", "--force-recreate", "--wait", "worker", env={"JOB_TEST_BARRIER": "after_commit"})
    job_id = create_job(api)
    wait_barrier(job_id, "after_commit")
    count, digest = results(job_id)
    assert count == 1
    compose("kill", "worker")

    compose("up", "-d", "--force-recreate", "--wait", "worker")  # сообщение доставляется повторно
    wait_until_redelivered(job_id)
    assert job_row(job_id)[0] == "succeeded"
    assert results(job_id) == (1, digest)


def wait_until_redelivered(job_id):
    # Ждём, пока новый worker увидит сообщение: брокер больше не держит его unacked.
    from e2e.conftest import wait_until

    def drained():
        out = compose("exec", "-T", "rabbitmq", "rabbitmqctl", "list_queues", "name", "messages", check=False).stdout
        line = next((l for l in out.splitlines() if l.startswith("jobs.execute")), "")
        return line.split()[-1] == "0"

    wait_until(drained, 40, 1, what="jobs.execute drained")


def test_duplicate_publication_and_two_workers_one_result(api):
    compose("up", "-d", "--scale", "worker=2", "--no-recreate", "--wait", "worker")
    compose("stop", "rabbitmq")
    job_id = create_job(api)
    sql(
        "INSERT INTO outbox (id, job_id, kind, attempt, publish_seq) "
        "VALUES (gen_random_uuid(), %s, 'job.execute', 1, 1)",
        job_id,
    )
    compose("start", "rabbitmq")
    compose("up", "-d", "--wait", "rabbitmq")
    wait_status(job_id, "succeeded", timeout=90)
    published = sql(
        "SELECT count(*) FROM outbox WHERE job_id = %s AND published_at IS NOT NULL", job_id
    )[0][0]
    assert published == 2
    assert job_row(job_id)[1] == 1
    assert results(job_id)[0] == 1
    assert api.get(f"/api/v1/jobs/{job_id}").json()["status"] == "succeeded"
    compose("up", "-d", "--scale", "worker=1", "--no-recreate", "worker")


def test_permanently_failing_job_stops_after_three_attempts(api):
    compose("up", "-d", "--force-recreate", "--wait", "worker", env={"JOB_TEST_FAIL": "1"})
    job_id = create_job(api)
    wait_status(job_id, "failed", timeout=90)
    body = api.get(f"/api/v1/jobs/{job_id}").json()
    assert (body["attempts"], body["max_attempts"]) == (3, 3)
    assert body["error_code"] == "execution_error"
    assert "injected" not in (body["error_message"] or "")
    assert api.get(f"/api/v1/jobs/{job_id}/result").status_code == 409
    assert [j["id"] for j in api.get("/api/v1/jobs", params={"status": "failed"}).json()["items"]] == [job_id]

    # Событие job.failed опубликовано и лежит в jobs.failed с постоянным ID.
    event_id = httpx_event_id(job_id)
    out = compose(
        "exec", "-T", "rabbitmq", "rabbitmqctl", "list_queues", "name", "messages"
    ).stdout
    failed_line = next(l for l in out.splitlines() if l.startswith("jobs.failed"))
    assert int(failed_line.split()[-1]) >= 1
    assert event_id


def httpx_event_id(job_id):
    from e2e.conftest import wait_until

    def published():
        rows = sql(
            "SELECT id FROM outbox WHERE job_id = %s AND kind = 'job.failed' "
            "AND published_at IS NOT NULL",
            job_id,
        )
        return rows[0][0] if rows else None

    return wait_until(published, 30, what="job.failed published")


def test_unknown_job_is_404(api):
    assert api.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000").status_code == 404
    assert httpx.get(f"{BASE}/api/v1/jobs/00000000-0000-0000-0000-000000000000/result").status_code == 404
