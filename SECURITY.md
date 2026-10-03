# Security

## Reporting a vulnerability

Please report security issues privately — do not open a public issue.

- Email: [anvarov1170@gmail.com](mailto:anvarov1170@gmail.com)
- Telegram: [@anvarov_911](https://t.me/anvarov_911)

Include what you found, how to reproduce it and its impact. You will get an
answer within a few days.

## Security model (summary)

- **Private by default.** Only Telegram users on `AUTHORIZED_TELEGRAM_USER_IDS`
  can sign in; an empty list means nobody (fails closed). The list is checked
  on every request, not only at sign-in.
- **Authentication.** Telegram `initData` is HMAC-verified with the bot token
  and must be fresh; the API issues short-lived signed access tokens with a
  sliding refresh.
- **Authorisation.** Every query is scoped to the owner; another user's object
  is a 404, never a 403.
- **Uploads.** Presigned part URLs are bound to the part's MD5; originals are
  immutable — derived files are written only under derived keys.
- **Secrets.** Live only in `/opt/synthcut/shared/.env` (mode 600) on the
  server; never in the repository, logs or error messages (the bot token is
  scrubbed from notification errors).
- **Agents.** Tools take ids, never paths or shell commands; every tool call
  passes a permission gate and is recorded.

Details: [docs/ARCHITECTURE.md §13](docs/ARCHITECTURE.md).
