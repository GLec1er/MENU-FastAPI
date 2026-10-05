import uuid

import pytest

from tests.helpers import execute, fetch, insert_job, scalar
from tests.test_data import menu_data

JOBS = "/api/v1/jobs"


async def test_create_job_persists_job_and_outbox(async_client):
    resp = await async_client.post(JOBS, json={"kind": "menu_report"})
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert body["kind"] == "menu_report"
    assert body["attempts"] == 0
    assert body["max_attempts"] == 3
    assert resp.headers["location"] == f"{JOBS}/{body['id']}"
    assert scalar("SELECT count(*) FROM jobs") == 1
    events = fetch("SELECT kind, attempt, publish_seq, published_at FROM outbox")
    assert [(e.kind, e.attempt, e.publish_seq, e.published_at) for e in events] == [
        ("job.execute", 1, 0, None)
    ]


async def test_create_job_rejects_unknown_kind(async_client):
    resp = await async_client.post(JOBS, json={"kind": "rm -rf"})
    assert resp.status_code == 422
    assert scalar("SELECT count(*) FROM jobs") == 0


async def test_snapshot_is_read_from_database(async_client, create_dish):
    resp = await async_client.post(JOBS, json={"kind": "menu_report"})
    assert resp.status_code == 202
    snapshot = scalar("SELECT snapshot FROM jobs")
    assert snapshot[0]["title"] == menu_data["title"]
    assert snapshot[0]["submenus"][0]["dishes"][0]["id"] == create_dish.id
    assert "snapshot" not in resp.json()


async def test_create_job_is_atomic(async_client, monkeypatch):
    def broken_outbox(**_):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.jobs.service.Outbox", broken_outbox)
    with pytest.raises(RuntimeError):
        await async_client.post(JOBS, json={"kind": "menu_report"})
    assert scalar("SELECT count(*) FROM jobs") == 0
    assert scalar("SELECT count(*) FROM outbox") == 0


async def test_get_job(async_client):
    job_id = insert_job()
    resp = await async_client.get(f"{JOBS}/{job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(job_id)
    assert body["error_code"] is None
    assert {"attempts", "max_attempts", "created_at", "updated_at"} <= body.keys()


async def test_get_unknown_job_is_404(async_client):
    resp = await async_client.get(f"{JOBS}/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_list_jobs_pagination_and_filter(async_client):
    for _ in range(3):
        insert_job()
    failed = insert_job(status="failed")
    execute(
        "UPDATE jobs SET error_code='execution_error', error_message='x' WHERE id=:id",
        id=failed,
    )
    resp = await async_client.get(JOBS, params={"limit": 2})
    body = resp.json()
    assert resp.status_code == 200
    assert (body["total"], len(body["items"]), body["limit"], body["offset"]) == (4, 2, 2, 0)
    assert all("snapshot" not in item for item in body["items"])

    resp = await async_client.get(JOBS, params={"status": "failed"})
    items = resp.json()["items"]
    assert [i["id"] for i in items] == [str(failed)]
    assert items[0]["error_code"] == "execution_error"

    assert (await async_client.get(JOBS, params={"limit": 101})).status_code == 422
    assert (await async_client.get(JOBS, params={"status": "bogus"})).status_code == 422


def _finish(job_id, content=b"PK-xlsx"):
    execute("UPDATE jobs SET status='succeeded' WHERE id=:id", id=job_id)
    execute(
        "INSERT INTO job_results (job_id, content_type, content, sha256) "
        "VALUES (:id, 'application/octet-stream', :c, 'x')",
        id=job_id,
        c=content,
    )


async def test_result_status_codes(async_client):
    job_id = insert_job()
    assert (await async_client.get(f"{JOBS}/{uuid.uuid4()}/result")).status_code == 404
    assert (await async_client.get(f"{JOBS}/{job_id}/result")).status_code == 409

    _finish(job_id)
    resp = await async_client.get(f"{JOBS}/{job_id}/result")
    assert resp.status_code == 200
    assert resp.content == b"PK-xlsx"
    assert f"menu-report-{job_id}.xlsx" in resp.headers["content-disposition"]


async def test_legacy_report_routes_use_jobs(async_client):
    resp = await async_client.post("/api/v1/report/")
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] is True
    task_id = body["message"].split()[1]
    assert body["message"] == f"Task {task_id} has been created"
    assert scalar("SELECT count(*) FROM jobs WHERE id=:id", id=task_id) == 1

    assert (await async_client.get(f"/api/v1/report/{task_id}")).status_code == 425
    assert (await async_client.get(f"/api/v1/report/{task_id}/download")).status_code == 404

    _finish(uuid.UUID(task_id))
    resp = await async_client.get(f"/api/v1/report/{task_id}")
    assert resp.status_code == 200
    assert resp.json() == {"status": True, "message": "Task is ready"}
    resp = await async_client.get(f"/api/v1/report/{task_id}/download")
    assert resp.status_code == 200
    assert resp.content == b"PK-xlsx"


async def test_legacy_report_malformed_id(async_client):
    assert (await async_client.get("/api/v1/report/not-a-uuid")).status_code == 425
    assert (await async_client.get("/api/v1/report/not-a-uuid/download")).status_code == 404
