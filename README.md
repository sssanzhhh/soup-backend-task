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

### Recorded Chaos Runs

Six execution logs were preserved:

- `run_20261118_010339.log` — 10,000 jobs succeeded with zero duplicate effects; no explicit final invariant PASS was recorded.
- `run_20261118_012001.log` — final state invariants PASS.
- `run_20261118_012626.log` — command typo (`ython`); the harness did not start.
- `run_20261118_012648.log` — harness failed because `send_requests` was undefined.
- `run_20261118_013210.log` — harness failed because `cancel_jobs` was undefined.
- `run_20261118_014226.log` — final state invariants PASS.

Two runs explicitly passed all final state invariants. The failed attempts remain available for review.

### Chaos Harness Limitations

The harness tests a finite set of worker crashes, concurrent requests, cancellations, and database invariants. It does not establish sustained 100 RPS performance, production-scale resource usage, or correctness of arbitrary external side effects. It also does not exhaustively cover every possible concurrency interleaving.

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

## Ship / Don't Ship Decision

**Decision: DON'T SHIP at 100 RPS yet.**

The implementation passed 13 automated tests and demonstrated recovery under chaos testing with 10,000 jobs and eight workers.

However, these results do not establish sustained performance at 100 requests per second. The system has not been benchmarked at that request rate.

**First fix:** Add a repeatable 100 RPS load test and measure API latency, error rate, job completion rate, and database contention.

The system should only be considered for production deployment after performance validation and further operational review.

## Reflection

The most important lesson from this task was that reliable background processing requires more than retrying failed jobs. PostgreSQL locking, leases, fencing tokens, and transactional side effects help protect the system against concurrent workers and unexpected process termination.

Chaos testing also showed why checking final database invariants is more valuable than simply checking whether worker processes remain alive.

## AI Disclosure

AI tools were used to support implementation planning, debugging, test design, and documentation.

I accepted suggestions involving FastAPI endpoint structure, PostgreSQL row-level locking with `SKIP LOCKED`, lease-based worker recovery, fencing tokens, and transactional side effects.

I verified the implementation locally through automated tests and chaos-test runs. The test suite passed 13 tests, and two recorded chaos runs passed the final state invariants.

During development, some chaos-harness runs failed because of missing function definitions. I corrected the harness and repeated the tests while preserving the failed logs.

AI-generated suggestions were reviewed and adjusted based on observed behavior rather than accepted as proof of correctness. The system has not been validated at a sustained 100 RPS, so my final decision remains DON'T SHIP.