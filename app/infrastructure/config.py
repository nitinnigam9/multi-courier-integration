"""Process configuration."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from the environment and an optional .env file."""

    app_name: str = "Assignment API"
    rate_limit_enabled: bool = True
    trust_proxy: bool = False
    burst_quota: int = Field(default=30, ge=1)
    burst_window_seconds: int = Field(default=60, ge=1)
    sustained_quota: int = Field(default=1000, ge=1)
    sustained_window_seconds: int = Field(default=3600, ge=1)

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def quota_policies(self) -> tuple[tuple[str, int, int], ...]:
        """Return (name, quota, window seconds) for each enforced policy."""
        return (
            ("burst", self.burst_quota, self.burst_window_seconds),
            ("sustained", self.sustained_quota, self.sustained_window_seconds),
        )


class CourierSettings(BaseSettings):
    """Courier credentials. Names match the keys already used in .env."""

    courier_partner: str = "urbanebolt"
    courier_partner_url: str = ""
    courier_username: str = ""
    courier_password: str = ""
    courier_customer_code: str = ""
    courier_service_type: str = "SDD"
    courier_login_path: str = "api/v1/auth/getToken/"
    courier_manifest_path: str = "api/v1/services/manifest/"
    courier_tracking_path: str = "api/v1/services/tracking-pub/"
    courier_cancel_path: str = "api/v1/services/cancel/"
    courier_csrf_token: str = ""
    database_url: str = ""
    bulk_concurrency: int = Field(default=10, ge=1, le=50)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
