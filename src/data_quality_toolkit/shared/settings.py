from __future__ import annotations

import os
from pathlib import Path
from typing import Any, ClassVar, Literal, cast  # ClassVar + cast

from data_quality_toolkit.shared.compat import (
    V2,
    BaseSettings,
    Field,
    SettingsConfigDict,
    field_validator,
)
from data_quality_toolkit.shared.constants import DEFAULT_MAX_ROWS_IN_MEMORY, DEFAULT_SAMPLE_SIZE


def _resolve_env_file() -> str | None:
    if os.getenv("DQT_LOAD_ENV", "").lower() in {"1", "true", "yes", "on"}:
        try:
            from dotenv import find_dotenv

            return find_dotenv(usecwd=True) or ".env"
        except Exception:  # pragma: no cover
            return ".env"
    return None


class Settings(BaseSettings):
    """Central configuration for DQT."""

    # Engine limits
    max_rows_in_memory: int = Field(
        DEFAULT_MAX_ROWS_IN_MEMORY, validation_alias="MAX_ROWS_IN_MEMORY"
    )
    sample_size: int = Field(DEFAULT_SAMPLE_SIZE, validation_alias="SAMPLE_SIZE")

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        "INFO", validation_alias="LOG_LEVEL"
    )
    log_format: Literal["json", "text"] = Field("json", validation_alias="LOG_FORMAT")

    # Export / BI
    export_base_dir: Path = Field("./dist", validation_alias="EXPORT_BASE_DIR")
    pbi_base_folder_parameter: Path = Field("./dist", validation_alias="PBI_BASE_FOLDER_PARAMETER")

    # LLM / SSOT
    api_key: str | None = Field(None, validation_alias="API_KEY")
    lorax_base_url: str = Field("http://localhost:8080", validation_alias="LORAX_BASE_URL")
    lorax_timeout_secs: int = Field(30, validation_alias="LORAX_TIMEOUT_SECS")

    # Security / feature flags
    dqt_allow_network: bool = Field(False, validation_alias="DQT_ALLOW_NETWORK")

    # Lineage / manifest (Phase 10 feature — declared for type-checker visibility)
    serde_impl: Literal["pydantic", "msgspec"] = Field("pydantic", validation_alias="SERDE_IMPL")
    json_writer: Literal["json", "orjson"] = Field("json", validation_alias="JSON_WRITER")
    lineage_schema_version: str = Field("1.0.0", validation_alias="LINEAGE_SCHEMA_VERSION")
    manifest_file: str = Field("artifacts.json", validation_alias="MANIFEST_FILE")

    # ------------------------------
    # Config (v2 dict / v1 class)
    # ------------------------------
    if V2:
        model_config: ClassVar[SettingsConfigDict] = {
            "env_file": None,
            "case_sensitive": False,
            "extra": "ignore",
        }
    else:  # pragma: no cover

        class Config:
            env_file = None
            case_sensitive = False

    # ------------------------------
    # Validators
    # ------------------------------
    if V2:
        _fv = cast(Any, field_validator)  # silence overload checking

        @_fv("export_base_dir", "pbi_base_folder_parameter", mode="after")
        def _ensure_paths(cls, v: Path) -> Path:  # noqa: N805
            return Path(v).expanduser().resolve()

    else:  # pragma: no cover
        _fv1 = cast(Any, field_validator)

        @_fv1("export_base_dir", "pbi_base_folder_parameter", pre=True)
        def _ensure_paths_v1(cls, v: Any) -> str:  # noqa: N805
            return str(Path(v).expanduser().resolve())

    def ensure_runtime_dirs(self) -> None:
        """Create necessary runtime directories."""
        for p in (self.export_base_dir, self.pbi_base_folder_parameter):
            Path(p).mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    """Load and prepare settings."""
    env_file = _resolve_env_file()
    _cls = cast(Any, Settings)  # _env_file not in pydantic-generated __init__ stubs
    s: Settings
    if V2:
        s = _cls(_env_file=env_file)
    else:  # pragma: no cover
        s = _cls(_env_file=env_file)
    s.ensure_runtime_dirs()
    return s


settings: Settings = load_settings()
