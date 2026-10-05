"""Импорты класса Base и всех моделей для Alembic."""
from app.core.db import Base  # noqa
from app.models import Dish, Job, JobResult, Menu, Outbox, SubMenu  # noqa
