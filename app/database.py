import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# ── Connection URL ─────────────────────────────────────────────────────────────
# Local dev:   set nothing → uses SQLite
# Production:  set DATABASE_URL to your Supabase connection string
#
# Where to find it in Supabase:
#   Project → Settings → Database → Connection string → URI
#   Format: postgresql://postgres:[PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres
#
# IMPORTANT: Supabase requires SSL — we enforce it via connect_args

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./jobs.db")

if DATABASE_URL.startswith("sqlite"):
    # SQLite — local dev only
    connect_args = {"check_same_thread": False}
    engine = create_engine(DATABASE_URL, connect_args=connect_args)
else:
    # PostgreSQL (Supabase) — enforce SSL
    connect_args = {"sslmode": "require"}
    engine = create_engine(
        DATABASE_URL,
        connect_args=connect_args,
        pool_size=5,           # Supabase free tier has connection limits
        max_overflow=10,
        pool_pre_ping=True,    # auto-reconnect if connection drops
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()