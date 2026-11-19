
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.worker as worker
from app.database import engine
from app.models import Job


def test_double_claim(monkeypatch):
    test_engine = create_engine(
        engine.url.set(database="soup_test_db")
    )
    TestSession = sessionmaker(bind=test_engine)

    monkeypatch.setattr(worker, "SessionLocal", TestSession)

    job_id = None

    try:
        with TestSession.begin() as db:
            job = Job(
                idempotency_key=f"double-claim-{uuid.uuid4()}",
                payload={"test": "double_claim"}
            )
            db.add(job)
            db.flush()
            job_id = job.id

        barrier = Barrier(2)

        def attempt_claim(worker_id):
            barrier.wait()
            return worker.claim_job(worker_id)

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(attempt_claim, "worker-A")
            second = executor.submit(attempt_claim, "worker-B")

            results = [first.result(), second.result()]

        assert results.count(job_id) == 1
        assert results.count(None) == 1

        with TestSession() as db:
            job = db.get(Job, job_id)
            assert job.status == "running"
            assert job.attempt_count == 1
            assert job.fencing_token == 1

    finally:
        if job_id is not None:
            with TestSession.begin() as db:
                db.query(Job).filter(Job.id == job_id).delete()
        test_engine.dispose()

def test_zombie_worker(monkeypatch):
    from sqlalchemy import text

    test_engine = create_engine(
        engine.url.set(database="soup_test_db")
    )
    TestSession = sessionmaker(bind=test_engine)

    monkeypatch.setattr(worker, "SessionLocal", TestSession)

    job_id = None

    try:
        with TestSession.begin() as db:
            job = Job(
                idempotency_key=f"zombie-{uuid.uuid4()}",
                payload={"test": "zombie_worker"}
            )
            db.add(job)
            db.flush()
            job_id = job.id

        assert worker.claim_job("worker-A") == job_id

        with TestSession.begin() as db:
            db.execute(
                text("""
                    UPDATE jobs
                    SET lease_until = clock_timestamp() - INTERVAL '1 second'
                    WHERE id = :job_id
                """),
                {"job_id": job_id}
            )

        assert worker.claim_job("worker-B") == job_id

        assert worker.complete_job(job_id, "worker-A", 1) is False
        assert worker.complete_job(job_id, "worker-B", 2) is True

        with TestSession() as db:
            job = db.get(Job, job_id)
            assert job.status == "succeeded"
            assert job.attempt_count == 2
            assert job.fencing_token == 2

    
    finally:
        if job_id is not None:
            with TestSession.begin() as db:
                db.execute(
                    text("DELETE FROM job_effects WHERE job_id = :job_id"),
                    {"job_id": job_id}
                )
                db.query(Job).filter(Job.id == job_id).delete()

        test_engine.dispose()

def test_cancel_complete_race(monkeypatch):
    from app.main import cancel_job
    from app.models import JobEffect

    test_engine = create_engine(
        engine.url.set(database="soup_test_db")
    )
    TestSession = sessionmaker(bind=test_engine)

    monkeypatch.setattr(worker, "SessionLocal", TestSession)

    job_id = None

    try:
        with TestSession.begin() as db:
            job = Job(
                idempotency_key=f"cancel-race-{uuid.uuid4()}",
                payload={"test": "cancel_complete_race"}
            )
            db.add(job)
            db.flush()
            job_id = job.id

        assert worker.claim_job("worker-A") == job_id

        barrier = Barrier(2)

        def complete():
            barrier.wait()
            return worker.complete_job(job_id, "worker-A", 1)

        def cancel():
            barrier.wait()
            with TestSession() as db:
                return cancel_job(job_id, db)

        with ThreadPoolExecutor(max_workers=2) as executor:
            completion = executor.submit(complete)
            cancellation = executor.submit(cancel)
            completed = completion.result()
            cancellation.result()

        with TestSession() as db:
            job = db.get(Job, job_id)
            effects = db.query(JobEffect).filter(
                JobEffect.job_id == job_id
            ).count()

            assert job.status in ("succeeded", "cancelled")

            if job.status == "succeeded":
                assert completed is True
                assert effects == 1
            else:
                assert completed is False
                assert effects == 0

    finally:
        if job_id is not None:
            with TestSession.begin() as db:
                db.query(JobEffect).filter(
                    JobEffect.job_id == job_id
                ).delete()
                db.query(Job).filter(Job.id == job_id).delete()

        test_engine.dispose()

def test_transaction_isolation():
    from sqlalchemy import select

    test_engine = create_engine(
        engine.url.set(database="soup_test_db")
    )
    TestSession = sessionmaker(bind=test_engine)

    job_id = None

    try:
        with TestSession.begin() as db:
            job = Job(
                idempotency_key=f"isolation-{uuid.uuid4()}",
                payload={"test": "isolation"}
            )
            db.add(job)
            db.flush()
            job_id = job.id

        with TestSession() as first, TestSession() as second:
            first.begin()
            second.begin()

            locked_job = first.execute(
                select(Job)
                .where(Job.id == job_id)
                .with_for_update()
            ).scalar_one()

            locked_job.status = "running"
            first.flush()

            skipped_job = second.execute(
                select(Job)
                .where(Job.id == job_id)
                .with_for_update(skip_locked=True)
            ).scalar_one_or_none()

            assert skipped_job is None

            second.rollback()
            first.commit()

        with TestSession() as db:
            job = db.get(Job, job_id)
            assert job.status == "running"

    finally:
        if job_id is not None:
            with TestSession.begin() as db:
                db.query(Job).filter(Job.id == job_id).delete()

        test_engine.dispose()

def test_clock_skew(monkeypatch):
    from datetime import datetime, timezone
    from app.models import JobEffect

    test_engine = create_engine(
        engine.url.set(database="soup_test_db")
    )
    TestSession = sessionmaker(bind=test_engine)
    monkeypatch.setattr(worker, "SessionLocal", TestSession)

    job_id = None

    try:
        with TestSession.begin() as db:
            job = Job(
                idempotency_key=f"clock-skew-{uuid.uuid4()}",
                payload={"test": "clock_skew"}
            )
            db.add(job)
            db.flush()
            job_id = job.id

        assert worker.claim_job("worker-A") == job_id

        with TestSession() as db:
            job = db.get(Job, job_id)
            token = job.fencing_token

        class WrongClock:
            @staticmethod
            def now(tz=None):
                return datetime(2099, 1, 1, tzinfo=timezone.utc)

        monkeypatch.setattr(worker, "datetime", WrongClock)

        assert worker.complete_job(job_id, "worker-A", token) is True

        with TestSession() as db:
            job = db.get(Job, job_id)
            assert job.status == "succeeded"
            assert db.query(JobEffect).filter(
                JobEffect.job_id == job_id
            ).count() == 1

    finally:
        if job_id is not None:
            with TestSession.begin() as db:
                db.query(JobEffect).filter(
                    JobEffect.job_id == job_id
                ).delete()
                db.query(Job).filter(Job.id == job_id).delete()

        test_engine.dispose()

