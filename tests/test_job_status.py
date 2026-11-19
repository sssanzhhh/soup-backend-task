from app.models import Job
import uuid
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db


def test_get_job_not_found():
    fake_db = MagicMock()
    fake_db.get.return_value = None

    def override_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            response = client.get(f"/jobs/{uuid.uuid4()}")

        assert response.status_code == 404
        assert response.json() == {"detail": "Job not found"}
    finally:
        app.dependency_overrides.pop(get_db, None)
def test_get_job_invalid_uuid():
    with TestClient(app) as client:
        response = client.get("/jobs/not-a-valid-uuid")

    assert response.status_code == 422
def test_get_job_success():
    job_id = uuid.uuid4()

    fake_job = MagicMock()
    fake_job.id = job_id
    fake_job.status = "queued"
    fake_job.payload = {"task": "train_model"}
    fake_job.attempt_count = 0

    fake_db = MagicMock()
    fake_db.get.return_value = fake_job

    def override_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            response = client.get(f"/jobs/{job_id}")

        assert response.status_code == 200
        assert response.json() == {
            "id": str(job_id),
            "status": "queued",
            "payload": {"task": "train_model"},
            "attempt_count": 0
        }

        fake_db.get.assert_called_once_with(Job, job_id)
    finally:
        app.dependency_overrides.pop(get_db, None)