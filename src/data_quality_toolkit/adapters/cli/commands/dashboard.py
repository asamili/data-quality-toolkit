# src/data_quality_toolkit/adapters/cli/commands/dashboard.py
"""``dqt dashboard`` — launch the Streamlit dashboard."""

from __future__ import annotations

import argparse

from data_quality_toolkit.adapters.cli.utils.streamlit_launcher import launch_streamlit_app


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Launch the Streamlit dashboard (requires the optional ``[ui]`` extra)."""
    return launch_streamlit_app()


def register(sub: argparse._SubParsersAction) -> None:
    sp_dash = sub.add_parser(
        "dashboard",
        help="Launch the Streamlit dashboard (requires: pip install data-quality-toolkit[ui])",
    )
    sp_dash.set_defaults(func=cmd_dashboard)
