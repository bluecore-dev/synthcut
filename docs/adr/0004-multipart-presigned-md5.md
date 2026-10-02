# ADR-0004 — S3 multipart with MD5-bound presigned parts (instead of tus)

**Why.** Rule 2: 4–50 GB uploads must never pass through the API. tus needs a server that receives the bytes. The spec lists "chunked, multipart, pause/resume, retry, checksum, progress, interruption recovery".

**Impact.** The API opens a multipart upload and presigns one URL per part with the part's MD5 inside the signature (`SignedHeaders=content-md5;host`), so storage itself rejects any corrupted part. The client re-checks the returned ETag. Resume reads ListParts; a resumed session is sample-verified (3 parts) before skipping, so a different file with the same name and size is never stitched in. Completion verifies the exact part set and sizes, then HEADs the object.

**Alternatives.** tus via a proxy (bytes through our server); browser SHA-256 of whole 5 GB files before upload (minutes on a phone); flexible `x-amz-checksum-*` headers (less uniformly supported across S3 servers).

**Decision.** Multipart + Content-MD5. Full-file SHA-256 is computed server-side during ingestion.
