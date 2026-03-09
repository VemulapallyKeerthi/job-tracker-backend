from sqlalchemy import Column, Integer, String, Date, Float
from app.database import Base

class Job(Base):
    __tablename__ = "jobs"

    id          = Column(Integer, primary_key=True, index=True)
    title       = Column(String, nullable=False)
    company     = Column(String, nullable=False)
    location    = Column(String)
    posted_date = Column(Date)
    description = Column(String)
    apply_link  = Column(String)
    source      = Column(String)          # e.g. "indeed", "linkedin"
    status      = Column(String, default="saved")

    # ── ML-derived fields (auto-populated on ingest) ──────────────────────────
    tags        = Column(String)          # CSV: "python,fastapi,docker"
    job_type    = Column(String)          # "full_time" | "internship" | "contract" | "part_time"
    score       = Column(Float)           # 0.0–1.0 relevance score
    flags       = Column(String)          # stringified dict of keyword flags
