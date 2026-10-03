"""Runtime configuration, read from the environment (``/opt/synthcut/shared/.env``
in production). Secrets are ``SecretStr`` so they never end up in logs or reprs.
"""

from __future__ import annotations

from functools import cached_property, lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

GIB = 1024**3
MIB = 1024**2


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    env: Literal["dev", "test", "prod"] = "dev"
    release: str = "dev"
    log_level: str = "INFO"

    public_base_url: str = "http://localhost:3400"

    database_url: str = "postgresql+psycopg://synthcut:synthcut@localhost:5432/synthcut"
    db_pool_size: int = 5
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint_internal: str = "http://localhost:3900"
    s3_endpoint_public: str = "http://localhost:3900"
    s3_region: str = "us-east-1"
    s3_bucket: str = "synthcut-media"
    s3_access_key_id: str = ""
    s3_secret_access_key: SecretStr = SecretStr("")

    telegram_bot_token: SecretStr = SecretStr("")
    telegram_webhook_secret: SecretStr = SecretStr("")
    telegram_bot_username: str = "synthcut_bot"
    # Comma separated Telegram user ids allowed to use this private system
    # (spec §40). Empty means nobody — the system fails closed.
    authorized_telegram_user_ids: str = ""

    session_secret: SecretStr = SecretStr("")
    access_token_ttl_seconds: int = 12 * 3600
    init_data_max_age_seconds: int = 3600

    max_upload_bytes: int = 50 * GIB
    storage_quota_bytes: int = 25 * GIB
    # Uploads are refused if they would leave less than this free on the disk
    # that also hosts other services (the VPS is shared).
    disk_reserve_bytes: int = 8 * GIB
    disk_probe_path: str | None = None
    upload_part_size: int = 16 * MIB
    upload_presign_ttl_seconds: int = 3600
    upload_session_idle_ttl_seconds: int = 48 * 3600

    scratch_dir: str = "/scratch"
    media_threads: int = Field(default=2, ge=1, le=16)
    media_proxy_short_side: int = 720
    media_url_ttl_seconds: int = 3600
    # Speech (Phase 4, spec §13). ``provider:model``; the local engine's model is
    # fetched into speech_models_dir at deploy, jobs never download.
    speech_route: str = "faster-whisper:large-v3-turbo"
    speech_models_dir: str = "/models"
    speech_threads: int = Field(default=2, ge=1, le=16)
    speech_beam_size: int = Field(default=5, ge=1, le=10)
    speech_auto: bool = True  # transcribe every file with audio once it is ingested
    notify_telegram: bool = True
    telegram_api_base: str = "https://api.telegram.org"
    worker_queues: str = "io"
    worker_concurrency: int = Field(default=1, ge=1, le=16)
    worker_lease_seconds: int = 60
    worker_poll_seconds: float = 2.0
    worker_scheduler: bool = False

    @cached_property
    def allowed_telegram_ids(self) -> frozenset[int]:
        ids: set[int] = set()
        for chunk in self.authorized_telegram_user_ids.replace(";", ",").split(","):
            chunk = chunk.strip()
            if chunk:
                ids.add(int(chunk))
        return frozenset(ids)

    @property
    def mini_app_url(self) -> str:
        return self.public_base_url.rstrip("/") + "/"

    def queues(self) -> list[str]:
        return [q.strip() for q in self.worker_queues.split(",") if q.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
