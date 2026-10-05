from http import HTTPStatus
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from app.jobs import states
from app.jobs.service import JobService, job_service
from app.schemas.status import StatusMessage

router = APIRouter(
    prefix="/report",
    tags=["Report"],
)


def _parse_id(task_id: str) -> UUID | None:
    try:
        return UUID(task_id)
    except ValueError:
        return None


@router.post(
    "/",
    response_model=StatusMessage,
    status_code=HTTPStatus.ACCEPTED,
    summary="Запрос для генерации отчета",
)
async def create_task_for_report(
    service: JobService = Depends(job_service),
) -> StatusMessage:
    job = await service.create_menu_report()
    return StatusMessage(
        status=True,
        message=f"Task {job.id} has been created",
    )


@router.get(
    "/{task_id}",
    response_model=StatusMessage,
    status_code=HTTPStatus.OK,
    summary="Запрос статуса",
)
async def get_task_status(
    task_id: str,
    service: JobService = Depends(job_service),
) -> StatusMessage:
    job_id = _parse_id(task_id)
    if job_id is not None and await service.get_status(job_id) == states.SUCCEEDED:
        return StatusMessage(
            status=True,
            message="Task is ready",
        )
    raise HTTPException(status_code=425, detail="Task is not ready or not found")


@router.get(
    "/{task_id}/download",
    status_code=HTTPStatus.OK,
    summary="Загрузка готового отчета",
)
async def get_report(
    task_id: str,
    service: JobService = Depends(job_service),
) -> Response:
    job_id = _parse_id(task_id)
    result = await service.get_result(job_id) if job_id else None
    if result is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return Response(
        content=result.content,
        media_type=result.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="menu-report-{job_id}.xlsx"'
        },
    )
