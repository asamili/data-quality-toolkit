"""App-import AI purity.

Importing the default Streamlit app must never pull in the optional local-AI
stack. Optional AI is default-off and is only activated behind an explicit
environment flag; a bare ``import`` of the app module must stay dependency-free.

The check runs in an isolated subprocess so the assertion observes only what the
app import itself loads, never modules another test happened to import earlier in
the session. This test imports none of the banned packages, requires none of them
to be installed, and does not set ``DQT_STORYLENS_AI_ENABLED`` or
``DQT_STORYLENS_MODEL_DIR``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import data_quality_toolkit

# Optional local-AI package roots that the default UI app must not import.
_BANNED_AI_ROOTS = (
    "transformers",
    "torch",
    "huggingface_hub",
    "tokenizers",
    "safetensors",
    "sentence_transformers",
)

# Program executed in a clean interpreter: import the app, then fail if any banned
# root is present in sys.modules. It prints the offenders and exits non-zero.
_CHILD_PROGRAM = (
    "import sys\n"
    "import data_quality_toolkit.adapters.ui.app  # noqa: F401\n"
    f"banned = {_BANNED_AI_ROOTS!r}\n"
    "present = sorted(name for name in banned if name in sys.modules)\n"
    "if present:\n"
    "    print(','.join(present))\n"
    "    raise SystemExit(1)\n"
)


def _src_root() -> str:
    # .../src/data_quality_toolkit/__init__.py -> .../src
    return str(Path(data_quality_toolkit.__file__).resolve().parent.parent)


def test_importing_ui_app_does_not_load_optional_ai_packages() -> None:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = _src_root() + (os.pathsep + existing if existing else "")
    # Keep optional AI default-off in the child; never enable it here.
    env.pop("DQT_STORYLENS_AI_ENABLED", None)
    env.pop("DQT_STORYLENS_MODEL_DIR", None)

    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _CHILD_PROGRAM],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, (
        "Importing data_quality_toolkit.adapters.ui.app loaded banned optional AI "
        f"package roots: {result.stdout.strip()}\nstderr:\n{result.stderr}"
    )
