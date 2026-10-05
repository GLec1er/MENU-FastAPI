import json
import logging
from typing import Optional

import amqp
from kombu.serialization import dumps
from kombu.utils.url import parse_url

from app.core.config import BROKER_URL, settings
from app.jobs import states

log = logging.getLogger(__name__)


class PublishError(Exception):
    pass


class Publisher:
    """Публикация в RabbitMQ с publisher confirms и mandatory-проверкой маршрута."""

    def __init__(self, url: str = BROKER_URL, timeout: Optional[float] = None):
        self.timeout = timeout or settings.publish_timeout
        parsed = parse_url(url)
        self.params = dict(
            host=f"{parsed['hostname']}:{parsed['port'] or 5672}",
            userid=parsed["userid"],
            password=parsed["password"],
            virtual_host=parsed["virtual_host"] or "/",
        )
        self.conn: Optional[amqp.Connection] = None
        self.channel = None

    def _ensure(self):
        if self.conn is not None and self.channel is not None:
            return
        self.close()
        conn = amqp.Connection(
            connect_timeout=self.timeout,
            read_timeout=self.timeout,
            write_timeout=self.timeout,
            confirm_publish=True,
            **self.params,
        )
        conn.connect()
        channel = conn.channel()
        for queue in (states.QUEUE_EXECUTE, states.QUEUE_FAILED):
            channel.queue_declare(queue, durable=True, auto_delete=False)
        self.conn, self.channel = conn, channel

    def close(self):
        conn, self.conn, self.channel = self.conn, None, None
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa
                pass

    def publish(self, queue: str, message: amqp.Message) -> None:
        try:
            self._ensure()
            self.channel.basic_publish(
                message,
                exchange="",
                routing_key=queue,
                mandatory=True,
                confirm_timeout=self.timeout,
            )
            if not self.channel.returned_messages.empty():
                raise PublishError(f"message to {queue} was not routed")
        except PublishError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise PublishError(f"{type(exc).__name__}: {exc}") from exc


def execute_message(celery_app, event_id, job_id, attempt) -> amqp.Message:
    task = celery_app.amqp.as_task_v2(
        str(event_id),
        "execute_job",
        args=[str(job_id), attempt, str(event_id)],
        kwargs={},
        ignore_result=True,
    )
    content_type, encoding, body = dumps(task.body, serializer="json")
    return amqp.Message(
        body,
        content_type=content_type,
        content_encoding=encoding,
        application_headers=task.headers,
        delivery_mode=2,
        correlation_id=str(event_id),
        message_id=str(event_id),
    )


def failed_message(event_id, job_id, attempts, code, message) -> amqp.Message:
    body = json.dumps(
        {
            "event_id": str(event_id),
            "job_id": str(job_id),
            "attempts": attempts,
            "error_code": code,
            "error_message": message,
        }
    )
    return amqp.Message(
        body,
        content_type="application/json",
        content_encoding="utf-8",
        delivery_mode=2,
        message_id=str(event_id),
    )
