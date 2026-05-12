"""Custom exception types (Phase 1 scaffold)."""

from __future__ import annotations


class DQTError(Exception):
    """Base error for the Data Quality Toolkit."""


class LoaderError(DQTError):
    """Data loading errors."""


class ValidationError(DQTError):
    """Validation errors."""


class ConfigError(DQTError):
    """Raised when configuration is invalid or missing."""


class ProfileError(DQTError):
    """Raised when profiling fails."""


class AssessmentError(DQTError):
    """Raised when quality assessment fails."""


__all__ = [
    "DQTError",
    "ConfigError",
    "ProfileError",
    "AssessmentError",
    "LoaderError",
    "ValidationError",
]
