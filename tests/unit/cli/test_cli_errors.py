import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import data_quality_toolkit.adapters.cli.main as cli

_SRC_ROOT = Path(cli.__file__).resolve().parents[3]
# Environment-backed settings aliases, cleared so each test controls them.
_SETTINGS_ENV = (
    "DQT_LOAD_ENV",
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


def _make_fake_parser(exc_to_raise, log_level="INFO", log_format="json", **extra):
    """Return a fake parser object that yields a namespace with a func that raises."""

    class _FakeParser:
        def parse_args(self, argv=None):  # noqa: ARG002
            def _raiser(_args):  # noqa: ANN001
                raise exc_to_raise

            return SimpleNamespace(
                func=_raiser,
                log_level=log_level,
                log_format=log_format,
                **extra,
            )

    return _FakeParser()


@pytest.mark.parametrize(
    "exc, code",
    [
        (FileNotFoundError("nope.csv"), 2),
        (PermissionError("blocked"), 13),
        (UnicodeDecodeError("utf-8", b"\xff", 0, 1, "reason"), 22),
        (ValueError("bad value"), 1),
        # An output-directory option pointed at an existing file is operator
        # input, so it joins the invalid-path category (2) instead of escaping
        # as an uncontrolled traceback.
        (FileExistsError(17, "File exists", "out-target"), 2),
        (NotADirectoryError(20, "Not a directory", "out-target/nested"), 2),
    ],
)
def test_main_exception_mappings(monkeypatch, exc, code, capsys):
    # prevent real logging configuration noise
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    # replace the parser with our fake one
    monkeypatch.setattr(cli, "build_parser", lambda: _make_fake_parser(exc))
    rc = cli.main([])
    stderr = capsys.readouterr().err
    assert rc == code
    assert "Error:" in stderr


def _run_with_exc(monkeypatch, exc, **extra):
    """Drive cli.main() so *exc* escapes the command handler."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "build_parser", lambda: _make_fake_parser(exc, **extra))
    return cli.main([])


def test_existing_file_dir_target_is_bounded_and_redacted(monkeypatch, capsys, tmp_path):
    target = tmp_path / "blocked-target"
    target.write_text("operator file\n", encoding="utf-8")

    rc = _run_with_exc(monkeypatch, FileExistsError(17, "File exists", str(target)))
    captured = capsys.readouterr()

    assert rc == 2
    assert "Traceback" not in captured.err
    assert "as a directory: a file already exists at that path." in captured.err
    assert "Hint:" in captured.err
    # the human surface keeps the basename only, per the CLI redaction convention
    assert "<path:blocked-target>" in captured.err
    assert str(target) not in captured.err
    assert captured.out == ""
    # the conflicting file is reported, never touched
    assert target.read_text(encoding="utf-8") == "operator file\n"


def test_not_a_directory_dir_target_is_bounded(monkeypatch, capsys, tmp_path):
    nested = tmp_path / "blocked-target" / "nested"

    rc = _run_with_exc(monkeypatch, NotADirectoryError(20, "Not a directory", str(nested)))
    captured = capsys.readouterr()

    assert rc == 2
    assert "Traceback" not in captured.err
    assert "a component of the path is an existing file." in captured.err
    assert "<path:nested>" in captured.err


def test_dir_target_json_errors_keeps_structured_code(monkeypatch, capsys, tmp_path):
    target = tmp_path / "blocked-target"

    rc = _run_with_exc(
        monkeypatch, FileExistsError(17, "File exists", str(target)), json_errors=True
    )
    captured = capsys.readouterr()

    assert rc == 2
    assert "Traceback" not in captured.err
    payload = json.loads(captured.err)["error"]
    assert payload["code"] == "INVALID_DIR_TARGET"
    assert payload["exc_type"] == "FileExistsError"
    # the programmatic surface keeps the raw path, like the shared error contract
    assert str(target) in payload["message"]


def test_unexpected_oserror_still_propagates(monkeypatch):
    """Containment stays narrow: an unrelated OSError remains diagnosable."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "build_parser", lambda: _make_fake_parser(OSError("disk failure")))
    with pytest.raises(OSError, match="disk failure"):
        cli.main([])


# --- invalid environment-backed settings ------------------------------------


def _clear_settings_env(monkeypatch):
    for alias in _SETTINGS_ENV:
        monkeypatch.delenv(alias, raising=False)


@pytest.mark.parametrize(
    ("alias", "raw"),
    [
        ("LOG_LEVEL", "VERBOSE"),
        ("LOG_LEVEL", "info"),
        ("MAX_ROWS_IN_MEMORY", "abc"),
        ("DQT_ALLOW_NETWORK", "maybe"),
    ],
)
def test_invalid_env_setting_is_a_bounded_config_error(monkeypatch, capsys, alias, raw):
    _clear_settings_env(monkeypatch)
    monkeypatch.setenv(alias, raw)

    rc = cli.main(["version"])
    captured = capsys.readouterr()

    assert rc == 2  # the invalid-configuration category, as for an invalid dqt.yaml
    assert captured.err.startswith(f"Error: invalid DQT configuration: {alias} ")
    assert "Hint:" in captured.err
    assert "Traceback" not in captured.err
    assert "Input should" not in captured.err
    assert raw not in captured.err
    assert captured.out == ""  # the command never ran: no version, no success output


def test_invalid_dotenv_setting_stops_before_any_export(monkeypatch, capsys, tmp_path):
    _clear_settings_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    dotenv = tmp_path / ".env"
    dotenv.write_text("LOG_FORMAT=yaml\n", encoding="utf-8")
    before = dotenv.read_bytes()
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("id,age\n1,25\n", encoding="utf-8")
    outdir = tmp_path / "out"
    monkeypatch.setenv("DQT_LOAD_ENV", "1")

    rc = cli.main(["export", str(csv_path), "--outdir", str(outdir)])
    captured = capsys.readouterr()

    assert rc == 2
    assert captured.err.startswith("Error: invalid DQT configuration: LOG_FORMAT ")
    assert "Traceback" not in captured.err
    assert "yaml" not in captured.err
    assert captured.out == ""
    assert not outdir.exists()  # no product artifact
    assert dotenv.read_bytes() == before


def test_unexpected_settings_load_error_still_propagates(monkeypatch):
    """Only the settings validation failure is contained; other errors stay visible."""

    def _broken_load():
        raise RuntimeError("settings backend failure")

    monkeypatch.setattr(cli, "load_settings", _broken_load)
    with pytest.raises(RuntimeError, match="settings backend failure"):
        cli.main(["version"])


# The console-script shim: import the CLI module, then call main(). Settings used to
# fail validation during that import, before main() could handle anything.
_CONSOLE_ENTRY = (
    "import sys; from data_quality_toolkit.adapters.cli.main import main; sys.exit(main())"
)


def _run_cli_process(tmp_path, extra_env, *args):
    env = {k: v for k, v in os.environ.items() if k not in _SETTINGS_ENV}
    env.update(extra_env)
    env["PYTHONPATH"] = str(_SRC_ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
        [sys.executable, "-B", "-c", _CONSOLE_ENTRY, *args],
        cwd=str(tmp_path),  # keep any relative default and .env lookup out of the repository
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    ("extra_env", "dotenv_text", "alias", "raw"),
    [
        ({"LOG_LEVEL": "VERBOSE"}, None, "LOG_LEVEL", "VERBOSE"),
        ({"MAX_ROWS_IN_MEMORY": "abc"}, None, "MAX_ROWS_IN_MEMORY", "abc"),
        ({"DQT_ALLOW_NETWORK": "maybe"}, None, "DQT_ALLOW_NETWORK", "maybe"),
        ({"DQT_LOAD_ENV": "1"}, "LOG_FORMAT=yaml\n", "LOG_FORMAT", "yaml"),
    ],
)
def test_invalid_settings_are_contained_on_the_real_startup_path(
    tmp_path, extra_env, dotenv_text, alias, raw
):
    if dotenv_text is not None:
        (tmp_path / ".env").write_text(dotenv_text, encoding="utf-8")
    before = sorted((p.name, p.read_bytes()) for p in tmp_path.iterdir())

    proc = _run_cli_process(tmp_path, extra_env, "--help")

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert proc.stdout == ""
    assert proc.stderr.startswith(f"Error: invalid DQT configuration: {alias} ")
    assert len(proc.stderr.splitlines()) == 2  # one error line and one hint line
    assert "Traceback" not in proc.stderr
    assert "pydantic" not in proc.stderr.lower()
    assert raw not in proc.stderr
    assert sorted((p.name, p.read_bytes()) for p in tmp_path.iterdir()) == before


def test_valid_default_settings_startup_is_unchanged(tmp_path):
    proc = _run_cli_process(tmp_path, {}, "--help")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.startswith("usage: dqt")
    assert "Traceback" not in proc.stderr
    assert list(tmp_path.iterdir()) == []


# --- unsupported CSV encoding names -----------------------------------------

_ENCODING_ERROR = "Error: Unsupported --encoding: not a known text encoding"


def _write_orders_csv(tmp_path, encoding="utf-8"):
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("id,city\n1,Zürich\n2,Café\n", encoding=encoding)
    return csv_path


@pytest.mark.parametrize("command", ["profile", "assess"])
@pytest.mark.parametrize("encoding", ["not-an-encoding", "base64"])
def test_unsupported_encoding_is_a_bounded_operator_error(
    monkeypatch, capsys, tmp_path, command, encoding
):
    _clear_settings_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    csv_path = _write_orders_csv(tmp_path)

    rc = cli.main([command, str(csv_path), "--encoding", encoding])
    captured = capsys.readouterr()

    assert rc == 2  # the invalid operator-input category, not an internal failure
    assert captured.err.startswith(_ENCODING_ERROR)
    assert "Traceback" not in captured.err
    assert "LookupError" not in captured.err
    assert "pydantic" not in captured.err.lower()
    assert encoding not in captured.err
    assert "complete" not in captured.err  # no success summary
    assert captured.out == ""  # no profile/assessment result


@pytest.mark.parametrize("command", ["profile", "assess"])
@pytest.mark.parametrize("encoding", ["not-an-encoding", ""])
def test_unsupported_encoding_never_reads_under_another_encoding(
    monkeypatch, capsys, tmp_path, command, encoding
):
    _clear_settings_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    reads = []
    monkeypatch.setattr(cli, "run_profile", lambda *a, **kw: reads.append(kw))
    monkeypatch.setattr(cli, "run_assessment", lambda *a, **kw: reads.append(kw))
    csv_path = _write_orders_csv(tmp_path)

    rc = cli.main([command, str(csv_path), "--encoding", encoding])

    assert rc == 2
    assert capsys.readouterr().err.startswith(_ENCODING_ERROR)
    assert reads == []  # rejected before any load: no fallback encoding is tried


@pytest.mark.parametrize("command", ["profile", "assess"])
@pytest.mark.parametrize("encoding", ["utf-8", "latin-1"])
def test_supported_encoding_behavior_is_unchanged(monkeypatch, capsys, tmp_path, command, encoding):
    _clear_settings_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    # Non-ASCII bytes: a latin-1 file only loads when latin-1 is really used.
    csv_path = _write_orders_csv(tmp_path, encoding=encoding)

    rc = cli.main([command, str(csv_path), "--encoding", encoding])
    captured = capsys.readouterr()

    assert rc == 0, captured.err
    assert "Traceback" not in captured.err
    result = json.loads(captured.out)
    assert result["meta"]["rows"] == 2
    assert result["meta"]["cols"] == 2


def test_lookup_error_from_a_command_still_propagates(monkeypatch):
    """Containment stays narrow: a LookupError subclass from a handler stays visible."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "build_parser", lambda: _make_fake_parser(KeyError("missing")))
    with pytest.raises(KeyError, match="missing"):
        cli.main([])


@pytest.mark.parametrize("command", ["profile", "assess"])
def test_unsupported_encoding_is_contained_on_the_real_startup_path(tmp_path, command):
    _write_orders_csv(tmp_path)
    before = sorted((p.name, p.read_bytes()) for p in tmp_path.iterdir())

    proc = _run_cli_process(tmp_path, {}, command, "data.csv", "--encoding", "not-an-encoding")

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert proc.stdout == ""
    assert proc.stderr.startswith(_ENCODING_ERROR)
    assert "Traceback" not in proc.stderr
    assert "LookupError" not in proc.stderr
    assert "not-an-encoding" not in proc.stderr
    assert sorted((p.name, p.read_bytes()) for p in tmp_path.iterdir()) == before


def test__safe_text_ascii_fallback(monkeypatch):
    # Force an ASCII-only stdout so '✓' is not encodable
    class _Dummy:
        encoding = "ascii"

    monkeypatch.setattr(cli.sys, "stdout", _Dummy())
    out = cli._safe_text("✓", "[OK]")
    assert out == "[OK]"
