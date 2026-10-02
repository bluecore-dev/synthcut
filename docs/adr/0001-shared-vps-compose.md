# ADR-0001 — One isolated Docker Compose project on the shared VPS

**Why.** The spec asks for Docker/Compose and an "initial server" of 8–16 vCPU / 32 GB / 200 GB NVMe. The available VPS has 4 vCPU, 7.8 GB, ~45 GB free and already runs other live products whose owner requires that nothing of theirs is touched.

**Impact.** SynthCut gets its own PostgreSQL, Redis and object store inside compose project `synthcut`; only 127.0.0.1:3400–3403 are published; the host nginx gets one new server block installed only after `nginx -t` passes. Media workers are capped (2 CPU / 3 GB), uploads are refused below 8 GiB free disk, total media is capped at 25 GiB (Garage hard limit 30 GiB). Log files are rotated.

**Alternatives.** Reuse the host PostgreSQL/Redis (less RAM, but shared blast radius and credentials); bare-metal processes under pm2/systemd (what other projects use, but not what the spec asks and harder to move to a bigger box).

**Decision.** Isolated compose project. Moving to a dedicated server is copying `/srv/synthcut` and the env file; scaling storage is pointing `S3_ENDPOINT_*` elsewhere.
