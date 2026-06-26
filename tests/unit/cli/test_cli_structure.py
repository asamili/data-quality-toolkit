"""Structure & compatibility tests for the v2.6.0 CLI package split.

These assert the modular layout (``adapters/cli/commands`` + ``adapters/cli/utils``)
without changing any public CLI behavior: every command module exposes a
``register*`` entry point, ``build_parser`` still wires the full command set, the
frozen ``cli.main`` attribute surface (proxies + shared helpers + handlers) is
intact, and importing the CLI never drags in Streamlit.
"""

from __future__ import annotations

import importlib
import sys

import pytest

import data_quality_toolkit.adapters.cli.main as cli

# The complete set of top-level ``dqt`` subcommands, in any order.
_EXPECTED_COMMANDS = {
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
    "plan",
    "chart",
    "dashboard",
    "ui",
}

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
    "cmd_ui",
]


def test_command_modules_importable_and_have_register() -> None:
    for name in _COMMAND_MODULES:
        mod = importlib.import_module(f"data_quality_toolkit.adapters.cli.commands.{name}")
        registrars = [a for a in dir(mod) if a == "register" or a.startswith("register_")]
        assert registrars, f"{name} exposes no register* entry point"


def test_utils_modules_importable() -> None:
    importlib.import_module("data_quality_toolkit.adapters.cli.utils.parser")
    launcher = importlib.import_module("data_quality_toolkit.adapters.cli.utils.streamlit_launcher")
    assert callable(launcher.launch_streamlit_app)


def test_build_parser_registers_full_command_set() -> None:
    parser = cli.build_parser()
    # Locate the top-level subparsers action and compare its command names.
    subactions = [
        a for a in parser._actions if isinstance(a, __import__("argparse")._SubParsersAction)
    ]
    assert subactions, "no subparsers found on the top-level parser"
    registered = set(subactions[0].choices.keys())
    assert registered == _EXPECTED_COMMANDS


@pytest.mark.parametrize("attr", _FROZEN_ATTRS + _FROZEN_HANDLERS)
def test_frozen_attribute_surface_present(attr: str) -> None:
    assert hasattr(cli, attr), f"cli.main.{attr} is missing after the split"


def test_handler_identity_matches_registered_func() -> None:
    parser = cli.build_parser()
    ns = parser.parse_args(["ui", "--db", "x.db"])
    assert ns.func is cli.cmd_ui
    ns2 = parser.parse_args(["profile", "file.csv"])
    assert ns2.func is cli.cmd_profile


def test_importing_cli_does_not_load_streamlit() -> None:
    # A fresh import of the CLI entrypoint must not import Streamlit.
    for mod in list(sys.modules):
        if mod == "streamlit" or mod.startswith("streamlit."):
            pytest.skip("streamlit already imported by another test in this session")
    importlib.reload(cli)
    assert "streamlit" not in sys.modules
