from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from sentinelward.errors import ConfigurationError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SENTINEL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["test", "demo", "design-real"] = "test"
    database_url: str = "postgresql://postgres@127.0.0.1:55432/postgres"
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = Field(default=8883, ge=1, le=65535)
    mqtt_client_id: str = "sentinelward-automation"
    mqtt_username: str | None = None
    mqtt_password: SecretStr | None = None
    mqtt_ca_file: Path | None = None
    mqtt_tls: bool = True
    mqtt_keepalive_seconds: int = Field(default=60, ge=15, le=300)
    mqtt_max_payload_bytes: int = Field(default=65_536, ge=1024, le=1_048_576)
    backend_base_url: str | None = None
    backend_service_token: SecretStr | None = None
    backend_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    backend_max_attempts: int = Field(default=3, ge=1, le=5)
    external_effect_mode: Literal["simulate"] = "simulate"
    http_host: str = "127.0.0.1"
    http_port: int = Field(default=8088, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @model_validator(mode="after")
    def validate_security(self) -> Settings:
        if self.environment != "test":
            if not self.mqtt_tls:
                raise ValueError("MQTT TLS is mandatory outside the test profile")
            if self.mqtt_ca_file is None:
                raise ValueError("SENTINEL_MQTT_CA_FILE is mandatory outside test")
            if not self.mqtt_username or self.mqtt_password is None:
                raise ValueError("MQTT credentials are mandatory outside test")
            if self.backend_base_url and self.backend_service_token is None:
                raise ValueError("backend token is required when backend URL is configured")
        return self

    def validate_files(self) -> None:
        if self.mqtt_tls and self.mqtt_ca_file is not None and not self.mqtt_ca_file.is_file():
            raise ConfigurationError(f"MQTT CA file does not exist: {self.mqtt_ca_file}")
