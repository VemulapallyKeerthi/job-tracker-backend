from app.database import SessionLocal
from app.models.job import Job

db = SessionLocal()

job = Job(
    title="Software Engineer",
    company="Microsoft",
    location="Remote",
    posted_date=None,
    description="Build backend systems",
    apply_link="https://careers.microsoft.com"
)

db.add(job)
db.commit()
db.close()