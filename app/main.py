from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import jobs
from app.database import engine
from app.models import job

app = FastAPI()

# ✅ Add CORS middleware immediately after creating the app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # allow frontend to call backend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"message": "Job Tracker API is running"}

# Routers come AFTER CORS
app.include_router(jobs.router)

# Database setup
job.Base.metadata.create_all(bind=engine)
