"""StoryLens AI adapter — default-OFF environment settings reader.

Reads DQT_STORYLENS_AI_ENABLED and DQT_STORYLENS_MODEL_DIR.
Default: AI disabled. Never mutates environment, never creates directories,
never leaks concrete paths in user-facing reason strings.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_ENV_AI_ENABLED = "DQT_STORYLENS_AI_ENABLED"
_ENV_MODEL_DIR = "DQT_STORYLENS_MODEL_DIR"
_TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True, slots=True)
class AIAvailability:
    """Snapshot of StoryLens AI availability at call time."""

    enabled: bool
    model_dir: Path | None
    reason: str


def read_ai_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Return True only when DQT_STORYLENS_AI_ENABLED is a truthy value.

    Truthy: "1", "true", "yes", "on" (case-insensitive).
    Anything else (empty, unset, "false", "0", garbage) → False.
    """
    if env is None:
        env = os.environ
    val = env.get(_ENV_AI_ENABLED, "").strip().lower()
    return val in _TRUTHY_VALUES


def resolve_model_dir(env: Mapping[str, str] | None = None) -> Path | None:
    """Return the model directory Path when set and it exists locally.

    Returns None when DQT_STORYLENS_MODEL_DIR is unset, empty, or the path
    does not exist. Does not create directories. Does not download anything.
    """
    if env is None:
        env = os.environ
    raw = env.get(_ENV_MODEL_DIR, "").strip()
    if not raw:
        return None
    p = Path(raw)
    if not p.exists():
        return None
    return p


def compute_availability(env: Mapping[str, str] | None = None) -> AIAvailability:
    """Compute full AI availability status from environment.

    The ``reason`` field never contains the concrete model path.
    """
    if not read_ai_enabled(env):
        return AIAvailability(
            enabled=False,
            model_dir=None,
            reason="AI disabled by default",
        )
    model_dir = resolve_model_dir(env)
    if model_dir is None:
        return AIAvailability(
            enabled=False,
            model_dir=None,
            reason="Model directory not set or not found",
        )
    return AIAvailability(
        enabled=True,
        model_dir=model_dir,
        reason="AI available",
    )
