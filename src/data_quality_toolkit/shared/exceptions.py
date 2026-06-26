"""Custom exception types (Phase 1 scaffold)."""

from __future__ import annotations

from typing import Any


class DQTError(Exception):
    """Base error for the Data Quality Toolkit."""

    def __init__(
        self,
        message: str = "",
        *,
        hint: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.hint = hint
        self.metadata = metadata


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


class NotificationError(DQTError):
    """Raised when a webhook notification cannot be built or delivered."""


class WebhookSecurityError(NotificationError):
    """Raised when a webhook URL fails security validation (scheme / host / SSRF guard)."""


__all__ = [
    "DQTError",
    "ConfigError",
    "ProfileError",
    "AssessmentError",
    "LoaderError",
    "ValidationError",
    "NotificationError",
    "WebhookSecurityError",
]
