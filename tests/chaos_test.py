import threading
import requests
import sys
import uuid
import time
import random
import subprocess
from sqlalchemy import text

from app.database import SessionLocal
from app.models import Job

TOTAL_JOBS = 10_000
WORKERS = 8


def create_jobs():
    batch = str(uuid.uuid4())

    with SessionLocal() as db:
        for i in range(TOTAL_JOBS):
            db.add(Job(
                idempotency_key=f"chaos-{batch}-{i}",
                payload={"batch": batch, "test": "chaos"}
            ))

        db.commit()

    print(f"Created {TOTAL_JOBS} jobs")
    print(f"Batch: {batch}")

    return batch
def start_workers():
    workers = []

    for i in range(WORKERS):
        process = subprocess.Popen(
            [sys.executable, "-u", "-m", "app.worker"],
            stdout=open(f"/tmp/soup-chaos-worker-{i}.log", "w"),
            stderr=subprocess.STDOUT
        )
        workers.append(process)

    print(f"Started {len(workers)} workers")
    return workers

def kill_random_worker(workers):
    alive = [p for p in workers if p.poll() is None]

    if not alive:
        return

    victim = random.choice(alive)
    victim.kill()  # SIGKILL на macOS/Linux
    victim.wait()

    print(f"Killed worker PID={victim.pid}", flush=True)

    replacement = subprocess.Popen(
        [sys.executable, "-u", "-m", "app.worker"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )

    workers.remove(victim)
    workers.append(replacement)

    print(f"Restarted worker PID={replacement.pid}", flush=True)

def run_chaos(duration=60):
    workers = start_workers()

    try:
        start = time.monotonic()

        while time.monotonic() - start < duration:
            time.sleep(2)
            kill_random_worker(workers)

    finally:
        for process in workers:
            if process.poll() is None:
                process.terminate()

        for process in workers:
            process.wait()

        print("All chaos workers stopped", flush=True)

def check_results(batch):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT
                j.status,
                COUNT(*) AS jobs,
                COUNT(e.id) AS effects
            FROM jobs j
            LEFT JOIN job_effects e ON e.job_id = j.id
            WHERE j.payload->>'batch' = :batch
            GROUP BY j.status
            ORDER BY j.status
        """), {"batch": batch}).all()

        print("\n=== CHAOS TEST RESULTS ===")

        for status, jobs, effects in rows:
            print(f"{status}: jobs={jobs}, effects={effects}")

        duplicates = db.execute(text("""
            SELECT COUNT(*)
            FROM (
                SELECT e.job_id
                FROM job_effects e
                JOIN jobs j ON j.id = e.job_id
                WHERE j.payload->>'batch' = :batch
                GROUP BY e.job_id
                HAVING COUNT(*) > 1
            ) AS duplicated
        """), {"batch": batch}).scalar_one()

        print(f"Duplicate effects: {duplicates}")

        total_jobs = sum(jobs for status, jobs, effects in rows)

        assert total_jobs == TOTAL_JOBS, (
            f"Expected {TOTAL_JOBS} jobs, got {total_jobs}"
        )

        assert duplicates == 0, (
            f"Found {duplicates} duplicate effects"
        )

        for status, jobs, effects in rows:
            assert status in ("succeeded", "cancelled"), (
                f"Unexpected status: {status}, jobs={jobs}"
            )

            if status == "succeeded":
                assert effects == jobs, (
                    f"Succeeded jobs={jobs}, effects={effects}"
                )

            if status == "cancelled":
                assert effects == 0, (
                    f"Cancelled jobs have {effects} effects"
                )

        print("Final state invariants: PASS", flush=True)
def recover_jobs(batch):
    print("Recovering unfinished jobs...", flush=True)

    workers = start_workers()
    deadline = time.monotonic() + 120

    try:
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError("Recovery exceeded 120 seconds")

            with SessionLocal() as db:
                remaining = db.query(Job).filter(
                    Job.payload["batch"].astext == batch,
                    Job.status.in_(["queued", "running"])
                ).count()

            print(f"Remaining jobs: {remaining}", flush=True)

            if remaining == 0:
                break

            time.sleep(2)

    finally:
        for process in workers:
            if process.poll() is None:
                process.terminate()

        for process in workers:
            process.wait()

        print("Recovery workers stopped", flush=True)

def api_chaos(batch):
    key = f"retry-{uuid.uuid4()}"
    all_job_ids = []
    def send_requests():
        job_ids = []

        for _ in range(20):
            response = requests.post(
                "http://127.0.0.1:8001/jobs",
                json={
                    "idempotency_key": key,
                    "payload": {"test": "retry"}
                },
                timeout=5
            )

            assert response.status_code == 201, (
                f"POST failed: {response.status_code}"
            )

            job_ids.append(response.json()["id"])
            all_job_ids.append(response.json()["id"])

        assert len(set(job_ids)) == 1, (
            f"Idempotency failed: {len(set(job_ids))} different IDs"
        )

        print("POST idempotency: PASS", flush=True)
    def cancel_jobs():
        with SessionLocal() as db:
            ids = [
                job.id for job in db.query(Job.id)
                .filter(
                    Job.payload["batch"].astext == batch,
                    Job.status.in_(["queued", "running"])
                )
                .limit(100)
            ]

        for job_id in ids:
            response = requests.post(
                f"http://127.0.0.1:8001/jobs/{job_id}/cancel",
                timeout=5
            )

            assert response.status_code == 200, (
                f"CANCEL failed: {response.status_code}"
            )

            print(f"CANCEL: {response.status_code}", flush=True)

    errors = []

    def run_checked(fn):
        try:
            fn()
        except Exception as e:
            errors.append(e)

    threads = [
        threading.Thread(target=run_checked, args=(send_requests,)),
        threading.Thread(target=run_checked, args=(send_requests,)),
        threading.Thread(target=run_checked, args=(cancel_jobs,))
    ]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    if errors:
        raise RuntimeError(f"API chaos failed: {errors}")
    assert len(all_job_ids) == 40, (
        f"Expected 40 responses, got {len(all_job_ids)}"
    )

    assert len(set(all_job_ids)) == 1, (
        "Concurrent idempotency failed: different Job IDs"
    )

    print("Concurrent idempotency: PASS", flush=True)

    print("API chaos: PASS", flush=True)


if __name__ == "__main__":
    batch = create_jobs()

    print("Starting chaos test...", flush=True)
    print(f"Batch: {batch}", flush=True)

    api_errors = []

    def run_api():
        try:
            api_chaos(batch)
        except Exception as e:
            api_errors.append(e)

    thread = threading.Thread(target=run_api)
    thread.start()

    try:
        run_chaos(duration=60)
    finally:
        thread.join()

    if api_errors:
        raise RuntimeError(f"API chaos failed: {api_errors}")

    recover_jobs(batch)
    check_results(batch)