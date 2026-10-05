"""Испытания со сбоями на реальных PostgreSQL, RabbitMQ, диспетчере и worker.

Запускаются с хоста (нужен docker compose): tests/e2e/run.sh
"""
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import httpx
import psycopg2
import pytest

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "menu-e2e"
API_PORT = os.getenv("E2E_API_PORT", "58000")
DB_PORT = os.getenv("E2E_DB_PORT", "55432")
BASE = f"http://localhost:{API_PORT}"
BARRIERS = Path(os.getenv("E2E_BARRIER_DIR") or tempfile.mkdtemp(prefix="menu-e2e-"))


def compose(*args, env=None, check=True):
    full_env = {
        **os.environ,
        "E2E_API_PORT": API_PORT,
        "E2E_DB_PORT": DB_PORT,
        "E2E_BARRIER_DIR": str(BARRIERS),
        "JOB_TEST_BARRIER": "",
        "JOB_TEST_FAIL": "",
        **(env or {}),
    }
    proc = subprocess.run(
        ["docker", "compose", "-p", PROJECT, "-f", "docker-compose.e2e.yml", *args],
        cwd=ROOT,
        env=full_env,
        capture_output=True,
        text=True,
    )
    if check and proc.returncode:
        raise RuntimeError(f"docker compose {' '.join(args)} failed:\n{proc.stderr[-3000:]}")
    return proc


def wait_until(predicate, timeout=60, interval=0.5, what="condition"):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except Exception as exc:  # noqa
            last = exc
        time.sleep(interval)
    raise AssertionError(f"timeout waiting for {what}; last={last!r}")


def sql(query, *params):
    conn = psycopg2.connect(
        host="localhost", port=DB_PORT, user="e2e", password="e2e", dbname="menu"
    )
    try:
        with conn, conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall() if cur.description else None
    finally:
        conn.close()


@pytest.fixture(scope="session", autouse=True)
def stack():
    BARRIERS.mkdir(parents=True, exist_ok=True)
    compose("down", "-v", "--remove-orphans", check=False)
    compose("up", "-d", "--build", "--wait", "db", "redis", "rabbitmq", "web", "dispatcher", "worker")
    wait_until(lambda: httpx.get(f"{BASE}/api/v1/jobs").status_code == 200, 90, what="api")
    yield
    if not os.getenv("E2E_KEEP"):
        compose("down", "-v", "--remove-orphans", check=False)


@pytest.fixture(autouse=True)
def clean_state():
    compose("up", "-d", "--wait", "rabbitmq", "dispatcher", "worker")
    sql("DELETE FROM jobs")
    for f in BARRIERS.glob("*"):
        f.unlink()
    yield
    compose("up", "-d", "--force-recreate", "--wait", "worker", env={})


@pytest.fixture
def api():
    with httpx.Client(base_url=BASE, timeout=15) as client:
        yield client


def create_job(api) -> str:
    resp = api.post("/api/v1/jobs", json={"kind": "menu_report"})
    assert resp.status_code == 202, resp.text
    return resp.json()["id"]


def job_row(job_id):
    rows = sql(
        "SELECT status, attempts, error_code FROM jobs WHERE id = %s", job_id
    )
    return rows[0] if rows else None


def wait_status(job_id, status, timeout=60):
    return wait_until(
        lambda: (job_row(job_id) or (None,))[0] == status and job_row(job_id),
        timeout,
        what=f"job {job_id} -> {status}",
    )


def results(job_id):
    return sql(
        "SELECT count(*), min(sha256) FROM job_results WHERE job_id = %s", job_id
    )[0]


def wait_barrier(job_id, point, timeout=60):
    path = BARRIERS / f"{job_id}.{point}"
    wait_until(path.exists, timeout, 0.2, what=f"barrier {point}")


def seed_menu(api):
    resp = api.post("/api/v1/menus/", json={"title": f"m-{uuid.uuid4()}", "description": "d"})
    assert resp.status_code == 201, resp.text
    return resp.json()
