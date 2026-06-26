"""CLI --help smoke: every registered top-level subcommand exits 0."""

from __future__ import annotations

import pytest

from data_quality_toolkit.adapters.cli.main import build_parser

_SUBCOMMANDS = [
    "assess",
    "build-pbi",
    "chart",
    "compare",
    "dashboard",
    "drift",
    "drift-history",
    "export",
    "export-star",
    "gen-dim-time",
    "kpi-emit",
    "kpi-graph",
    "kpi-validate",
    "log-demo",
    "manifest",
    "pipeline",
    "plan",
    "profile",
    "settings",
    "ui",
    "version",
]


@pytest.fixture(scope="module")
def _parser():
    return build_parser()


@pytest.mark.parametrize("subcommand", _SUBCOMMANDS)
def test_subcommand_help_exits_0(
    subcommand: str,
    _parser,
    capsys: pytest.CaptureFixture,
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _parser.parse_args([subcommand, "--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert out, f"--help produced no output for subcommand '{subcommand}'"
