import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest

import data_quality_toolkit.shared.settings as settings_module
from data_quality_toolkit.shared.settings import (
    Settings,
    SettingsValidationError,
    describe_invalid_settings,
    load_settings,
)

_SRC_ROOT = Path(settings_module.__file__).resolve().parents[2]
_ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"
_ACTIVE_ENTRY = re.compile(r"([A-Z][A-Z0-9_]*)=(\S*)")
_COMMENTED_ENTRY = re.compile(r"# ?([A-Z][A-Z0-9_]*)=(\S*)")

# Live environment alias -> (Settings field, non-default raw value, parsed value).
_LIVE_ENV_CONTRACT: dict[str, tuple[str, str, object]] = {
    "MAX_ROWS_IN_MEMORY": ("max_rows_in_memory", "4321", 4321),
    "SAMPLE_SIZE": ("sample_size", "77", 77),
    "LOG_LEVEL": ("log_level", "DEBUG", "DEBUG"),
    "LOG_FORMAT": ("log_format", "text", "text"),
    "DQT_ALLOW_NETWORK": ("dqt_allow_network", "true", True),
    "SERDE_IMPL": ("serde_impl", "msgspec", "msgspec"),
    "JSON_WRITER": ("json_writer", "orjson", "orjson"),
    "LINEAGE_SCHEMA_VERSION": ("lineage_schema_version", "9.9.9", "9.9.9"),
    "MANIFEST_FILE": ("manifest_file", "custom_manifest.json", "custom_manifest.json"),
}
# Path aliases; their mapping is covered by the directory tests below.
_PATH_ALIASES = {
    "EXPORT_BASE_DIR": "export_base_dir",
    "PBI_BASE_FOLDER_PARAMETER": "pbi_base_folder_parameter",
}
# The operator template: behaviour-neutral active entries, plus examples left
# commented because merely setting them in the real environment changes behaviour.
_ENV_EXAMPLE_ACTIVE = {
    "MAX_ROWS_IN_MEMORY",
    "LOG_LEVEL",
    "LOG_FORMAT",
    "EXPORT_BASE_DIR",
    "DQT_ALLOW_NETWORK",
    "SERDE_IMPL",
    "JSON_WRITER",
}
_ENV_EXAMPLE_COMMENTED = {"SAMPLE_SIZE"}

_IMPORT_PROBE = """import os
from pathlib import Path

target_export = Path(os.environ["EXPORT_BASE_DIR"])
target_pbi = Path(os.environ["PBI_BASE_FOLDER_PARAMETER"])
assert not target_export.exists(), "export dir existed before import"
assert not target_pbi.exists(), "pbi dir existed before import"

from data_quality_toolkit.shared.settings import settings

assert settings.export_base_dir == target_export.resolve(), settings.export_base_dir
assert not target_export.exists(), "import created the export dir"
assert not target_pbi.exists(), "import created the pbi dir"
print("IMPORT_PURE")
"""


def test_load_settings_respects_env_and_does_not_create_dirs(monkeypatch, tmp_path):
    # point export dirs to tmp and override sizing envs
    monkeypatch.setenv("SAMPLE_SIZE", "123")
    monkeypatch.setenv("MAX_ROWS_IN_MEMORY", "456")
    monkeypatch.setenv("EXPORT_BASE_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("PBI_BASE_FOLDER_PARAMETER", str(tmp_path / "pbi_param"))

    s = load_settings()

    # env overrides applied
    assert s.sample_size == 123
    assert s.max_rows_in_memory == 456

    # paths are expanded + resolved, but loading settings creates nothing:
    # directory creation is owned by ensure_runtime_dirs() and by writers.
    assert s.export_base_dir == (tmp_path / "out").resolve()
    assert s.pbi_base_folder_parameter == (tmp_path / "pbi_param").resolve()
    assert not s.export_base_dir.exists()
    assert not s.pbi_base_folder_parameter.exists()

    # sanity defaults still present
    assert s.log_format in {"json", "text"}
    # clean up env side effects for other tests
    for k in ("SAMPLE_SIZE", "MAX_ROWS_IN_MEMORY", "EXPORT_BASE_DIR", "PBI_BASE_FOLDER_PARAMETER"):
        os.environ.pop(k, None)


def test_ensure_runtime_dirs_creates_configured_dirs_and_is_idempotent(monkeypatch, tmp_path):
    """Explicit preparation is the only settings operation that mutates disk."""
    export_dir = tmp_path / "nested" / "out"
    pbi_dir = tmp_path / "nested" / "pbi_param"
    monkeypatch.setenv("EXPORT_BASE_DIR", str(export_dir))
    monkeypatch.setenv("PBI_BASE_FOLDER_PARAMETER", str(pbi_dir))

    s = load_settings()
    assert not export_dir.exists()
    assert not pbi_dir.exists()

    s.ensure_runtime_dirs()

    assert export_dir.is_dir()
    assert pbi_dir.is_dir()

    # repeated preparation stays safe (exist_ok) and preserves existing content
    marker = export_dir / "keep.txt"
    marker.write_text("kept", encoding="utf-8")
    s.ensure_runtime_dirs()
    assert export_dir.is_dir()
    assert pbi_dir.is_dir()
    assert marker.read_text(encoding="utf-8") == "kept"


def test_importing_settings_module_creates_no_dirs(tmp_path):
    """A fresh interpreter importing the module must not touch the filesystem."""
    export_dir = tmp_path / "fresh_export"
    pbi_dir = tmp_path / "fresh_pbi"

    env = dict(os.environ)
    env.pop("DQT_LOAD_ENV", None)
    env["EXPORT_BASE_DIR"] = str(export_dir)
    env["PBI_BASE_FOLDER_PARAMETER"] = str(pbi_dir)
    env["PYTHONPATH"] = str(_SRC_ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
        [sys.executable, "-B", "-c", _IMPORT_PROBE],
        cwd=str(tmp_path),  # keep any relative default out of the repository
        env=env,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "IMPORT_PURE" in proc.stdout
    assert not export_dir.exists()
    assert not pbi_dir.exists()


_INVALID_ENV_IMPORT_PROBE = """import data_quality_toolkit.shared.settings as settings_module

print("IMPORTED")
try:
    settings_module.settings
except settings_module.SettingsValidationError:
    print("ACCESS_REJECTED")
else:
    print("ACCESS_ACCEPTED")
"""


def test_importing_settings_module_does_not_validate_the_environment(tmp_path):
    """Import is validation-free; the shared instance still rejects a bad value on access."""
    env = dict(os.environ)
    env.pop("DQT_LOAD_ENV", None)
    env["LOG_LEVEL"] = "VERBOSE"
    env["PYTHONPATH"] = str(_SRC_ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
        [sys.executable, "-B", "-c", _INVALID_ENV_IMPORT_PROBE],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.split() == ["IMPORTED", "ACCESS_REJECTED"]


def test_shared_settings_instance_is_built_once(monkeypatch):
    _clear_settings_env(monkeypatch)
    from data_quality_toolkit.shared.settings import settings

    assert isinstance(settings, Settings)
    assert settings_module.settings is settings
    with pytest.raises(AttributeError):
        settings_module.not_a_setting


# (environment variable, rejected raw value, expected accepted-values wording)
_INVALID_ENV_CASES = [
    ("LOG_LEVEL", "VERBOSE", "must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL"),
    ("LOG_LEVEL", "info", "must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL"),
    ("MAX_ROWS_IN_MEMORY", "abc", "must be an integer"),
    ("DQT_ALLOW_NETWORK", "maybe", "must be a boolean (true or false)"),
    ("LOG_FORMAT", "yaml", "must be one of: json, text"),
]


@pytest.mark.parametrize(("alias", "raw", "accepted"), _INVALID_ENV_CASES)
def test_invalid_env_value_is_rejected_and_described_without_the_value(
    monkeypatch, alias, raw, accepted
):
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv(alias, raw)

    with pytest.raises(SettingsValidationError) as excinfo:
        load_settings()  # an invalid value is never replaced by the default

    summary = describe_invalid_settings(excinfo.value)
    assert summary == f"{alias} {accepted}"
    assert raw not in summary
    assert "Input should" not in summary  # pydantic's own rendering stays out


def test_invalid_dotenv_value_is_rejected_on_opt_in_and_described(monkeypatch, tmp_path):
    _clear_settings_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    dotenv = tmp_path / ".env"
    dotenv.write_text("LOG_FORMAT=yaml\n", encoding="utf-8")
    before = dotenv.read_bytes()

    assert load_settings().log_format == "json"  # no opt-in: .env is never read
    monkeypatch.setenv("DQT_LOAD_ENV", "1")
    with pytest.raises(SettingsValidationError) as excinfo:
        load_settings()

    summary = describe_invalid_settings(excinfo.value)
    assert summary == "LOG_FORMAT must be one of: json, text"
    assert "yaml" not in summary
    assert dotenv.read_bytes() == before


def test_several_invalid_values_are_each_named_once(monkeypatch):
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv("MAX_ROWS_IN_MEMORY", "abc")
    monkeypatch.setenv("DQT_ALLOW_NETWORK", "maybe")

    with pytest.raises(SettingsValidationError) as excinfo:
        load_settings()

    summary = describe_invalid_settings(excinfo.value)
    assert summary.split("; ") == [
        "MAX_ROWS_IN_MEMORY must be an integer",
        "DQT_ALLOW_NETWORK must be a boolean (true or false)",
    ]
    assert "abc" not in summary
    assert "maybe" not in summary


def _clear_settings_env(monkeypatch):
    monkeypatch.delenv("DQT_LOAD_ENV", raising=False)
    for alias in (*_LIVE_ENV_CONTRACT, *_PATH_ALIASES):
        monkeypatch.delenv(alias, raising=False)


def _env_example_entries() -> tuple[dict[str, str], dict[str, str]]:
    if not _ENV_EXAMPLE.is_file():
        pytest.skip("the private .env.example template is not present in this tree")
    active: dict[str, str] = {}
    commented: dict[str, str] = {}
    for line in _ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        if m := _ACTIVE_ENTRY.fullmatch(line):
            assert m[1] not in active, f"duplicate entry {m[1]}"
            active[m[1]] = m[2]
        elif m := _COMMENTED_ENTRY.fullmatch(line):
            commented[m[1]] = m[2]
        else:
            assert not line or line.startswith("#"), f"unparseable line: {line!r}"
    return active, commented


@pytest.mark.parametrize(
    ("alias", "field", "raw", "expected"),
    [(alias, *spec) for alias, spec in _LIVE_ENV_CONTRACT.items()],
)
def test_live_env_alias_maps_to_its_field(monkeypatch, alias, field, raw, expected):
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv(alias, raw)
    assert getattr(load_settings(), field) == expected


def test_env_example_documents_only_live_settings_aliases():
    active, commented = _env_example_entries()
    assert set(active) == _ENV_EXAMPLE_ACTIVE
    assert set(commented) == _ENV_EXAMPLE_COMMENTED
    assert set(active) | set(commented) <= set(_LIVE_ENV_CONTRACT) | set(_PATH_ALIASES)


def test_env_example_values_restate_the_settings_defaults(monkeypatch, tmp_path):
    """An unedited copy, commented examples included, changes no setting."""
    active, commented = _env_example_entries()
    _clear_settings_env(monkeypatch)
    monkeypatch.chdir(tmp_path)  # relative paths resolve identically on both sides
    defaults = dict(load_settings())
    uncommented = tmp_path / "uncommented.env"
    uncommented.write_text("".join(f"{k}={v}\n" for k, v in commented.items()), encoding="utf-8")
    field_of = {alias: spec[0] for alias, spec in _LIVE_ENV_CONTRACT.items()} | _PATH_ALIASES

    for env_file, entries in ((_ENV_EXAMPLE, active), (uncommented, commented)):
        loaded = dict(cast(Any, Settings)(_env_file=str(env_file)))
        for alias in entries:
            assert loaded[field_of[alias]] == defaults[field_of[alias]], alias
    assert not (tmp_path / "dist").exists()


def test_dotenv_copy_is_read_only_on_opt_in_and_real_env_wins(monkeypatch, tmp_path):
    _env_example_entries()
    _clear_settings_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    text = _ENV_EXAMPLE.read_text(encoding="utf-8")
    edited = text.replace("\nLOG_LEVEL=INFO\n", "\nLOG_LEVEL=DEBUG\n")
    assert edited != text
    (tmp_path / ".env").write_text(edited, encoding="utf-8")

    assert load_settings().log_level == "INFO"  # no opt-in: .env is never read
    monkeypatch.setenv("DQT_LOAD_ENV", "1")
    assert load_settings().log_level == "DEBUG"  # opt-in: the .env copy is read
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    assert load_settings().log_level == "WARNING"  # the real environment wins
