Redis 7 runs as the `redis` service: no persistence, 64 MB, `noeviction`,
password protected, not published. It carries only disposable state (pub/sub,
worker wake-ups, rate limits) — PostgreSQL is the ledger (ADR-0002).
