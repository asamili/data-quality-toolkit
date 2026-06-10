"""Phase 6D: minimal project-level configuration via ./dqt.yaml.

Opt-in: when ./dqt.yaml is absent, callers see an empty config and behavior
is unchanged. Only a fixed set of CLI defaults is supported.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from data_quality_toolkit.shared.exceptions import ConfigError

CONFIG_FILENAME = "dqt.yaml"

# v1.9 Top-level keys
SUPPORTED_KEYS: frozenset[str] = frozenset(
    {"null_threshold", "fail_under", "outdir", "dataset", "columns"}
)
_NUMERIC_KEYS: frozenset[str] = frozenset({"null_threshold", "fail_under"})

# v2.0 Rule vocabulary
SUPPORTED_DATASET_KEYS: frozenset[str] = frozenset({"fail_under", "score_field"})
SUPPORTED_COLUMN_RULE_KEYS: frozenset[str] = frozenset(
    {
        "required",
        "critical",
        "null_threshold",
        "high_cardinality_threshold",
        "outlier_threshold",
        "fail_under",
        "unique",
        "dtype",
        "accepted_values",
        "weight",
    }
)

PIPELINE_CONFIG_KEYS: frozenset[str] = frozenset(
    {"run_id", "sessions_root", "extract", "transform", "load", "assess", "manifest"}
)
_PIPELINE_STR_KEYS: frozenset[str] = frozenset(
    {"run_id", "sessions_root", "extract", "transform", "load"}
)
_PIPELINE_BOOL_KEYS: frozenset[str] = frozenset({"assess", "manifest"})

_THRESHOLD_KEYS: frozenset[str] = frozenset(
    {"null_threshold", "high_cardinality_threshold", "outlier_threshold", "fail_under"}
)
_BOOL_KEYS: frozenset[str] = frozenset({"required", "critical", "unique"})


def load_dqt_config(path: str | Path = CONFIG_FILENAME) -> dict[str, Any]:
    """Load ./dqt.yaml from CWD. Returns {} when absent; raises ConfigError on invalid."""
    config_path = Path(path)
    if not config_path.is_file():
        return {}
    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as err:
        raise ConfigError(f"Invalid YAML in {config_path}: {err}") from err
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(
            f"{config_path} must contain a mapping of config keys, got {type(data).__name__}"
        )
    unknown = sorted(k for k in data if k not in SUPPORTED_KEYS)
    if unknown:
        supported = ", ".join(sorted(SUPPORTED_KEYS))
        raise ConfigError(
            f"{config_path} has unknown key(s): {', '.join(unknown)}. Supported keys: {supported}"
        )
    return {k: _validated_top_level(config_path, k, v) for k, v in data.items()}


def _validated_top_level(config_path: Path, key: str, value: Any) -> Any:
    """Validate top-level keys in dqt.yaml."""
    if key in _NUMERIC_KEYS:
        return _validate_threshold(config_path, key, value)
    if key == "outdir":
        return _validate_string(config_path, key, value)
    if key == "dataset":
        return _validate_dataset(config_path, value)
    if key == "columns":
        return _validate_columns(config_path, value)
    return value


def _validate_dataset(config_path: Path, data: Any) -> dict[str, Any]:
    """Validate 'dataset' section."""
    if not isinstance(data, dict):
        raise ConfigError(f"{config_path}: 'dataset' must be a mapping, got {type(data).__name__}")
    unknown = sorted(k for k in data if k not in SUPPORTED_DATASET_KEYS)
    if unknown:
        raise ConfigError(f"{config_path}: 'dataset' has unknown key(s): {', '.join(unknown)}")

    validated: dict[str, Any] = {}
    for k, v in data.items():
        ctx = f"dataset.{k}"
        if k == "fail_under":
            val_f: float = _validate_threshold(config_path, ctx, v)
            validated[k] = val_f
        elif k == "score_field":
            val_s: str = _validate_string(config_path, ctx, v)
            validated[k] = val_s
    return validated


def _validate_columns(config_path: Path, data: Any) -> dict[str, dict[str, Any]]:
    """Validate 'columns' section."""
    if not isinstance(data, dict):
        raise ConfigError(f"{config_path}: 'columns' must be a mapping, got {type(data).__name__}")

    validated: dict[str, dict[str, Any]] = {}
    for col_name, rules in data.items():
        if not isinstance(rules, dict):
            raise ConfigError(
                f"{config_path}: rules for column '{col_name}' must be a mapping, got {type(rules).__name__}"
            )
        unknown = sorted(k for k in rules if k not in SUPPORTED_COLUMN_RULE_KEYS)
        if unknown:
            raise ConfigError(
                f"{config_path}: column '{col_name}' has unknown rule key(s): {', '.join(unknown)}"
            )
        validated[col_name] = _validate_column_rules(config_path, col_name, rules)
    return validated


def _validate_column_rules(
    config_path: Path, col_name: str, rules: dict[str, Any]
) -> dict[str, Any]:
    """Validate individual column rule set."""
    validated: dict[str, Any] = {}
    for k, v in rules.items():
        ctx = f"columns.{col_name}.{k}"
        if k in _THRESHOLD_KEYS:
            val_f: float = _validate_threshold(config_path, ctx, v)
            validated[k] = val_f
        elif k in _BOOL_KEYS:
            val_b: bool = _validate_bool(config_path, ctx, v)
            validated[k] = val_b
        elif k == "weight":
            val_w: float = _validate_weight(config_path, ctx, v)
            validated[k] = val_w
        elif k == "dtype":
            val_s: str = _validate_string(config_path, ctx, v)
            validated[k] = val_s
        elif k == "accepted_values":
            val_l: list[Any] = _validate_list(config_path, ctx, v)
            validated[k] = val_l
    return validated


def _validate_threshold(config_path: Path, ctx: str, value: Any) -> float:
    """Validate a 0.0-1.0 float threshold."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"{config_path}: '{ctx}' must be a number, got {type(value).__name__}")
    val_f = float(value)
    if not (0.0 <= val_f <= 1.0):
        raise ConfigError(f"{config_path}: '{ctx}' must be between 0.0 and 1.0, got {val_f}")
    return val_f


def _validate_bool(config_path: Path, ctx: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{config_path}: '{ctx}' must be a boolean, got {type(value).__name__}")
    return value


def _validate_weight(config_path: Path, ctx: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"{config_path}: '{ctx}' must be a number, got {type(value).__name__}")
    if value <= 0:
        raise ConfigError(f"{config_path}: '{ctx}' must be greater than 0, got {value}")
    return float(value)


def _validate_string(config_path: Path, ctx: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{config_path}: '{ctx}' must be a string, got {type(value).__name__}")
    return value


def _validate_list(config_path: Path, ctx: str, value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ConfigError(f"{config_path}: '{ctx}' must be a list, got {type(value).__name__}")
    return value


def load_pipeline_config(path: str | Path) -> dict[str, Any]:
    """Load a pipeline.yaml explicitly given by --config. Raises ConfigError when absent or invalid."""
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"Pipeline config not found: {config_path}")
    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as err:
        raise ConfigError(f"Invalid YAML in {config_path}: {err}") from err
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{config_path} must be a mapping, got {type(data).__name__}")
    unknown = sorted(k for k in data if k not in PIPELINE_CONFIG_KEYS)
    if unknown:
        supported = ", ".join(sorted(PIPELINE_CONFIG_KEYS))
        raise ConfigError(
            f"{config_path} has unknown key(s): {', '.join(unknown)}. Supported: {supported}"
        )
    for k in _PIPELINE_STR_KEYS:
        if k in data and not isinstance(data[k], str):
            raise ConfigError(
                f"{config_path}: '{k}' must be a string, got {type(data[k]).__name__}"
            )
    for k in _PIPELINE_BOOL_KEYS:
        if k in data and not isinstance(data[k], bool):
            raise ConfigError(
                f"{config_path}: '{k}' must be a boolean, got {type(data[k]).__name__}"
            )
    return data


__all__ = [
    "CONFIG_FILENAME",
    "SUPPORTED_KEYS",
    "PIPELINE_CONFIG_KEYS",
    "load_dqt_config",
    "load_pipeline_config",
]
