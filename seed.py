"""
seed.py — Populate the database with sample jobs for local development/testing.

Usage:
    python seed.py
"""

from app.database import SessionLocal, engine
from app.models.job import Job, Base
from app.ml.jobs import analyze_job_description

# Ensure tables exist before seeding
Base.metadata.create_all(bind=engine)

SAMPLE_JOBS = [
    {
        "title": "Software Engineer",
        "company": "Microsoft",
        "location": "Remote",
        "description": (
            "Build and maintain backend systems using Python, FastAPI, and PostgreSQL. "
            "Work with Docker, Kubernetes, and AWS. Experience with CI/CD pipelines required. "
            "Full-time position. Visa sponsorship available."
        ),
        "apply_link": "https://careers.microsoft.com",
        "source": "seed",
        "status": "saved",
    },
    {
        "title": "Data Scientist",
        "company": "Google",
        "location": "New York, NY",
        "description": (
            "Apply machine learning and deep learning to large-scale datasets. "
            "Proficiency in Python, TensorFlow, PyTorch, and SQL required. "
            "Experience with GCP and BigQuery preferred. Full-time, hybrid role. "
            "Must be authorized to work in the US. No visa sponsorship."
        ),
        "apply_link": "https://careers.google.com",
        "source": "seed",
        "status": "applied",
    },
    {
        "title": "ML Engineer Intern",
        "company": "OpenAI",
        "location": "San Francisco, CA",
        "description": (
            "Summer internship on the ML infrastructure team. "
            "Work with Python, PyTorch, and distributed training systems. "
            "Experience with LLMs and Hugging Face a plus. "
            "Internship position, 12 weeks, on-site."
        ),
        "apply_link": "https://openai.com/careers",
        "source": "seed",
        "status": "saved",
    },
    {
        "title": "Backend Engineer",
        "company": "Stripe",
        "location": "Remote",
        "description": (
            "Design and build scalable APIs using Go and Python. "
            "Work with PostgreSQL, Redis, and Kafka. "
            "Fully remote, full-time. Visa sponsorship available for qualified candidates."
        ),
        "apply_link": "https://stripe.com/jobs",
        "source": "seed",
        "status": "interview",
    },
]

def seed():
    db = SessionLocal()
    try:
        existing = db.query(Job).count()
        if existing > 0:
            print(f"Database already has {existing} jobs — skipping seed.")
            return

        for job_data in SAMPLE_JOBS:
            # Auto-analyze description
            if job_data.get("description"):
                analysis            = analyze_job_description(job_data["description"])
                job_data["tags"]    = ",".join(analysis["tags"])
                job_data["job_type"]= analysis["job_type"]
                job_data["score"]   = analysis["score"]
                job_data["flags"]   = str(analysis["flags"])

            job = Job(**job_data)
            db.add(job)
            print(f"  + {job_data['title']} @ {job_data['company']} "
                  f"[{job_data.get('job_type', '?')}] tags={job_data.get('tags', '')}")

        db.commit()
        print(f"\n✓ Seeded {len(SAMPLE_JOBS)} jobs successfully.")

    except Exception as e:
        db.rollback()
        print(f"✗ Seed failed: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed()