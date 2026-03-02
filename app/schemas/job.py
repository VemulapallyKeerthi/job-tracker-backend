from enum import Enum
from pydantic import BaseModel
from datetime import date

class JobStatus(str, Enum):
    saved = "saved"
    applied = "applied"
    interviewing = "interviewing"
    offer = "offer"
    rejected = "rejected"

class JobBase(BaseModel):
    title: str
    company: str
    location: str | None = None
    posted_date: date | None = None
    description: str | None = None
    apply_link: str
    status: JobStatus = JobStatus.saved

class JobResponse(JobBase):
    id: int

    class Config:
        from_attributes = True