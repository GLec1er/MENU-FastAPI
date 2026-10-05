from http import HTTPStatus
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.jobs import states
from app.jobs.service import JobService, job_service
from app.schemas.job import JobCreate, JobList, JobOut

router = APIRouter(prefix="/jobs", tags=["Jobs"])


def result_headers(job_id: UUID) -> dict:
    return {"Content-Disposition": f'attachment; filename="menu-report-{job_id}.xlsx"'}


@router.post(
    "",
    response_model=JobOut,
    status_code=HTTPStatus.ACCEPTED,
    summary="Создать задание",
)
async def create_job(
    body: JobCreate,
    response: Response,
    service: JobService = Depends(job_service),
) -> JobOut:
    job = await service.create_menu_report()
    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    return job


@router.get("", response_model=JobList, summary="Список заданий")
async def list_jobs(
    status: Optional[str] = Query(None, regex="^(%s)$" % "|".join(states.STATUSES)),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: JobService = Depends(job_service),
) -> JobList:
    items, total = await service.list(status, limit, offset)
    return JobList(items=items, total=total, limit=limit, offset=offset)


@router.get("/{job_id}", response_model=JobOut, summary="Состояние задания")
async def get_job(job_id: UUID, service: JobService = Depends(job_service)) -> JobOut:
    job = await service.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/{job_id}/result", summary="Результат задания (XLSX)")
async def get_job_result(
    job_id: UUID, service: JobService = Depends(job_service)
) -> Response:
    status = await service.get_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Job not found")
    result = await service.get_result(job_id) if status == states.SUCCEEDED else None
    if result is None:
        raise HTTPException(status_code=409, detail="Result is not available")
    return Response(
        content=result.content,
        media_type=result.content_type,
        headers=result_headers(job_id),
    )
