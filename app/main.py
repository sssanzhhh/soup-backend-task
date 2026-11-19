
import uuid

from fastapi import FastAPI, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Job

app = FastAPI(title="Soup Backend Task")


class JobCreate(BaseModel):
    idempotency_key: str = Field(min_length=1)
    payload: dict = Field(default_factory=dict)


@app.post("/jobs", status_code=201)
def create_job(data: JobCreate, db: Session = Depends(get_db)):
    job = Job(
        id=uuid.uuid4(),
        idempotency_key=data.idempotency_key,
        payload=data.payload,
        status="queued"
    )

    db.add(job)

    try:
        db.commit()
        db.refresh(job)
    except IntegrityError:
        db.rollback()

        existing_job = db.query(Job).filter(
            Job.idempotency_key == data.idempotency_key
        ).first()

        if existing_job is None:
            raise HTTPException(
                status_code=409,
                detail="Database conflict"
            )

        if existing_job.payload != data.payload:
            raise HTTPException(
                status_code=409,
                detail="Idempotency key already used with different payload"
            )

        return {
            "id": str(existing_job.id),
            "status": existing_job.status,
            "message": "Job already exists"
        }

    return {
        "id": str(job.id),
        "status": job.status,
        "message": "Job created"
    }

@app.get("/jobs/{job_id}")
def get_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )

    return {
        "id": str(job.id),
        "status": job.status,
        "payload": job.payload,
        "attempt_count": job.attempt_count
    }


@app.get("/jobs")
def list_jobs(
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db)
):
    jobs = (
        db.query(Job)
        .order_by(Job.created_at.asc(), Job.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "items": [
            {
                "id": str(job.id),
                "status": job.status,
                "payload": job.payload,
                "attempt_count": job.attempt_count
            }
            for job in jobs
        ],
        "limit": limit,
        "offset": offset
    }

@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: uuid.UUID, db: Session = Depends(get_db)):
    with db.begin():
        job = (
            db.query(Job)
            .filter(Job.id == job_id)
            .with_for_update()
            .first()
        )

        if job is None:
            raise HTTPException(
                status_code=404,
                detail="Job not found"
            )

        if job.status in ("queued", "running"):
            job.status = "cancelled"
            job.worker_id = None
            job.lease_until = None

        return {
            "id": str(job.id),
            "status": job.status
        }
