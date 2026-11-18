# Soup Backend — Design Note

## Architecture

The service uses FastAPI, PostgreSQL, and Python workers. PostgreSQL stores jobs, their states, and execution records. Docker Compose runs the API, database, and four workers.

PostgreSQL was chosen because it supports transactions, row-level locking, and `FOR UPDATE SKIP LOCKED`, which are useful for coordinating concurrent workers.

## Job Claiming

Workers select queued jobs or running jobs with expired leases using `SELECT ... FOR UPDATE SKIP LOCKED`. This prevents workers from claiming the same row simultaneously.

Each claim sets the status to `running`, assigns a worker ID, creates a 30-second lease, and increments the attempt count and fencing token.

## Worker Failure and Recovery

If a worker crashes, its job remains `running` until the lease expires. Another worker can then reclaim it.

The fencing token prevents an outdated worker from completing a job after another worker has reclaimed it. Lease expiry is checked against the PostgreSQL clock to reduce dependence on individual worker clocks.

## Cancellation

The API allows queued and running jobs to be cancelled. Cancellation locks the job row and changes its status to `cancelled`.

Cancellation does not forcibly terminate running Python code. Instead, the completion transaction checks the current job status, worker ID, fencing token, and lease. If cancellation commits first, the worker cannot successfully complete that job.

If completion commits first, the job remains `succeeded`.

## Side Effects and Guarantees

The side effect is a row in the `job_effects` table. The worker inserts this row and changes the job status to `succeeded` in the same database transaction.

A unique constraint on `job_effects.job_id` prevents multiple committed effect records for one job.

The API also uses a unique idempotency key to prevent duplicate job creation when clients retry requests.

The design supports recovery through retries and provides at-most-once committed database side effects. It does not guarantee exactly-once execution of worker code or exactly-once external operations.

## Limitations

The current worker performs a minimal operation and immediately attempts completion. It does not simulate a long-running business task.

Lease recovery requires at least one healthy worker to continue polling. The implementation has no lease renewal for tasks lasting longer than 30 seconds.

The database constraint protects PostgreSQL effect records, but external actions such as sending emails or calling third-party APIs would require additional safeguards.
