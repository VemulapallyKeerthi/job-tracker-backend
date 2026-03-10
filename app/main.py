import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.routers import jobs
from app.database import engine
from app.models import job

log = logging.getLogger(__name__)

# ── Scheduler setup ───────────────────────────────────────────────────────────
scheduler = BackgroundScheduler()

def run_scraper():
    """Run the combined scraper — called daily by the scheduler."""
    try:
        log.info("⏰ Scheduled scraper starting...")
        from scrapers.scraper import run_all
        run_all()
        log.info("✅ Scheduled scraper completed")
    except Exception as e:
        log.error(f"❌ Scheduled scraper failed: {e}")


# ── App lifespan (startup / shutdown) ─────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──
    # Schedule scraper to run daily at 8:00 AM UTC
    # Override via SCRAPER_HOUR / SCRAPER_MINUTE env vars if needed
    hour   = int(os.getenv("SCRAPER_HOUR", "8"))
    minute = int(os.getenv("SCRAPER_MINUTE", "0"))

    scheduler.add_job(
        run_scraper,
        trigger=CronTrigger(hour=hour, minute=minute),
        id="daily_scraper",
        name="Daily job scraper",
        replace_existing=True,
    )
    scheduler.start()
    log.info(f"📅 Scraper scheduled daily at {hour:02d}:{minute:02d} UTC")

    yield  # app runs here

    # ── Shutdown ──
    scheduler.shutdown(wait=False)
    log.info("🛑 Scheduler shut down")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Job Tracker API",
    description="Scrapes, stores, and analyzes tech job listings",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
allowed_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"message": "Job Tracker API is running"}

@app.head("/")
def root_head():
    return {}

@app.post("/scrape", tags=["Scraper"])
def trigger_scrape_manually(background_tasks: BackgroundTasks):
    """Manually trigger the scraper in background — returns immediately."""
    background_tasks.add_task(run_scraper)
    return {"message": "Scraper started in background"}

@app.get("/scraper/status", tags=["Scraper"])
def scraper_status():
    """Check when the scraper last ran and when it runs next."""
    job_info = scheduler.get_job("daily_scraper")
    if not job_info:
        return {"status": "not scheduled"}
    return {
        "status": "scheduled",
        "next_run": str(job_info.next_run_time),
        "name": job_info.name,
    }

# Routers
app.include_router(jobs.router)

# Auto-create all tables
job.Base.metadata.create_all(bind=engine)