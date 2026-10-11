from __future__ import annotations

import os
from pathlib import Path
from typing import Any, ClassVar, Literal, cast, get_args, get_origin  # ClassVar + cast

# Settings construction raises pydantic's ValidationError for a rejected value; the
# alias names that one failure for callers that report it (e.g. the dqt CLI).
from pydantic import ValidationError as SettingsValidationError

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

    # Security / feature flags
    dqt_allow_network: bool = Field(False, validation_alias="DQT_ALLOW_NETWORK")

    # Lineage / manifest (declared for type-checker visibility)
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
        """Create the configured runtime directories.

        This is the explicit mutation boundary for output directories: it is the
        only settings operation that touches the filesystem. Constructing or
        reading settings never creates directories; callers that are about to
        write invoke this (or create their own output parents, as the CSV
        exporter and SQLite schema helper already do). Idempotent.
        """
        for p in (self.export_base_dir, self.pbi_base_folder_parameter):
            Path(p).mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    """Load settings from the environment.

    Read-only and filesystem-pure: it creates no directories. Call
    :meth:`Settings.ensure_runtime_dirs` explicitly when a write needs them.
    """
    env_file = _resolve_env_file()
    _cls = cast(Any, Settings)  # _env_file not in pydantic-generated __init__ stubs
    s: Settings
    if V2:
        s = _cls(_env_file=env_file)
    else:  # pragma: no cover
        s = _cls(_env_file=env_file)
    return s


def _accepted_values(annotation: Any) -> str:
    """Describe what a settings field accepts, from its annotation alone."""
    if get_origin(annotation) is Literal:
        return "must be one of: " + ", ".join(str(v) for v in get_args(annotation))
    if annotation is bool:
        return "must be a boolean (true or false)"
    if annotation is int:
        return "must be an integer"
    return "has an invalid value"


def describe_invalid_settings(exc: SettingsValidationError) -> str:
    """Summarize a settings validation failure for an operator, without its input.

    Each rejected setting is named by its environment variable and paired with
    what it accepts, derived from the ``Settings`` model. The supplied value and
    pydantic's own rendering of the error are deliberately left out, so a value
    placed in the wrong variable (a secret, for instance) is never echoed.
    """
    fields = Settings.model_fields
    field_by_alias = {str(info.validation_alias): name for name, info in fields.items()}
    problems: list[str] = []
    for error in exc.errors():
        loc = error.get("loc") or ()
        alias = str(loc[0]) if loc else ""
        field = field_by_alias.get(alias)
        if field is None:
            problem = "a DQT setting has an invalid value"
        else:
            problem = f"{alias} {_accepted_values(fields[field].annotation)}"
        if problem not in problems:
            problems.append(problem)
    return "; ".join(problems)


# The shared instance is built on first access rather than at import, so importing
# this module never validates the environment. An invalid value then surfaces where
# settings are first needed -- for the dqt CLI, inside main()'s operator-facing error
# handling -- instead of as a traceback while an import graph is still loading.
settings: Settings  # provided by __getattr__ below
_shared_settings: Settings | None = None


def __getattr__(name: str) -> Settings:
    """Build the shared ``settings`` instance once, on first access (PEP 562)."""
    global _shared_settings
    if name != "settings":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if _shared_settings is None:
        _shared_settings = load_settings()
    return _shared_settings
