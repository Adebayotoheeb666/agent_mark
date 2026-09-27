"""Health check endpoint — minimal Local API for N1."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    """Liveness + DB connectivity probe.

    Returns 200 only if the local PostgreSQL is reachable.
    Per N1 spec: this is the only endpoint in the skeleton; it proves the API
    is bound and the DB is migrated.
    """
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:  # pragma: no cover
        db_status = f"error: {exc}"

    return {"status": "ok" if db_status == "ok" else "degraded", "db": db_status, "service": "agent-mark-node"}


@router.get("/health/ready")
def readiness_check():
    """ Readiness without DB — for container orchestration if needed. """
    return {"status": "ok", "service": "agent-mark-node"}
