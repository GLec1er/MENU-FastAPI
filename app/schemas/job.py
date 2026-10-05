from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel


class JobCreate(BaseModel):
    kind: Literal["menu_report"]


class JobOut(BaseModel):
    id: UUID
    kind: str
    status: str
    attempts: int
    max_attempts: int
    next_run_at: Optional[datetime]
    error_code: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True


class JobList(BaseModel):
    items: List[JobOut]
    total: int
    limit: int
    offset: int
