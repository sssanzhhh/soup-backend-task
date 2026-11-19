
import os
import uuid
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.main import app
from app.models import Job


load_dotenv()

database_url = make_url(os.environ["DATABASE_URL"])
test_database_url = database_url.set(database="soup_test_db")

assert test_database_url.database == "soup_test_db"

test_engine = create_engine(test_database_url)

TestSessionLocal = sessionmaker(
    bind=test_engine,
    autoflush=False,
    autocommit=False
)


def override_get_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_list_jobs_empty():
    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            response = client.get("/jobs?limit=5&offset=0")

        assert response.status_code == 200
        assert response.json() == {
            "items": [],
            "limit": 5,
            "offset": 0
        }

    finally:
        app.dependency_overrides.pop(get_db, None)


def test_list_jobs_pagination():
    db = TestSessionLocal()
    job_ids = []

    try:
        base_time = datetime.now(timezone.utc)

        for i in range(3):
            job = Job(
                idempotency_key=f"pagination-test-{uuid.uuid4()}",
                payload={"task": f"task_{i}"},
                created_at=base_time + timedelta(seconds=i)
            )
            db.add(job)
            db.flush()
            job_ids.append(str(job.id))

        db.commit()

        app.dependency_overrides[get_db] = override_get_db

        with TestClient(app) as client:
            response = client.get("/jobs?limit=2&offset=1")

        assert response.status_code == 200

        data = response.json()
        assert [item["id"] for item in data["items"]] == job_ids[1:3]
        assert data["limit"] == 2
        assert data["offset"] == 1

    finally:
        app.dependency_overrides.pop(get_db, None)
        db.rollback()

        if job_ids:
            db.query(Job).filter(
                Job.id.in_(job_ids)
            ).delete(synchronize_session=False)
            db.commit()

        db.close()
