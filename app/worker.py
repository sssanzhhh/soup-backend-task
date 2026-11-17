from sqlalchemy import or_, func
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Job


LEASE_SECONDS = 30


def claim_job(worker_id: str):
    with SessionLocal() as db:
        with db.begin():
            job = db.execute(
                select(Job)
                .where(
                    or_(
                        Job.status == "queued",
                        (Job.status == "running") &
                        (Job.lease_until < func.clock_timestamp())
                    )
                )
                .order_by(Job.created_at, Job.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            ).scalar_one_or_none()

            if job is None:
                return None

            job.status = "running"
            job.worker_id = worker_id
            job.lease_until = func.clock_timestamp() + timedelta(seconds=LEASE_SECONDS)
            job.attempt_count += 1
            job.fencing_token += 1

            db.flush()

            return job.id

def complete_job(job_id, worker_id: str, fencing_token: int):
    from app.models import JobEffect

    with SessionLocal() as db:
        with db.begin():
            job = db.execute(
                select(Job)
                .where(Job.id == job_id)
                .with_for_update()
            ).scalar_one_or_none()

            if job is None:
                return False

            if (
                job.status != "running"
                or job.worker_id != worker_id
                or job.fencing_token != fencing_token
                or job.lease_until <= db.execute(select(func.clock_timestamp())).scalar_one()
            ):
                return False

            db.add(JobEffect(
                job_id=job.id,
                worker_id=worker_id,
                fencing_token=fencing_token
            ))

            job.status = "succeeded"
            job.lease_until = None
            job.worker_id = None
            job.updated_at = func.now()

    return True

def run_worker():
    import time

    worker_id = str(uuid.uuid4())

    print(f"Worker {worker_id} started", flush=True)

    while True:
        job_id = claim_job(worker_id)

        if job_id is None:
            time.sleep(1)
            continue

        with SessionLocal() as db:
            job = db.get(Job, job_id)
            token = job.fencing_token

        result = complete_job(job_id, worker_id, token)

        print(
            f"Worker {worker_id}: "
            f"job={job_id}, completed={result}",
            flush=True
        )


if __name__ == "__main__":
    run_worker()
