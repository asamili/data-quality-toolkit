# src/data_quality_toolkit/adapters/cli/commands/ui.py
"""``dqt ui`` — preferred Streamlit launcher (opens the Drift Explorer)."""

from __future__ import annotations

import argparse

from data_quality_toolkit.adapters.cli.utils.streamlit_launcher import launch_streamlit_app


def cmd_ui(args: argparse.Namespace) -> int:
    """Launch the Streamlit UI (Drift Explorer), preferred over ``dashboard``.

    If ``--db`` is given, seed ``DQT_UI_DB`` so the Drift Explorer opens
    pre-pointed at that monitoring database.
    """
    return launch_streamlit_app(db=getattr(args, "db", None))


def register(sub: argparse._SubParsersAction) -> None:
    sp_ui = sub.add_parser(
        "ui",
        help=(
            "Launch the Streamlit Drift Explorer UI "
            '(requires: pip install "data-quality-toolkit[ui]")'
        ),
    )
    sp_ui.add_argument(
        "--db",
        dest="db",
        metavar="PATH",
        help="Path to a SQLite monitoring database (sets DQT_UI_DB for the UI)",
    )
    sp_ui.set_defaults(func=cmd_ui)
