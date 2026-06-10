import tempfile
from pathlib import Path
from typing import Any


def _collect_versions() -> dict[str, str]:
    # Placeholder for actual version collection logic
    return {"version": "0.1.0"}


def _collect_settings_snapshot() -> dict[str, Any]:
    # Placeholder. Redaction logic needed here if sensitive data is accessed
    return {"some_setting": "value", "api_key": "REDACTED", "secret_token": "REDACTED"}


def _load_project_config() -> dict[str, Any]:
    return {}


def _collect_import_diagnostics() -> dict[str, Any]:
    return {"imports": "ok"}


def _probe_writable_dir(path_str: str) -> tuple[bool, str | None]:
    path = Path(path_str)
    if not path.exists() or not path.is_dir():
        return False, f"Directory not found: {path}"

    try:
        # Probe by creating a temp file and deleting it
        with tempfile.NamedTemporaryFile(dir=path, delete=True):
            return True, None
    except Exception as e:
        return False, str(e)
