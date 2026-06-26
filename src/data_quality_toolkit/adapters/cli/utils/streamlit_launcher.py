# src/data_quality_toolkit/adapters/cli/utils/streamlit_launcher.py
"""Shared Streamlit app launcher for ``dqt dashboard`` and ``dqt ui``.

Importing this module must NOT import Streamlit: the ``import streamlit`` guard
lives inside :func:`launch_streamlit_app` so the base CLI stays Streamlit-free.
"""

from __future__ import annotations

import inspect
import os
import subprocess
import sys

# Single source of truth for the missing-Streamlit hint (quoted form so the
# shell command copy-pastes correctly).
MISSING_STREAMLIT_MESSAGE = (
    "Error: Streamlit is not installed.\n"
    '  Install it with: pip install "data-quality-toolkit[ui]"'
)


def launch_streamlit_app(*, db: str | None = None) -> int:
    """Launch the Streamlit UI app (``ui/app.py``) in a child process.

    Shared by ``dqt dashboard`` and ``dqt ui``. When ``db`` is provided, seed
    ``DQT_UI_DB`` so the Drift Explorer opens pre-pointed at that monitoring
    database.

    Returns:
        ``1`` if Streamlit is not installed, ``130`` on KeyboardInterrupt,
        otherwise the child process return code.
    """
    try:
        import streamlit  # noqa: F401
    except ImportError:
        print(MISSING_STREAMLIT_MESSAGE, file=sys.stderr)
        return 1

    if db:
        # Only the user-provided DB path is exported for the child app.
        os.environ["DQT_UI_DB"] = db

    import data_quality_toolkit.adapters.ui.app as _app_mod

    app_file = inspect.getfile(_app_mod)
    try:
        # List args (never shell=True); app_file is resolved from the package,
        # not interpolated from user input.
        result = subprocess.run([sys.executable, "-m", "streamlit", "run", app_file])  # noqa: S603
        return result.returncode
    except KeyboardInterrupt:
        return 130
