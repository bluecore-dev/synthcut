PostgreSQL 16 runs as the `postgres` service in docker-compose.yml with data in
`/srv/synthcut/postgres`. The application role `synthcut` owns the database and
runs the migrations (`python -m synthcut_core.migrate upgrade`), so every table
is owned by the role that uses it.
