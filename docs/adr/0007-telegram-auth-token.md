# ADR-0007 — initData exchanged once for a short-lived token

**Why.** Validating `initData` on every request breaks long sessions: its `auth_date` is fixed when the Mini App opens, but a 5 GB upload can take an hour or more.

**Impact.** `POST /auth/telegram` validates the HMAC (bot token, `WebAppData` key; both canonical forms with/without the newer `signature` field are accepted — forging either still needs the token), rejects data older than 1 h, checks the allowlist and returns a 12 h HS256 token. The client refreshes it while open. The allowlist is re-checked on every request.

**Decision.** Token exchange with sliding refresh; no cookies, so no CSRF surface.
