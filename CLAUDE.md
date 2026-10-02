# Working on SynthCut

Read `docs/ARCHITECTURE.md` before changing behaviour; architecture changes get
an ADR in `docs/adr/` (why → impact → alternatives → decision).

## Hard rules

* The VPS (185.2.101.47) is shared with other live products. Touch only the
  compose project `synthcut`, `/opt/synthcut`, `/srv/synthcut`,
  `/etc/nginx/sites-available/synthcut` (+ its sites-enabled link) and
  `/var/www/synthcut-acme`. Never prune Docker globally, never restart nginx
  (reload only, after `nginx -t`).
* Never run tests against production. Integration tests drop the schema of
  `SYNTHCUT_TEST_DATABASE_URL`. On the server use `test-stack.sh`.
* `/opt/synthcut/shared/.env` is created once by `bootstrap.sh`; never
  regenerate it (sessions, the Garage key and the webhook secret depend on it).
* One bot token = one consumer. The bot is webhook-only; do not add polling.
* Migrations are additive only (ADR-0006).
* Originals are immutable: write derived files only through
  `Storage.put_derived_*` with keys from `synthcut_storage.keys`.
* Agent tools take ids, never paths or commands; inputs are Pydantic models
  with `extra="forbid"` (enforced at registration).
* Values the server owns (presets, stage labels, phases, fps choices) come
  from the API/OpenAPI types — do not hard-code them in the Mini App.
* New tests: prove they catch the bug (temporarily revert the fix, see them fail).

## Commands

`make test-unit` · `make test` · `make lint` · `make openapi` · `make deploy`

Server: `docker compose -p synthcut ps|logs -f <svc>`; releases in
`/opt/synthcut/releases`, live one at `/opt/synthcut/current`.
