from pathlib import Path

from data_quality_toolkit.shared.constants import DEFAULT_MAX_ROWS_IN_MEMORY, DEFAULT_SAMPLE_SIZE
from data_quality_toolkit.shared.settings import load_settings

_LIVE_ENV_ALIASES = (
    "MAX_ROWS_IN_MEMORY",
    "SAMPLE_SIZE",
    "LOG_LEVEL",
    "LOG_FORMAT",
    "EXPORT_BASE_DIR",
    "PBI_BASE_FOLDER_PARAMETER",
    "DQT_ALLOW_NETWORK",
    "SERDE_IMPL",
    "JSON_WRITER",
    "LINEAGE_SCHEMA_VERSION",
    "MANIFEST_FILE",
)
# Removed LLM/SSOT leftovers: declared, but never read by any production code.
_REMOVED_LEGACY_FIELDS = {
    "api_key": "API_KEY",
    "lorax_base_url": "LORAX_BASE_URL",
    "lorax_timeout_secs": "LORAX_TIMEOUT_SECS",
}


def _clear_settings_env(monkeypatch):
    monkeypatch.delenv("DQT_LOAD_ENV", raising=False)
    for alias in _LIVE_ENV_ALIASES:
        monkeypatch.delenv(alias, raising=False)


def test_load_settings_env_file_and_types(tmp_path, monkeypatch):
    # Override a couple of envs at runtime to prove precedence & typing
    monkeypatch.setenv("MAX_ROWS_IN_MEMORY", "123")
    monkeypatch.setenv("DQT_ALLOW_NETWORK", "false")  # bool parsing
    monkeypatch.setenv("EXPORT_BASE_DIR", str(tmp_path / "out"))
    s = load_settings()

    assert s.max_rows_in_memory == 123
    assert s.dqt_allow_network is False
    assert s.export_base_dir == (tmp_path / "out").resolve()
    # loading settings is filesystem-pure: the configured path is resolved but
    # never created. Creation belongs to ensure_runtime_dirs() and to writers.
    assert not Path(s.export_base_dir).exists()


def test_defaults_and_literals():
    s = load_settings()
    assert s.log_level in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    assert s.log_format in {"json", "text"}


def test_reading_settings_values_creates_no_directories(tmp_path, monkeypatch):
    """Reading configuration must not touch the filesystem."""
    export_dir = tmp_path / "read_only_export"
    pbi_dir = tmp_path / "read_only_pbi"
    monkeypatch.setenv("EXPORT_BASE_DIR", str(export_dir))
    monkeypatch.setenv("PBI_BASE_FOLDER_PARAMETER", str(pbi_dir))

    assert not export_dir.exists()
    assert not pbi_dir.exists()

    s = load_settings()
    # representative read-only accesses across scalar and path fields
    assert s.log_level in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    assert s.export_base_dir == export_dir.resolve()
    assert s.pbi_base_folder_parameter == pbi_dir.resolve()

    assert not export_dir.exists()
    assert not pbi_dir.exists()


def test_live_settings_defaults_are_unchanged(tmp_path, monkeypatch):
    """The full field set and every default: nothing live moved, nothing dead remains."""
    _clear_settings_env(monkeypatch)
    monkeypatch.chdir(tmp_path)  # anchor the relative "./dist" defaults

    s = load_settings()

    assert dict(s) == {
        "max_rows_in_memory": DEFAULT_MAX_ROWS_IN_MEMORY,
        "sample_size": DEFAULT_SAMPLE_SIZE,
        "log_level": "INFO",
        "log_format": "json",
        "export_base_dir": (tmp_path / "dist").resolve(),
        "pbi_base_folder_parameter": (tmp_path / "dist").resolve(),
        "dqt_allow_network": False,
        "serde_impl": "pydantic",
        "json_writer": "json",
        "lineage_schema_version": "1.0.0",
        "manifest_file": "artifacts.json",
    }
    assert not (tmp_path / "dist").exists()


def test_removed_legacy_fields_are_gone_and_stale_env_is_ignored(monkeypatch):
    _clear_settings_env(monkeypatch)
    for alias in _REMOVED_LEGACY_FIELDS.values():
        monkeypatch.setenv(alias, "stale-legacy-value")

    s = load_settings()  # a stale variable must neither fail loading nor surface

    exposed = dict(s)
    for field in _REMOVED_LEGACY_FIELDS:
        assert field not in exposed
        assert not hasattr(s, field)
    assert "stale-legacy-value" not in repr(exposed)
