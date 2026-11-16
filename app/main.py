
import uuid

from fastapi import FastAPI, Depends, HTTPException
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
