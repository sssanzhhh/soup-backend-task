# Soup Backend Engineer Task

A FastAPI-based background job processing system using PostgreSQL and multiple workers.

The project focuses on job reliability, idempotency, worker recovery, cancellation, and concurrency safety.

## Tech Stack

- Python 3.13
- FastAPI
- PostgreSQL 16
- SQLAlchemy
- Docker Compose
- Pytest

## Quick Start

1. Copy `.env.example` to `.env`.
2. Configure the environment variables.
3. Start the services:

```bash
docker compose up --build -d
```

The API is available at `http://127.0.0.1:8000`.

Interactive API documentation: `http://127.0.0.1:8000/docs`.

Docker Compose starts the API, PostgreSQL, and four worker replicas.

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/jobs` | Create a background job |
| GET | `/jobs/{job_id}` | Retrieve a job |
| GET | `/jobs` | List jobs with pagination |
| POST | `/jobs/{job_id}/cancel` | Cancel a queued or running job |

### Create a Job

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"idempotency_key":"example-001","payload":{"task":"demo"}}'
```

A successful request returns HTTP 201 with the job ID and status.

Repeating the request with the same idempotency key and payload returns the existing job. Reusing the key with a different payload returns HTTP 409.

### List Jobs

```bash
curl "http://127.0.0.1:8000/jobs?limit=10&offset=0"
```

The `limit` parameter accepts values from 1 to 100. The `offset` parameter must be non-negative.

## Worker Reliability

Workers claim jobs using PostgreSQL row-level locking and `SKIP LOCKED` to avoid simultaneous claims.

Jobs have leases and fencing tokens. An expired lease allows another worker to reclaim the job. Completion checks the worker identity, fencing token, and lease validity.

Job completion and the database side effect occur in one transaction.

See `design.md` for the architecture and reliability decisions.

## Automated Tests

Run:

```bash
python -m pytest tests/ -v
```

The latest complete local run passed all 13 tests.

The test suite includes API tests and concurrency scenarios such as double claiming, zombie workers, cancellation races, transaction isolation, and clock-skew-related behavior.

## Chaos Testing

The chaos harness is implemented in `tests/chaos_test.py`.

It creates 10,000 jobs, starts eight worker processes, randomly kills and replaces workers, performs concurrent API requests, attempts cancellations, and checks final database invariants.

The harness uses `http://127.0.0.1:8001` for API requests, so a separate local API must be running on that port.

Run the chaos test only against an isolated test environment. It modifies database records and terminates worker processes.

Previously captured raw execution logs, including failed attempts, are preserved in `chaos_results/`.

## Reliability Scope

The implementation targets database-backed at-most-once effects per job through a unique job-effect constraint and transactional completion.

Worker execution itself may be repeated after lease expiry or process termination. The system does not guarantee exactly-once execution of arbitrary external side effects.

## Project Files

- `app/` — API, database models, and worker logic
- `tests/` — automated tests and chaos harness
- `chaos_results/` — raw chaos-test logs
- `design.md` — architecture and reliability explanation
- `docker-compose.yml` — API, workers, and PostgreSQL configuration

## Limitations

The project is a take-home implementation, not a production-ready distributed job platform.

A sustained 100 RPS benchmark has not been demonstrated. Production deployment would require further performance validation and operational hardening.