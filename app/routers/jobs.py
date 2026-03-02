from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.job import Job
from app.schemas.job import JobBase, JobResponse, JobStatus

router = APIRouter(prefix="/jobs", tags=["Jobs"])

# Database session dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# GET /jobs → return all jobs
@router.get("/", response_model=list[JobResponse])
def get_jobs(
    status: str | None = None,
    company: str | None = None,
    location: str | None = None,
    title: str | None = None,
    db: Session = Depends(get_db)
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

    return query.all()

# POST /jobs → create a new job
@router.post("/", response_model=JobResponse)
def create_job(job: JobBase, db: Session = Depends(get_db)):
    new_job = Job(**job.dict())
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    return new_job

from fastapi import HTTPException

# UPDATE /jobs/{id}
@router.put("/{job_id}", response_model=JobResponse)
def update_job(job_id: int, updated_job: JobBase, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    for key, value in updated_job.dict().items():
        setattr(job, key, value)

    db.commit()
    db.refresh(job)
    return job


# DELETE /jobs/{id}
@router.delete("/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    db.delete(job)
    db.commit()
    return {"message": "Job deleted successfully"}

@router.patch("/{job_id}/status", response_model=JobResponse)
def update_job_status(job_id: int, status: JobStatus, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.status = status
    db.commit()
    db.refresh(job)
    return job

# Move job to "applied"
@router.post("/{job_id}/apply", response_model=JobResponse)
def mark_as_applied(job_id: int, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = JobStatus.applied
    db.commit()
    db.refresh(job)
    return job


# Move job to "interviewing"
@router.post("/{job_id}/interview", response_model=JobResponse)
def mark_as_interviewing(job_id: int, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = JobStatus.interviewing
    db.commit()
    db.refresh(job)
    return job


# Move job to "offer"
@router.post("/{job_id}/offer", response_model=JobResponse)
def mark_as_offer(job_id: int, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = JobStatus.offer
    db.commit()
    db.refresh(job)
    return job


# Move job to "rejected"
@router.post("/{job_id}/reject", response_model=JobResponse)
def mark_as_rejected(job_id: int, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    job.status = JobStatus.rejected
    db.commit()
    db.refresh(job)
    return job