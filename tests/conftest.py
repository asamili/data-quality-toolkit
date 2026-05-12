from __future__ import annotations

import sys
import types
from pathlib import Path

# Repo root = tests/.. (adjust if your layout differs)
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

# Ensure "src" is importable
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Provide a namespace module "src" to satisfy imports like "from src.foo import bar"
if "src" not in sys.modules:
    mod = types.ModuleType("src")
    mod.__path__ = [str(SRC)]  # namespace package
    sys.modules["src"] = mod
