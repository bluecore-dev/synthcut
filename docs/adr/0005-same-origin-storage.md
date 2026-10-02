# ADR-0005 — Object storage on the Mini App's own origin

**Why.** Browser PUTs to another origin need CORS preflights and an exposed ETag header, plus a second hostname and certificate.

**Impact.** nginx proxies `https://<domain>/synthcut-media/…` to Garage with the original path and Host, which is exactly what presigned URLs are signed for (path-style, public endpoint). Only GET and PUT are allowed there; bodies up to 80 MB stream unbuffered. Other API routes keep a 1 MB body limit.

**Decision.** Same origin. A separate storage domain remains possible by changing `S3_ENDPOINT_PUBLIC`.
