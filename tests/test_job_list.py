import uuid
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db


def test_list_jobs_success():
    job_id = uuid.uuid4()

    fake_job = MagicMock()
    fake_job.id = job_id
    fake_job.status = "queued"
    fake_job.payload = {"task": "train_model"}
    fake_job.attempt_count = 0

    fake_db = MagicMock()
    fake_db.query.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [fake_job]

    def override_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            response = client.get("/jobs?limit=5&offset=0")

        assert response.status_code == 200
        assert response.json() == {
            "items": [
                {
                    "id": str(job_id),
                    "status": "queued",
                    "payload": {"task": "train_model"},
                    "attempt_count": 0
                }
            ],
            "limit": 5,
            "offset": 0
        }
    finally:
        app.dependency_overrides.pop(get_db, None)
def test_list_jobs_invalid_limit():
    with TestClient(app) as client:
        response = client.get("/jobs?limit=101&offset=0")

    assert response.status_code == 422
def test_list_jobs_negative_offset():
    with TestClient(app) as client:
        response = client.get("/jobs?limit=5&offset=-1")

    assert response.status_code == 422