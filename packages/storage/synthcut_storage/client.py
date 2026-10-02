"""S3-compatible object storage client.

Two boto3 clients are kept:

* ``internal`` talks to the storage service over the private network and is
  the only one that performs requests.
* ``signer`` is configured with the *public* endpoint and is only used to
  presign URLs, so the signature covers the host the browser will actually
  call. It never opens a connection.

Video bytes never pass through the API: the browser PUTs each part straight to
storage with a presigned URL whose signature includes ``Content-MD5``, so the
storage server itself rejects any part whose body differs from what the client
hashed (verified against Garage: ``400 InvalidDigest``).
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .keys import assert_writable, is_original


@dataclass(frozen=True, slots=True)
class StorageConfig:
    endpoint_internal: str
    endpoint_public: str
    region: str
    bucket: str
    access_key_id: str
    secret_access_key: str


@dataclass(frozen=True, slots=True)
class UploadedPart:
    number: int
    size: int
    etag: str  # without quotes


@dataclass(frozen=True, slots=True)
class ObjectInfo:
    key: str
    size: int
    etag: str
    content_type: str | None
    last_modified: datetime | None


@dataclass(frozen=True, slots=True)
class MultipartUploadRef:
    key: str
    upload_id: str
    initiated: datetime | None


class StorageError(RuntimeError):
    pass


class NoSuchUploadError(StorageError):
    pass


def _strip_etag(etag: str) -> str:
    return etag.strip().strip('"')


def md5_b64_to_hex(md5_b64: str) -> str:
    raw = base64.b64decode(md5_b64, validate=True)
    if len(raw) != 16:
        raise ValueError("MD5 must be 16 bytes")
    return binascii.hexlify(raw).decode()


def _boto_config(*, read_timeout: int = 120) -> Config:
    return Config(
        signature_version="s3v4",
        s3={"addressing_style": "path"},
        retries={"max_attempts": 4, "mode": "standard"},
        connect_timeout=5,
        read_timeout=read_timeout,
        # botocore >= 1.36 adds CRC checksums by default, which several
        # S3-compatible servers reject. Only send what the operation requires.
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
    )


class Storage:
    def __init__(self, cfg: StorageConfig) -> None:
        self.cfg = cfg
        common: dict[str, Any] = {
            "region_name": cfg.region,
            "aws_access_key_id": cfg.access_key_id,
            "aws_secret_access_key": cfg.secret_access_key,
        }
        self.internal = boto3.client(
            "s3", endpoint_url=cfg.endpoint_internal, config=_boto_config(), **common
        )
        self.signer = boto3.client("s3", endpoint_url=cfg.endpoint_public, config=_boto_config(), **common)

    @property
    def bucket(self) -> str:
        return self.cfg.bucket

    # ------------------------------------------------------------------ health

    def ping(self) -> None:
        self.internal.head_bucket(Bucket=self.bucket)

    # ------------------------------------------------------------------ multipart (originals)

    def create_multipart(self, key: str, content_type: str) -> str:
        resp = self.internal.create_multipart_upload(Bucket=self.bucket, Key=key, ContentType=content_type)
        return str(resp["UploadId"])

    def presign_part(
        self, key: str, upload_id: str, part_number: int, md5_b64: str, ttl_seconds: int
    ) -> tuple[str, dict[str, str], datetime]:
        url = self.signer.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "UploadId": upload_id,
                "PartNumber": part_number,
                "ContentMD5": md5_b64,
            },
            ExpiresIn=ttl_seconds,
            HttpMethod="PUT",
        )
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        return url, {"Content-MD5": md5_b64}, expires_at

    def list_parts(self, key: str, upload_id: str) -> list[UploadedPart]:
        parts: list[UploadedPart] = []
        marker = 0
        while True:
            try:
                resp = self.internal.list_parts(
                    Bucket=self.bucket, Key=key, UploadId=upload_id, PartNumberMarker=marker, MaxParts=1000
                )
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") == "NoSuchUpload":
                    raise NoSuchUploadError(upload_id) from exc
                raise
            for p in resp.get("Parts", []):
                parts.append(UploadedPart(int(p["PartNumber"]), int(p["Size"]), _strip_etag(p["ETag"])))
            if not resp.get("IsTruncated"):
                break
            next_marker = int(resp.get("NextPartNumberMarker") or 0)
            if next_marker <= marker:
                break
            marker = next_marker
        parts.sort(key=lambda p: p.number)
        return parts

    def complete_multipart(self, key: str, upload_id: str, parts: list[UploadedPart]) -> str:
        try:
            resp = self.internal.complete_multipart_upload(
                Bucket=self.bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": [{"PartNumber": p.number, "ETag": f'"{p.etag}"'} for p in parts]},
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "NoSuchUpload":
                raise NoSuchUploadError(upload_id) from exc
            raise
        return _strip_etag(str(resp.get("ETag", "")))

    def abort_multipart(self, key: str, upload_id: str) -> None:
        try:
            self.internal.abort_multipart_upload(Bucket=self.bucket, Key=key, UploadId=upload_id)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "NoSuchUpload":
                raise

    def list_multipart_uploads(self, prefix: str = "") -> list[MultipartUploadRef]:
        refs: list[MultipartUploadRef] = []
        key_marker: str | None = None
        upload_marker: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self.bucket, "Prefix": prefix, "MaxUploads": 1000}
            if key_marker:
                kwargs["KeyMarker"] = key_marker
            if upload_marker:
                kwargs["UploadIdMarker"] = upload_marker
            resp = self.internal.list_multipart_uploads(**kwargs)
            for u in resp.get("Uploads", []):
                refs.append(MultipartUploadRef(u["Key"], u["UploadId"], u.get("Initiated")))
            if not resp.get("IsTruncated"):
                break
            key_marker = resp.get("NextKeyMarker")
            upload_marker = resp.get("NextUploadIdMarker")
            if not key_marker and not upload_marker:
                break
        return refs

    # ------------------------------------------------------------------ objects

    def head(self, key: str) -> ObjectInfo | None:
        try:
            resp = self.internal.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        return ObjectInfo(
            key=key,
            size=int(resp["ContentLength"]),
            etag=_strip_etag(resp.get("ETag", "")),
            content_type=resp.get("ContentType"),
            last_modified=resp.get("LastModified"),
        )

    def presign_get(self, key: str, ttl_seconds: int, *, download_name: str | None = None) -> str:
        params: dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if download_name:
            safe = "".join(c for c in download_name if c.isalnum() or c in "._- ")[:120] or "download"
            params["ResponseContentDisposition"] = f'attachment; filename="{safe}"'
        return str(self.signer.generate_presigned_url("get_object", Params=params, ExpiresIn=ttl_seconds))

    def internal_get_url(self, key: str, ttl_seconds: int = 3600) -> str:
        """Presigned URL on the *internal* endpoint, for ffmpeg/ffprobe in workers."""
        return str(
            self.internal.generate_presigned_url(
                "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=ttl_seconds
            )
        )

    # ------------------------------------------------------------------ derived files (never originals)

    def put_derived_file(self, key: str, path: Path, content_type: str) -> None:
        assert_writable(key)
        self.internal.upload_file(str(path), self.bucket, key, ExtraArgs={"ContentType": content_type})

    def put_derived_bytes(self, key: str, body: bytes, content_type: str) -> None:
        assert_writable(key)
        self.internal.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType=content_type)

    def delete_derived(self, key: str) -> None:
        assert_writable(key)
        self.internal.delete_object(Bucket=self.bucket, Key=key)

    def download_file(self, key: str, path: Path) -> None:
        self.internal.download_file(self.bucket, key, str(path))

    @staticmethod
    def guard_original(key: str) -> bool:
        return is_original(key)
