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
    external_effect_mode: Literal["simulate", "live"] = "simulate"
    m6_enabled: bool = False
    demo_lifecycle_enabled: bool = False
    phase4_config_file: Path | None = None
    phase5_config_file: Path | None = None
    m6_contexts_file: Path | None = None
    m6_calibration_file: Path | None = None
    telegram_bot_token: SecretStr | None = None
    telegram_recipients_file: Path | None = None
    alert_demo_seconds: int = Field(default=30, ge=1, le=300)
    alert_design_real_seconds: int = Field(default=60, ge=1, le=600)
    http_host: str = "127.0.0.1"
    http_port: int = Field(default=8088, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @model_validator(mode="after")
    def validate_security(self) -> Settings:
        if self.phase5_config_file is not None and (
            self.phase4_config_file is None or self.backend_service_token is None
        ):
            raise ValueError("Phase 5 requires isolated Phase 4 and authenticated backend commands")
        if self.phase4_config_file is not None and self.http_host not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError("isolated Phase 4 HTTP must bind loopback")
        if self.phase4_config_file is not None and (
            self.environment != "test" or not self.demo_lifecycle_enabled
        ):
            raise ValueError("isolated Phase 4 requires test profile and enabled demo lifecycle")
        if self.demo_lifecycle_enabled and (
            not self.m6_enabled or self.environment == "design-real"
        ):
            raise ValueError("demo lifecycle requires enabled research M6 in test/demo profile")
        if self.m6_enabled:
            if self.m6_contexts_file is None:
                raise ValueError("M6 requires an explicit episode-context file")
            if self.environment == "design-real":
                raise ValueError("M6 is research-only until the held-out safety gate is reviewed")
        if self.environment != "test":
            if not self.mqtt_tls:
                raise ValueError("MQTT TLS is mandatory outside the test profile")
            if self.mqtt_ca_file is None:
                raise ValueError("SENTINEL_MQTT_CA_FILE is mandatory outside test")
            if not self.mqtt_username or self.mqtt_password is None:
                raise ValueError("MQTT credentials are mandatory outside test")
            if self.backend_base_url and self.backend_service_token is None:
                raise ValueError("backend token is required when backend URL is configured")
        if self.external_effect_mode == "live":
            if not self.backend_base_url or self.backend_service_token is None:
                raise ValueError("live effects require the authenticated backend")
            if self.telegram_bot_token is None or self.telegram_recipients_file is None:
                raise ValueError("live effects require Telegram token and recipient map")
        return self

    def validate_files(self) -> None:
        if self.phase5_config_file is not None and not self.phase5_config_file.is_file():
            raise ConfigurationError("Phase 5 configuration file is unavailable")
        if self.phase4_config_file is not None and not self.phase4_config_file.is_file():
            raise ConfigurationError("Phase 4 configuration file is unavailable")
        if self.m6_enabled:
            for path in (self.m6_contexts_file, self.m6_calibration_file):
                if path is not None and not path.is_file():
                    raise ConfigurationError(f"M6 input file does not exist: {path}")
        if self.mqtt_tls and self.mqtt_ca_file is not None and not self.mqtt_ca_file.is_file():
            raise ConfigurationError(f"MQTT CA file does not exist: {self.mqtt_ca_file}")
        if (
            self.external_effect_mode == "live"
            and self.telegram_recipients_file is not None
            and not self.telegram_recipients_file.is_file()
        ):
            raise ConfigurationError(
                f"Telegram recipient map does not exist: {self.telegram_recipients_file}"
            )

    @property
    def alert_escalation_seconds(self) -> int:
        if self.environment == "design-real":
            return self.alert_design_real_seconds
        return self.alert_demo_seconds
