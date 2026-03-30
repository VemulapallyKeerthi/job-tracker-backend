from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
import jwt
from jwt import PyJWKClient
import os

from app.database import SessionLocal
from app.models.job import Job
from app.schemas.job import JobBase, JobResponse, JobStatus
from app.ml.jobs import analyze_job_description

router = APIRouter(prefix="/jobs", tags=["Jobs"])

SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")
SUPABASE_URL        = os.getenv("SUPABASE_URL")


# ── DB dependency ─────────────────────────────────────────────────────────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Auth dependency ───────────────────────────────────────────────────────────
def get_current_user(authorization: Optional[str] = Header(None)) -> Optional[str]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ")[1]

    # Try JWKS first
    try:
        jwks_url = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        jwks_client = PyJWKClient(jwks_url)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            options={"verify_aud": False},
        )
        user_id = payload.get("sub")
        print(f"✅ JWKS auth success: {user_id}", flush=True)
        return user_id
    except Exception as e:
        print(f"❌ JWKS auth failed: {e}", flush=True)

    # Fallback to HS256
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        user_id = payload.get("sub")
        print(f"✅ HS256 auth success: {user_id}", flush=True)
        return user_id
    except Exception as e:
        print(f"❌ HS256 auth failed: {e}", flush=True)
        return None


def require_user(user_id: Optional[str] = Depends(get_current_user)) -> str:
    """Raise 401 if user is not authenticated."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


# ── GET /jobs ─────────────────────────────────────────────────────────────────
@router.get("/", response_model=list[JobResponse])
def get_jobs(
    status           : str | None  = None,
    company          : str | None  = None,
    location         : str | None  = None,
    title            : str | None  = None,
    source           : str | None  = None,
    job_type         : str | None  = None,
    visa_sponsorship : bool | None = None,
    db               : Session = Depends(get_db),
    user_id          : Optional[str] = Depends(get_current_user),
):
    query = db.query(Job)

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
        query = query.filter(Job.flags.ilike("%'visa_sponsorship': True%"))
    if visa_sponsorship is False:
        query = query.filter(Job.flags.ilike("%'no_sponsorship': True%"))

    jobs = query.all()

    # If user is authenticated, overlay their personal status from user_jobs
    if user_id:
        result = db.execute(
            text("SELECT job_id, status FROM user_jobs WHERE user_id = :uid"),
            {"uid": user_id}
        ).fetchall()
        user_statuses = {row.job_id: row.status for row in result}

        jobs_with_status = []
        for job in jobs:
            job_dict = {
                "id":          job.id,
                "title":       job.title,
                "company":     job.company,
                "location":    job.location,
                "posted_date": job.posted_date,
                "description": job.description,
                "apply_link":  job.apply_link,
                "source":      job.source,
                "status":      user_statuses.get(job.id, "saved"),
                "tags":        job.tags,
                "job_type":    job.job_type,
                "score":       job.score,
                "flags":       job.flags,
            }
            jobs_with_status.append(job_dict)

        if status:
            jobs_with_status = [j for j in jobs_with_status if j["status"] == status]

        return jobs_with_status

    # No auth — filter by status on job table directly
    if status:
        query = query.filter(Job.status == status)

    return jobs


# ── GET /jobs/debug/auth ──────────────────────────────────────────────────────
@router.get("/debug/auth")
def debug_auth(
    user_id       : Optional[str] = Depends(get_current_user),
    authorization : Optional[str] = Header(None),
):
    return {
        "user_id":        user_id,
        "has_token":      authorization is not None,
        "token_prefix":   authorization[:30] if authorization else None,
        "jwt_secret_set": SUPABASE_JWT_SECRET is not None,
        "supabase_url":   SUPABASE_URL,
    }


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

    if data.get("description"):
        analysis         = analyze_job_description(data["description"])
        data["tags"]     = ",".join(analysis["tags"])
        data["job_type"] = analysis["job_type"]
        data["score"]    = analysis["score"]
        data["flags"]    = str(analysis["flags"])

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
def update_job_status(
    job_id  : int,
    status  : JobStatus,
    db      : Session = Depends(get_db),
    user_id : Optional[str] = Depends(get_current_user),
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if user_id:
        db.execute(
            text("""
                INSERT INTO user_jobs (user_id, job_id, status)
                VALUES (:uid, :jid, :status)
                ON CONFLICT (user_id, job_id)
                DO UPDATE SET status = :status
            """),
            {"uid": user_id, "jid": job_id, "status": status.value}
        )
        db.commit()
    else:
        job.status = status
        db.commit()
        db.refresh(job)

    return job


# ── GET /jobs/{job_id}/analysis ───────────────────────────────────────────────
@router.get("/{job_id}/analysis")
def get_job_analysis(job_id: int, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.description:
        raise HTTPException(status_code=422, detail="Job has no description to analyze")
    return analyze_job_description(job.description)


# ── Status transition helpers ─────────────────────────────────────────────────
def _transition(job_id: int, new_status: JobStatus, db: Session, user_id: Optional[str]):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if user_id:
        db.execute(
            text("""
                INSERT INTO user_jobs (user_id, job_id, status)
                VALUES (:uid, :jid, :status)
                ON CONFLICT (user_id, job_id)
                DO UPDATE SET status = :status
            """),
            {"uid": user_id, "jid": job_id, "status": new_status.value}
        )
        db.commit()
    else:
        job.status = new_status
        db.commit()
        db.refresh(job)

    return job


@router.post("/{job_id}/apply", response_model=JobResponse)
def mark_as_applied(
    job_id  : int,
    db      : Session = Depends(get_db),
    user_id : Optional[str] = Depends(get_current_user),
):
    return _transition(job_id, JobStatus.applied, db, user_id)


@router.post("/{job_id}/interview", response_model=JobResponse)
def mark_as_interviewing(
    job_id  : int,
    db      : Session = Depends(get_db),
    user_id : Optional[str] = Depends(get_current_user),
):
    return _transition(job_id, JobStatus.interview, db, user_id)


@router.post("/{job_id}/offer", response_model=JobResponse)
def mark_as_offer(
    job_id  : int,
    db      : Session = Depends(get_db),
    user_id : Optional[str] = Depends(get_current_user),
):
    return _transition(job_id, JobStatus.offer, db, user_id)


@router.post("/{job_id}/reject", response_model=JobResponse)
def mark_as_rejected(
    job_id  : int,
    db      : Session = Depends(get_db),
    user_id : Optional[str] = Depends(get_current_user),
):
    return _transition(job_id, JobStatus.rejected, db, user_id)