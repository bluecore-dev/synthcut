# ADR-0002 — PostgreSQL-leased job queue; Redis is the doorbell

**Why.** The spec requires idempotent, retryable, observable, recoverable jobs, priorities, separate CPU/GPU/render queues, and that one job can never produce a duplicate render. Jobs here are few and long (minutes of FFmpeg, long LLM loops). Celery on Redis redelivers tasks that outlive its visibility timeout, and enqueueing outside the business transaction needs an outbox to avoid lost or phantom jobs.

**Impact.** `jobs` is the ledger: enqueue in the caller's transaction, `idempotency_key` UNIQUE, claim with `FOR UPDATE SKIP LOCKED`, renewable lease with heartbeats, writes fenced by lease owner, reaper for expired leases, exponential backoff, dead state, cancellation, graceful hand-back. Workers claim only kinds they have handlers for. Redis pub/sub only wakes idle workers (polling every 2 s is the fallback).

**Alternatives.** Celery/Redis (rich, but the guarantees above would need extra machinery); Dramatiq/RQ (same visibility problem); `procrastinate` (Postgres-based, but its own schema separate from the observability columns the spec lists).

**Decision.** ~400 lines of our own, covered by concurrency, fencing, retry and recovery tests.
