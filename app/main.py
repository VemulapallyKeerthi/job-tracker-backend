from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import jobs
from app.database import engine
from app.models import job

app = FastAPI(
    title="Job Tracker API",
    description="Scrapes, stores, and analyzes tech job listings",
    version="1.0.0",
)

# CORS — restrict origins in production via env var
import os
allowed_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"message": "Job Tracker API is running"}

@app.head("/")
def root_head():
    return {}

# Routers
app.include_router(jobs.router)

# Auto-create all tables (including new ML columns)
job.Base.metadata.create_all(bind=engine)

