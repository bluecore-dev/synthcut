# ADR-0006 — Additive migrations, rollback by image tag

**Why.** A deploy must be reversible in seconds without restoring the database.

**Impact.** Each release builds `synthcut/app:<release>` and `synthcut/web:<release>`; rollback starts the previous tags. Migrations only add (tables, nullable columns, columns with server defaults, indexes) so the previous release keeps working on the newer schema. Migrations run once, in a one-shot `migrate` container, under a PostgreSQL advisory lock, as the application role (tables owned by the role that uses them).

**Decision.** No `DROP`/`RENAME` of anything a running release reads; a destructive change needs its own two-step plan.
