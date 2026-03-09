from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.job import Job
from app.schemas.job import JobBase, JobResponse, JobStatus
from app.ml.jobs import analyze_job_description

router = APIRouter(prefix="/jobs", tags=["Jobs"])

# ── DB dependency ─────────────────────────────────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── GET /jobs ─────────────────────────────────────────────────────────────────
@router.get("/", response_model=list[JobResponse])
def get_jobs(
    status           : str | None  = None,
    company          : str | None  = None,
    location         : str | None  = None,
    title            : str | None  = None,
    source           : str | None  = None,
    job_type         : str | None  = None,
    visa_sponsorship : bool | None = None,   # True → only jobs with sponsorship
    db               : Session = Depends(get_db),
):
    query = db.query(Job)

    if status:
        query = query.filter(Job.status == status)
    if company:
        query = query.filter(Job.company.ilike(f"%{company}%"))
    if location:
        query = query.filter(Job.location.ilike(f"%{location}%"))
    if title:
        query = query.filter(Job.title.ilike(f"%{title}%"))
    if source:
        query = query.filter(Job.source == source)
    if job_type:
        query = query.filter(Job.job_type == job_type)
    if visa_sponsorship is True:
        # flags is stored as a stringified dict — filter jobs where visa_sponsorship is True
        query = query.filter(Job.flags.ilike("%'visa_sponsorship': True%"))
    if visa_sponsorship is False:
        query = query.filter(Job.flags.ilike("%'no_sponsorship': True%"))

    return query.all()


# ── GET /jobs/{job_id} ────────────────────────────────────────────────────────
@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ── POST /jobs ────────────────────────────────────────────────────────────────
@router.post("/", response_model=JobResponse)
def create_job(job: JobBase, db: Session = Depends(get_db)):
    data = job.model_dump(exclude={"url"})

    # Auto-analyze description if present
    if data.get("description"):
        analysis         = analyze_job_description(data["description"])
        data["tags"]     = ",".join(analysis["tags"])   # stored as CSV string
        data["job_type"] = analysis["job_type"]
        data["score"]    = analysis["score"]
        data["flags"]    = str(analysis["flags"])       # stored as string; use JSON col if preferred

    new_job = Job(**data)
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    return new_job


# ── PUT /jobs/{job_id} ────────────────────────────────────────────────────────
@router.put("/{job_id}", response_model=JobResponse)
def update_job(job_id: int, updated_job: JobBase, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    for key, value in updated_job.model_dump(exclude={"url"}).items():
        setattr(job, key, value)

    # Re-analyze if description changed
    if updated_job.description:
        analysis      = analyze_job_description(updated_job.description)
        job.tags      = ",".join(analysis["tags"])
        job.job_type  = analysis["job_type"]
        job.score     = analysis["score"]
        job.flags     = str(analysis["flags"])

    db.commit()
    db.refresh(job)
    return job


# ── DELETE /jobs/{job_id} ─────────────────────────────────────────────────────
@router.delete("/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    db.delete(job)
    db.commit()
    return {"message": "Job deleted successfully"}


# ── PATCH /jobs/{job_id}/status ───────────────────────────────────────────────
@router.patch("/{job_id}/status", response_model=JobResponse)
def update_job_status(job_id: int, status: JobStatus, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = status
    db.commit()
    db.refresh(job)
    return job


# ── GET /jobs/{job_id}/analysis ───────────────────────────────────────────────
@router.get("/{job_id}/analysis")
def get_job_analysis(job_id: int, db: Session = Depends(get_db)):
    """Re-run ML analysis on demand for any job."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.description:
        raise HTTPException(status_code=422, detail="Job has no description to analyze")
    return analyze_job_description(job.description)


# ── Status transition helpers ─────────────────────────────────────────────────
def _transition(job_id: int, new_status: JobStatus, db: Session):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = new_status
    db.commit()
    db.refresh(job)
    return job

@router.post("/{job_id}/apply", response_model=JobResponse)
def mark_as_applied(job_id: int, db: Session = Depends(get_db)):
    return _transition(job_id, JobStatus.applied, db)

@router.post("/{job_id}/interview", response_model=JobResponse)
def mark_as_interviewing(job_id: int, db: Session = Depends(get_db)):
    return _transition(job_id, JobStatus.interview, db)

@router.post("/{job_id}/offer", response_model=JobResponse)
def mark_as_offer(job_id: int, db: Session = Depends(get_db)):
    return _transition(job_id, JobStatus.offer, db)

@router.post("/{job_id}/reject", response_model=JobResponse)
def mark_as_rejected(job_id: int, db: Session = Depends(get_db)):
    return _transition(job_id, JobStatus.rejected, db)


