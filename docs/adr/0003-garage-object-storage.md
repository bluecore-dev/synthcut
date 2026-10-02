# ADR-0003 — Garage instead of MinIO

**Why.** The spec's S3-compatible store is usually MinIO, but MinIO stopped publishing community Docker images in 2025 (`minio/minio` returns 404 on Docker Hub) and the community edition is in maintenance mode.

**Impact.** Garage v2.4.1 (actively released, Rust, ~50 MB RAM), single node, `replication_factor = 1`, compression off (video is already compressed). Verified before adoption on this VPS: presigned UploadPart with signed `Content-MD5` (tampered body → `400 InvalidDigest`), part ETag = MD5, S3 composite final ETag, ListParts, ListMultipartUploads, abort, ranged GET (206), anonymous access 403, bucket quotas. Setup (layout, bucket, imported key, quota) is the idempotent `garage-init.sh`.

**Alternatives.** Old MinIO image from quay.io (unmaintained); SeaweedFS (heavier, more moving parts); RustFS (preview quality); plain filesystem (breaks spec rule 13 and the direct-upload design).

**Decision.** Garage, behind plain S3 calls only — swapping it for AWS S3, R2 or another Garage cluster is configuration.
