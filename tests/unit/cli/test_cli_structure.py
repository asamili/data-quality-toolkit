"""Structure & compatibility tests for the v2.6.0 CLI package split.

These assert the modular layout (``adapters/cli/commands`` + ``adapters/cli/utils``)
without changing any public CLI behavior: every command module exposes a
``register*`` entry point, ``build_parser`` still wires the full command set, the
frozen ``cli.main`` attribute surface (proxies + shared helpers + handlers) is
intact, and importing the CLI never drags in Streamlit.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import data_quality_toolkit.adapters.cli.main as cli

# The core, public-safe set of top-level ``dqt`` subcommands, in any order.
# Every one of these must be registered in any repository state.
_CORE_COMMANDS = {
    "settings",
    "manifest",
    "pipeline",
    "version",
    "log-demo",
    "profile",
    "assess",
    "export-star",
    "export",
    "build-pbi",
    "gen-dim-time",
    "kpi-emit",
    "kpi-graph",
    "compare",
    "drift",
    "drift-history",
    "kpi-validate",
    "kpi-builtin",
    "plan",
    "chart",
    "dashboard",
    "stats",
    "ui",
}


def _extension_commands() -> set[str]:
    """The subcommands contributed by the optional command extensions in this tree.

    Extensions are discovered rather than listed, so their commands are asserted
    through the extensions themselves; the core set above stays strict in every
    distribution instead of being weakened to accommodate them.
    """
    sub = argparse.ArgumentParser().add_subparsers()
    for extension in cli._extensions:
        extension.register(sub)
    return set(sub.choices)


def _expected_commands() -> set[str]:
    """The exact command set for the current repository state."""
    return set(_CORE_COMMANDS) | _extension_commands()


_COMMAND_MODULES = [
    "assess",
    "chart",
    "compare",
    "dashboard",
    "drift",
    "drift_history",
    "export",
    "kpi",
    "meta",
    "pipeline",
    "plan",
    "powerbi",
    "profile",
    "stats",
    "ui",
]

# Names that existing (non-editable) tests patch or call on ``cli.main``; the
# split must keep all of them as module attributes.
_FROZEN_ATTRS = [
    # proxies
    "run_profile",
    "run_profile_chunked",
    "run_assessment",
    "run_assessment_chunked",
    "run_export_star",
    "run_plan",
    "run_drift",
    "read_drift_history",
    "import_drift_history_sqlite",
    "ensure_drift_db",
    "summarize_drift_trends_sqlite",
    "read_drift_runs_sqlite",
    "read_drift_columns_sqlite",
    "read_drift_distributions_sqlite",
    "stats_profile_csv",
    "select_statistical_test",
    "run_statistical_test",
    "compare_ab",
    # shared helpers
    "_json_dump",
    "_safe_text",
    "_get_sample_size",
    "_csv_kwargs_from_args",
    "_check_quality_gate",
    "_extract_null_threshold",
    "_extract_fail_under",
    "_apply_dqt_config",
    "_validate_csv_path",
    "_validate_csv_extension",
    "setup_logging",
    "subprocess",
    "load_settings",
    "VERSION",
    "build_parser",
    "main",
]

_FROZEN_HANDLERS = [
    "cmd_settings_show",
    "cmd_version",
    "cmd_log_demo",
    "cmd_manifest_create",
    "cmd_pipeline_run",
    "cmd_profile",
    "cmd_assess",
    "cmd_export_star",
    "cmd_build_pbi",
    "cmd_gen_dim_time",
    "cmd_kpi_emit",
    "cmd_kpi_graph",
    "cmd_kpi_validate",
    "cmd_compare",
    "cmd_drift",
    "cmd_drift_history",
    "cmd_drift_history_import",
    "cmd_drift_history_list",
    "cmd_drift_history_columns",
    "cmd_drift_history_trend",
    "cmd_drift_history_report",
    "cmd_drift_dashboard",
    "cmd_plan",
    "cmd_chart",
    "cmd_dashboard",
    "cmd_stats_profile",
    "cmd_stats_select_test",
    "cmd_stats_test",
    "cmd_stats_ab",
    "cmd_ui",
]


def _assert_exposes_a_registrar(name: str) -> None:
    mod = importlib.import_module(f"data_quality_toolkit.adapters.cli.commands.{name}")
    registrars = [a for a in dir(mod) if a == "register" or a.startswith("register_")]
    assert registrars, f"{name} exposes no register* entry point"


def test_command_modules_importable_and_have_register() -> None:
    for name in _COMMAND_MODULES:
        _assert_exposes_a_registrar(name)


def test_core_command_modules_are_not_treated_as_extensions() -> None:
    core = {f"data_quality_toolkit.adapters.cli.commands.{name}" for name in _COMMAND_MODULES}
    assert core <= cli._CORE_COMMAND_MODULES
    assert not {module.__name__ for module in cli._extensions} & cli._CORE_COMMAND_MODULES
    assert not _extension_commands() & _CORE_COMMANDS


def test_utils_modules_importable() -> None:
    importlib.import_module("data_quality_toolkit.adapters.cli.utils.parser")
    launcher = importlib.import_module("data_quality_toolkit.adapters.cli.utils.streamlit_launcher")
    assert callable(launcher.launch_streamlit_app)


def test_build_parser_registers_full_command_set() -> None:
    parser = cli.build_parser()
    # Locate the top-level subparsers action and compare its command names.
    subactions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    assert subactions, "no subparsers found on the top-level parser"
    registered = set(subactions[0].choices.keys())
    assert registered == _expected_commands()


@pytest.mark.parametrize("attr", _FROZEN_ATTRS + _FROZEN_HANDLERS)
def test_frozen_attribute_surface_present(attr: str) -> None:
    assert hasattr(cli, attr), f"cli.main.{attr} is missing after the split"


def test_handler_identity_matches_registered_func() -> None:
    parser = cli.build_parser()
    ns = parser.parse_args(["ui", "--db", "x.db"])
    assert ns.func is cli.cmd_ui
    ns2 = parser.parse_args(["profile", "file.csv"])
    assert ns2.func is cli.cmd_profile


# A fresh interpreter is the only order-independent way to prove this boundary:
# once any other test in the session has imported Streamlit, an in-process check
# can do nothing but skip, silently deleting the invariant from the broad suite.
_STREAMLIT_LEAK_PROBE = """
import importlib, importlib.util, json, sys
available = importlib.util.find_spec("streamlit") is not None
importlib.import_module("data_quality_toolkit.adapters.cli.main")
leaked = sorted(n for n in sys.modules if n == "streamlit" or n.startswith("streamlit."))
print(json.dumps({"available": available, "leaked": leaked}))
"""


def _streamlit_state_after_importing_the_cli() -> dict[str, object]:
    """Import the CLI entrypoint in a clean subprocess and report Streamlit state.

    Mirrors ``tests/unit/ui/test_ui_layer_containment.py``: reloading or pruning
    ``sys.modules`` in the pytest process would both depend on and disturb what
    other tests already imported, so the isolation has to be a real one. A fresh
    interpreter also re-executes the whole CLI import graph, which an in-process
    ``importlib.reload`` of a single module cannot do.
    """
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
        [sys.executable, "-c", _STREAMLIT_LEAK_PROBE],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return dict(json.loads(completed.stdout.strip()))


def test_importing_cli_does_not_load_streamlit() -> None:
    """A fresh import of the CLI entrypoint must not import Streamlit.

    Order-independent: the result never depends on what earlier tests imported.
    Only a genuinely absent Streamlit distribution can stop the probe from
    observing a leak, and that is the sole remaining skip condition.
    """
    state = _streamlit_state_after_importing_the_cli()
    if not state["available"]:
        pytest.skip("streamlit is not installed, so an accidental CLI import cannot be observed")
    assert state["leaked"] == [], f"importing the CLI pulled in Streamlit: {state['leaked']}"


# --- Optional command-extension boundary ------------------------------------
#
# Modules in ``adapters/cli/commands`` beyond the core set are optional command
# extensions: ``cli.main`` discovers and registers them, and a distribution may
# ship none. The core CLI must import and build its parser with no extension
# present, register one that is present, and fail loudly on one that is present
# but broken.
#
# Each state is proved in a fresh interpreter against a scratch copy of the
# package. Editing the real source tree and restoring it would leave the
# repository dirty on any failure, and pruning ``sys.modules`` in the pytest
# process would both depend on and disturb what earlier tests imported.

_SRC_ROOT = Path(__file__).resolve().parents[3] / "src"
_COMMANDS_DIR = "data_quality_toolkit/adapters/cli/commands"

_CLI_STATE_PROBE = """
import argparse, importlib, json, os, sys
scratch, command, handler = sys.argv[1], sys.argv[2], sys.argv[3]
cli = importlib.import_module("data_quality_toolkit.adapters.cli.main")
parser = cli.build_parser()
sub = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)][0]
print(json.dumps({
    "loaded_from": cli.__file__,
    "commands": sorted(sub.choices),
    "extensions": sorted(m.__name__ for m in cli._extensions),
    "handler_exported": bool(handler) and hasattr(cli, handler),
    "handler_is_registered_func": bool(command)
    and parser.parse_args([command]).func is getattr(cli, handler, None),
    "core_profile_handler_module": cli.cmd_profile.__module__,
    "loaded_package_modules": sorted(n for n in sys.modules if n.startswith("data_quality_toolkit")),
    "package_modules_outside_scratch": sorted(
        name
        for name, mod in list(sys.modules.items())
        if name.startswith("data_quality_toolkit")
        and getattr(mod, "__file__", None)
        and not os.path.realpath(mod.__file__).startswith(os.path.realpath(scratch))
    ),
}))
"""


def _extension_files() -> tuple[str, ...]:
    """The package-relative source file of every extension present in this tree."""
    return tuple(
        Path(str(module.__file__)).resolve().relative_to(_SRC_ROOT.resolve()).as_posix()
        for module in cli._extensions
    )


def _scratch_package(
    tmp_path: Path,
    *,
    omit: tuple[str, ...] = (),
    add: dict[str, str] | None = None,
) -> Path:
    """Copy the package into ``tmp_path`` minus ``omit``, plus ``add``; return its root."""
    src = tmp_path / "src"
    shutil.copytree(
        _SRC_ROOT / "data_quality_toolkit",
        src / "data_quality_toolkit",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    for relative in omit:
        (src / relative).unlink(missing_ok=True)
    for relative, text in (add or {}).items():
        (src / relative).write_text(text, encoding="utf-8")
    return src


def _probe_cli_in(
    src: Path, *, check: bool, command: str = "", handler: str = ""
) -> subprocess.CompletedProcess[str]:
    """Run the CLI state probe in a fresh interpreter resolving the package from ``src``."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(src)
    return subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
        [sys.executable, "-c", _CLI_STATE_PROBE, str(src), command, handler],
        capture_output=True,
        text=True,
        timeout=120,
        check=check,
        cwd=str(src.parent),
        env=env,
    )


def _state(completed: subprocess.CompletedProcess[str], src: Path) -> dict[str, Any]:
    state = dict(json.loads(completed.stdout.strip()))
    # Without this the probe could be silently reporting on the installed
    # package, and every assertion on it would prove nothing.
    loaded_from = str(state["loaded_from"])
    assert loaded_from.startswith(str(src)), f"probe imported {loaded_from}, not {src}"
    assert state["package_modules_outside_scratch"] == [], (
        "the probe resolved package modules outside the scratch copy: "
        f"{state['package_modules_outside_scratch']}"
    )
    return state


_PROBE_EXTENSION = """
import argparse


def cmd_probe_extension(args: argparse.Namespace) -> int:
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    return 99


def register(sub: argparse._SubParsersAction) -> None:
    sp = sub.add_parser("probe-extension")
    sp.set_defaults(func=cmd_probe_extension)
"""


def test_cli_is_healthy_without_command_extensions(tmp_path: Path) -> None:
    """With every extension removed the CLI imports, parses and has the core set."""
    src = _scratch_package(tmp_path, omit=_extension_files())
    state = _state(_probe_cli_in(src, check=True), src)

    assert set(state["commands"]) == _CORE_COMMANDS
    assert state["extensions"] == []


def test_command_extension_is_discovered_and_registered(tmp_path: Path) -> None:
    """A present extension is registered and its handler re-exported, never over a core one."""
    src = _scratch_package(
        tmp_path,
        omit=_extension_files(),
        add={
            f"{_COMMANDS_DIR}/zz_probe_extension.py": _PROBE_EXTENSION,
            f"{_COMMANDS_DIR}/zz_probe_helper.py": "VALUE = 1\n",
        },
    )
    completed = _probe_cli_in(
        src, check=True, command="probe-extension", handler="cmd_probe_extension"
    )
    state = _state(completed, src)

    assert set(state["commands"]) == _CORE_COMMANDS | {"probe-extension"}
    assert state["extensions"] == ["data_quality_toolkit.adapters.cli.commands.zz_probe_extension"]
    assert state["handler_exported"] is True
    assert state["handler_is_registered_func"] is True
    assert (
        state["core_profile_handler_module"] == "data_quality_toolkit.adapters.cli.commands.profile"
    )


def test_broken_command_extension_is_not_swallowed_as_absence(tmp_path: Path) -> None:
    """A present extension that fails to import must fail loudly, not read as absent."""
    src = _scratch_package(
        tmp_path,
        omit=_extension_files(),
        add={f"{_COMMANDS_DIR}/zz_broken_extension.py": "import dqt_probe_missing_dependency\n"},
    )
    completed = _probe_cli_in(src, check=False)

    assert completed.returncode != 0, "a broken extension was reported as normal absence"
    assert "ModuleNotFoundError" in completed.stderr
    assert "dqt_probe_missing_dependency" in completed.stderr
