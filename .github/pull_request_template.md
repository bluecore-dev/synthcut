## What and why

<!-- What changes, and the problem it solves. Link the phase / ADR if relevant. -->

## How it was verified

- [ ] `make lint` and `make test` pass locally
- [ ] New behaviour has tests that fail without the change
- [ ] Server test stack (`infrastructure/deployment/test-stack.sh`) for media / migration changes
- [ ] `make openapi` re-run if the API changed
- [ ] Docs updated (ARCHITECTURE / ADR / SITEMAP / CHANGELOG)

## Deployment notes

<!-- Migrations (additive only), new environment variables, model downloads. -->
