from typing import Optional
from uuid import UUID, uuid4

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_async_session
from app.crud.menu import menu_crud
from app.jobs import states
from app.models import Job, JobResult, Outbox
from app.schemas.job import JobOut


class JobService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_menu_report(self) -> JobOut:
        """Принять задание: снимок меню, задание и outbox — одной транзакцией."""
        try:
            snapshot = await menu_crud.select_all_data(self.session)
            job = Job(
                id=uuid4(),
                kind=states.KIND_MENU_REPORT,
                snapshot=snapshot,
                status=states.QUEUED,
                attempts=0,
                max_attempts=settings.job_max_attempts,
            )
            self.session.add(job)
            await self.session.flush()
            self.session.add(
                Outbox(
                    job_id=job.id,
                    kind=states.EVENT_EXECUTE,
                    attempt=1,
                    publish_seq=0,
                )
            )
            await self.session.flush()
            await self.session.refresh(job)
            out = JobOut.from_orm(job)
            await self.session.commit()
        except BaseException:
            await self.session.rollback()
            raise
        return out

    async def get(self, job_id: UUID) -> Optional[JobOut]:
        job = await self.session.get(Job, job_id)
        return JobOut.from_orm(job) if job else None

    async def list(self, status: Optional[str], limit: int, offset: int):
        # Тело снимка в список не попадает: выбираем только метаданные.
        cols = [c for c in Job.__table__.columns if c.name not in ("snapshot", "owner_token")]
        query = select(*cols)
        count = select(func.count()).select_from(Job)
        if status:
            query = query.where(Job.status == status)
            count = count.where(Job.status == status)
        rows = await self.session.execute(
            query.order_by(Job.created_at.desc(), Job.id).limit(limit).offset(offset)
        )
        total = await self.session.scalar(count)
        return [JobOut.parse_obj(dict(r._mapping)) for r in rows], total

    async def get_status(self, job_id: UUID) -> Optional[str]:
        return await self.session.scalar(select(Job.status).where(Job.id == job_id))

    async def get_result(self, job_id: UUID) -> Optional[JobResult]:
        return await self.session.get(JobResult, job_id)


async def job_service(session: AsyncSession = Depends(get_async_session)) -> JobService:
    return JobService(session=session)
