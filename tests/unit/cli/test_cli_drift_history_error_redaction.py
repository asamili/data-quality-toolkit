# tests/unit/cli/test_cli_drift_history_error_redaction.py
"""Human-facing drift-history CLI errors route through the shared path redactor.

Covers every ``commands/drift_history.py`` handler that catches an exception and
prints it (``notify``, ``export-xlsx``, ``plot``, ``export-duckdb``). Each backend
proxy is faked to raise its real exception type carrying a synthetic absolute
path; stderr must keep the error wording and the basename but drop the private
parent directories. Exit code 1 and the empty stdout are asserted unchanged.
"""

from __future__ import annotations

import ast
import inspect

import pytest

import data_quality_toolkit.adapters.cli.main as cli
from data_quality_toolkit.adapters.cli.commands import drift_history
from data_quality_toolkit.adapters.exporters.bi.duckdb_exporter import DuckdbExportError
from data_quality_toolkit.adapters.exporters.bi.xlsx_drift_exporter import XlsxExportError
from data_quality_toolkit.adapters.exporters.viz.drift_plots import PlotExportError
from data_quality_toolkit.shared.exceptions import NotificationError

# Synthetic fixtures only: no real user, host, or runtime location.
WIN_PRIVATE_PATH = r"C:\Users\example_user\private_runtime\drift.db"
POSIX_PRIVATE_PATH = "/home/example_user/private_runtime/drift.db"
_PRIVATE_FRAGMENTS = ("example_user", "private_runtime", "Users", "/home", "C:\\")

# (subcommand argv, cli proxy attribute, exception type the real backend raises)
_COMMANDS = [
    pytest.param(
        ["notify", "--db", "m.db", "--webhook-url", "https://hooks.example.com/x"],
        "send_drift_notification",
        NotificationError,
        id="notify",
    ),
    pytest.param(
        ["export-xlsx", "--db", "m.db", "--out", "drift.xlsx"],
        "export_drift_history_xlsx",
        XlsxExportError,
        id="export-xlsx",
    ),
    pytest.param(
        ["plot", "--db", "m.db", "--out", "plots"],
        "export_drift_plots",
        PlotExportError,
        id="plot",
    ),
    pytest.param(
        ["export-duckdb", "--db", "m.db", "--out", "mirror.duckdb"],
        "export_monitoring_duckdb",
        DuckdbExportError,
        id="export-duckdb",
    ),
]

_SAFE_MESSAGES = [
    "Output path must end with .xlsx, got: out.csv",
    "real webhook send refused: network is disabled",
    "webhook returned HTTP 500 for https://hooks.example.com/x",
    "Unknown chart 'pie'. Supported: drift-rate, psi-by-column, top-drifted, all.",
]

_ALREADY_REDACTED = [
    "Output file already exists; pass --force to overwrite: <path:drift.db>",
    "Output path is an existing directory: [path redacted]",
    "Failed to write plot to drift_rate.png: disk full",
]


def _run_failing(monkeypatch, capsys, argv, proxy, exc):
    def boom(*_a, **_k):
        raise exc

    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, proxy, boom)
    rc = cli.main(["drift-history", *argv])
    return rc, capsys.readouterr()


def _error_lines(err: str) -> list[str]:
    return [line for line in err.splitlines() if line.startswith("Error:")]


@pytest.mark.parametrize(("argv", "proxy", "exc_type"), _COMMANDS)
def test_windows_path_redacted(monkeypatch, capsys, argv, proxy, exc_type):
    exc = exc_type(f"Failed to open source database read-only: {WIN_PRIVATE_PATH} (disk I/O error)")
    rc, out = _run_failing(monkeypatch, capsys, argv, proxy, exc)

    assert rc == 1
    assert out.out == ""
    assert _error_lines(out.err) == [
        "Error: Failed to open source database read-only: <path:drift.db> (disk I/O error)"
    ]
    assert WIN_PRIVATE_PATH not in out.err
    for fragment in _PRIVATE_FRAGMENTS:
        assert fragment not in out.err


@pytest.mark.parametrize(("argv", "proxy", "exc_type"), _COMMANDS)
def test_posix_path_redacted(monkeypatch, capsys, argv, proxy, exc_type):
    exc = exc_type(f"Output file already exists; pass --force to overwrite: {POSIX_PRIVATE_PATH}")
    rc, out = _run_failing(monkeypatch, capsys, argv, proxy, exc)

    assert rc == 1
    assert out.out == ""
    assert _error_lines(out.err) == [
        "Error: Output file already exists; pass --force to overwrite: <path:drift.db>"
    ]
    for fragment in _PRIVATE_FRAGMENTS:
        assert fragment not in out.err


@pytest.mark.parametrize(("argv", "proxy", "exc_type"), _COMMANDS)
def test_chained_os_error_repr_path_redacted(monkeypatch, capsys, argv, proxy, exc_type):
    """``str(OSError)`` renders the filename via repr (doubled backslashes)."""
    os_err = PermissionError(13, "Permission denied", WIN_PRIVATE_PATH)
    exc = exc_type(f"Failed to write output to {WIN_PRIVATE_PATH}: {os_err}")
    rc, out = _run_failing(monkeypatch, capsys, argv, proxy, exc)

    assert rc == 1
    assert _error_lines(out.err) == [
        "Error: Failed to write output to <path:drift.db>: "
        "[Errno 13] Permission denied: '<path:drift.db>'"
    ]
    for fragment in _PRIVATE_FRAGMENTS:
        assert fragment not in out.err


@pytest.mark.parametrize("message", _SAFE_MESSAGES)
@pytest.mark.parametrize(("argv", "proxy", "exc_type"), _COMMANDS)
def test_safe_message_kept_verbatim(monkeypatch, capsys, argv, proxy, exc_type, message):
    rc, out = _run_failing(monkeypatch, capsys, argv, proxy, exc_type(message))

    assert rc == 1
    assert _error_lines(out.err) == [f"Error: {message}"]
    assert "<path" not in out.err


@pytest.mark.parametrize("message", _ALREADY_REDACTED)
@pytest.mark.parametrize(("argv", "proxy", "exc_type"), _COMMANDS)
def test_already_redacted_message_not_mangled(monkeypatch, capsys, argv, proxy, exc_type, message):
    rc, out = _run_failing(monkeypatch, capsys, argv, proxy, exc_type(message))

    assert rc == 1
    assert _error_lines(out.err) == [f"Error: {message}"]


def test_no_handler_renders_a_raw_exception():
    """Each ``except ... as name`` body uses ``name`` only through the redactor."""
    tree = ast.parse(inspect.getsource(drift_history))
    handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler) and n.name]
    assert len(handlers) == 4

    for handler in handlers:
        redacted_args = {
            id(arg)
            for call in ast.walk(handler)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "_redact_cli_paths"
            for arg in call.args
        }
        uses = [
            node
            for node in ast.walk(handler)
            if isinstance(node, ast.Name) and node.id == handler.name
        ]
        assert uses, f"handler at line {handler.lineno} never renders {handler.name}"
        for node in uses:
            assert (
                id(node) in redacted_args
            ), f"line {node.lineno}: '{handler.name}' rendered without _redact_cli_paths"


# --- R7A3B2-R1: absolute paths containing whitespace -----------------------

WIN_SPACED_PATH = r"C:\Users\example user\private runtime\drift.db"
POSIX_SPACED_PATH = "/home/example user/private runtime/drift.db"
_SPACED_FRAGMENTS = ("example user", "private runtime", "Users", "/home", "C:\\")


@pytest.mark.parametrize(("argv", "proxy", "exc_type"), _COMMANDS)
def test_windows_spaced_path_redacted(monkeypatch, capsys, argv, proxy, exc_type):
    exc = exc_type(f"Failed to write output to {WIN_SPACED_PATH} (disk I/O error)")
    rc, out = _run_failing(monkeypatch, capsys, argv, proxy, exc)

    assert rc == 1
    assert out.out == ""
    assert _error_lines(out.err) == [
        "Error: Failed to write output to <path:drift.db> (disk I/O error)"
    ]
    for fragment in _SPACED_FRAGMENTS:
        assert fragment not in out.err


@pytest.mark.parametrize(("argv", "proxy", "exc_type"), _COMMANDS)
def test_posix_spaced_path_redacted(monkeypatch, capsys, argv, proxy, exc_type):
    exc = exc_type(f"Failed to write output to {POSIX_SPACED_PATH}: permission denied")
    rc, out = _run_failing(monkeypatch, capsys, argv, proxy, exc)

    assert rc == 1
    assert _error_lines(out.err) == [
        "Error: Failed to write output to <path:drift.db>: permission denied"
    ]
    for fragment in _SPACED_FRAGMENTS:
        assert fragment not in out.err


@pytest.mark.parametrize(("argv", "proxy", "exc_type"), _COMMANDS)
def test_spaced_filename_keeps_command_wording(monkeypatch, capsys, argv, proxy, exc_type):
    exc = exc_type(
        "Output file already exists; pass --force to overwrite: "
        r"C:\Users\example user\out file.xlsx"
    )
    rc, out = _run_failing(monkeypatch, capsys, argv, proxy, exc)

    assert rc == 1
    assert _error_lines(out.err) == [
        "Error: Output file already exists; pass --force to overwrite: <path:out file.xlsx>"
    ]
    for fragment in _SPACED_FRAGMENTS:
        assert fragment not in out.err
