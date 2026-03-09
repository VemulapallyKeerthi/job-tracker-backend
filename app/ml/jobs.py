"""
app/ml/jobs.py — Local NLP-based job description analyzer

Features:
  - Skill tag extraction       (curated tech skill list + spaCy NLP)
  - Keyword flagging           (visa sponsorship, remote, clearance, etc.)
  - Job type classification    (full-time, part-time, internship, contract)

Dependencies:
  pip install spacy
  python -m spacy download en_core_web_sm
"""

import re
import spacy
from functools import lru_cache

# ── Lazy-load spaCy model (only once per process) ─────────────────────────────
@lru_cache(maxsize=1)
def _get_nlp():
    try:
        return spacy.load("en_core_web_sm")
    except OSError:
        raise RuntimeError(
            "spaCy model not found. Run: python -m spacy download en_core_web_sm"
        )


# ── Skill taxonomy ────────────────────────────────────────────────────────────
SKILLS = {
    # Languages
    "python", "r", "sql", "java", "scala", "julia", "c++", "c#", "go",
    "rust", "javascript", "typescript", "bash", "shell",

    # ML / AI
    "machine learning", "deep learning", "nlp", "natural language processing",
    "computer vision", "reinforcement learning", "llm", "generative ai",
    "neural network", "transformers", "bert", "gpt",

    # ML Frameworks
    "tensorflow", "pytorch", "keras", "scikit-learn", "sklearn", "xgboost",
    "lightgbm", "catboost", "hugging face", "langchain", "openai",

    # Data / Analytics
    "pandas", "numpy", "scipy", "matplotlib", "seaborn", "plotly",
    "tableau", "power bi", "looker", "dbt", "airflow", "spark", "hadoop",
    "kafka", "flink", "dask",

    # Databases
    "postgresql", "postgres", "mysql", "mongodb", "redis", "elasticsearch",
    "snowflake", "bigquery", "redshift", "databricks", "pinecone", "weaviate",

    # Backend / APIs
    "fastapi", "django", "flask", "rest api", "graphql", "grpc",
    "celery", "rabbitmq",

    # Cloud / DevOps
    "aws", "gcp", "azure", "docker", "kubernetes", "terraform", "ci/cd",
    "github actions", "mlflow", "kubeflow", "sagemaker", "vertex ai",

    # Frontend
    "react", "next.js", "vue", "angular", "html", "css", "tailwind",

    # Other
    "git", "linux", "agile", "scrum", "jira",
    "a/b testing", "statistics", "probability", "linear algebra",
}


# ── Keyword flag patterns ─────────────────────────────────────────────────────
FLAG_PATTERNS: dict[str, list[str]] = {
    "visa_sponsorship": [
        r"visa sponsorship",
        r"will sponsor",
        r"sponsorship available",
        r"h[\-\s]?1b",
        r"opt\b",
        r"cpt\b",
        r"work authorization",
        r"authorized to work",
    ],
    "no_sponsorship": [
        r"no visa",
        r"not sponsor",
        r"sponsorship not available",
        r"must be (a )?(us |u\.s\. )?(citizen|resident|national)",
        r"security clearance required",
        r"us citizenship required",
    ],
    "remote": [
        r"\bremote\b",
        r"work from home",
        r"wfh",
        r"fully remote",
        r"remote[-\s]?first",
    ],
    "hybrid": [
        r"\bhybrid\b",
        r"hybrid model",
        r"partially remote",
        r"in[-\s]?office (2|3|two|three) days",
    ],
    "on_site": [
        r"\bon[-\s]?site\b",
        r"in[-\s]?office",
        r"on[-\s]?location",
    ],
    "clearance_required": [
        r"security clearance",
        r"secret clearance",
        r"top secret",
        r"ts/sci",
        r"dod clearance",
    ],
    "urgent_hiring": [
        r"immediate(ly)?( available)?",
        r"urgent(ly)?",
        r"asap",
        r"start(ing)? immediately",
    ],
}

# ── Job type patterns ─────────────────────────────────────────────────────────
JOB_TYPE_PATTERNS: dict[str, list[str]] = {
    "internship": [
        r"\bintern(ship)?\b",
        r"co[-\s]?op\b",
        r"summer (position|role|opportunity|program)",
        r"student (position|role)",
    ],
    "contract": [
        r"\bcontract\b",
        r"\bcontractor\b",
        r"\bfreelance\b",
        r"\bc2c\b",
        r"contract[-\s]?to[-\s]?hire",
        r"\bw2\b",
        r"1099",
        r"temporary position",
    ],
    "part_time": [
        r"part[-\s]?time",
        r"\bpartial\b",
        r"(\d+)[-\s]?(hours?|hrs?) (per|a) week",
    ],
    "full_time": [
        r"full[-\s]?time",
        r"\bpermanent\b",
        r"direct hire",
        r"regular employee",
    ],
}


# ── Core analyzer ─────────────────────────────────────────────────────────────
def analyze_job_description(text: str) -> dict:
    """
    Analyze a job description and return:
      - tags:      list of detected tech skills
      - flags:     dict of boolean keyword signals
      - job_type:  classified job type string
      - score:     simple relevance score (0.0–1.0) based on skill density
    """
    if not text or not text.strip():
        return {
            "tags": [],
            "flags": {},
            "job_type": "unknown",
            "score": 0.0,
        }

    normalized = text.lower()

    # ── 1. Skill extraction ───────────────────────────────────────────────────
    nlp = _get_nlp()
    doc = nlp(normalized)

    # Match multi-word skills first, then single tokens
    extracted_skills = set()
    for skill in SKILLS:
        if " " in skill:
            if skill in normalized:
                extracted_skills.add(skill)
        else:
            for token in doc:
                if token.text == skill and not token.is_stop:
                    extracted_skills.add(skill)

    tags = sorted(extracted_skills)

    # ── 2. Keyword flagging ───────────────────────────────────────────────────
    flags: dict[str, bool] = {}
    for flag_name, patterns in FLAG_PATTERNS.items():
        flags[flag_name] = any(
            re.search(p, normalized, re.IGNORECASE) for p in patterns
        )

    # ── 3. Job type classification ────────────────────────────────────────────
    job_type = "full_time"   # default assumption
    for jtype, patterns in JOB_TYPE_PATTERNS.items():
        if any(re.search(p, normalized, re.IGNORECASE) for p in patterns):
            job_type = jtype
            break   # first match wins (internship > contract > part_time > full_time)

    # ── 4. Relevance score ────────────────────────────────────────────────────
    # Simple heuristic: ratio of matched skills to total words (capped at 1.0)
    word_count = max(len(normalized.split()), 1)
    raw_score  = len(tags) / (word_count ** 0.5)     # sqrt dampens long descriptions
    score      = round(min(raw_score, 1.0), 4)

    return {
        "tags":     tags,
        "flags":    flags,
        "job_type": job_type,
        "score":    score,
    }
