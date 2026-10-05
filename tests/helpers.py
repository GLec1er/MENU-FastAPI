import uuid

from sqlalchemy import text

from tests.conftest import Session

SNAPSHOT = [
    {
        "id": "m1",
        "title": "Menu 1",
        "description": "d",
        "submenus": [
            {
                "id": "s1",
                "title": "Sub 1",
                "description": "d",
                "dishes": [
                    {"id": "d1", "title": "Dish 1", "description": "d", "price": "12.50"}
                ],
            }
        ],
    }
]


def insert_job(snapshot=None, status="queued", attempts=0, published=False) -> uuid.UUID:
    job_id = uuid.uuid4()
    with Session() as s:
        s.execute(
            text(
                """
                INSERT INTO jobs (id, kind, snapshot, status, attempts, max_attempts)
                VALUES (:id, 'menu_report', CAST(:snap AS jsonb), :st, :att, 3)
                """
            ),
            {
                "id": job_id,
                "snap": __import__("json").dumps(SNAPSHOT if snapshot is None else snapshot),
                "st": status,
                "att": attempts,
            },
        )
        s.execute(
            text(
                """
                INSERT INTO outbox (id, job_id, kind, attempt, publish_seq, published_at)
                VALUES (gen_random_uuid(), :id, 'job.execute', :att, 0,
                        CASE WHEN :pub THEN now() END)
                """
            ),
            {"id": job_id, "att": attempts + 1, "pub": published},
        )
        s.commit()
    return job_id


def fetch(sql: str, **params):
    with Session() as s:
        return s.execute(text(sql), params).all()


def scalar(sql: str, **params):
    with Session() as s:
        return s.execute(text(sql), params).scalar()


def execute(sql: str, **params):
    with Session() as s:
        s.execute(text(sql), params)
        s.commit()
