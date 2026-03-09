from enum import Enum
from pydantic import BaseModel, Field
from datetime import date

class JobStatus(str, Enum):
    saved     = "saved"
    applied   = "applied"
    interview = "interview"
    offer     = "offer"
    rejected  = "rejected"

class JobBase(BaseModel):
    title       : str
    company     : str
    location    : str | None   = None
    posted_date : date | None  = None
    description : str | None   = None
    apply_link  : str | None   = None
    url         : str | None   = Field(default=None, exclude=True)  # scraper alias for apply_link
    source      : str | None   = None
    status      : JobStatus    = JobStatus.saved

    def model_post_init(self, __context):
        if self.url and not self.apply_link:
            self.apply_link = self.url

class JobResponse(BaseModel):
    id          : int
    title       : str
    company     : str
    location    : str | None   = None
    posted_date : date | None  = None
    description : str | None   = None
    apply_link  : str | None   = None
    source      : str | None   = None
    status      : str

    # ML-derived fields
    tags        : str | None   = None   # CSV string e.g. "python,docker,aws"
    job_type    : str | None   = None   # "full_time" | "internship" | "contract" | "part_time"
    score       : float | None = None   # 0.0–1.0
    flags       : str | None   = None   # stringified keyword flags dict

    class Config:
        from_attributes = True
