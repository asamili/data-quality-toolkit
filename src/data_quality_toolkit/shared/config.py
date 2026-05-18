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
SUPPORTED_KEYS: frozenset[str] = frozenset({"null_threshold", "fail_under", "outdir"})
_NUMERIC_KEYS: frozenset[str] = frozenset({"null_threshold", "fail_under"})


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
            f"{config_path} must contain a mapping of config keys, " f"got {type(data).__name__}"
        )
    unknown = sorted(k for k in data if k not in SUPPORTED_KEYS)
    if unknown:
        supported = ", ".join(sorted(SUPPORTED_KEYS))
        raise ConfigError(
            f"{config_path} has unknown key(s): {', '.join(unknown)}. "
            f"Supported keys: {supported}"
        )
    return {k: _validated(config_path, k, v) for k, v in data.items()}


def _validated(config_path: Path, key: str, value: Any) -> Any:
    if key in _NUMERIC_KEYS:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ConfigError(
                f"{config_path}: '{key}' must be a number, " f"got {type(value).__name__}"
            )
        return float(value)
    if not isinstance(value, str):
        raise ConfigError(
            f"{config_path}: '{key}' must be a string, " f"got {type(value).__name__}"
        )
    return value


__all__ = ["CONFIG_FILENAME", "SUPPORTED_KEYS", "load_dqt_config"]
