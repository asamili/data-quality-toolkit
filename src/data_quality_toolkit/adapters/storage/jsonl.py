import json
import os
from pathlib import Path
from typing import Any


def append_jsonl_record(path: Path, record: Any) -> None:
    """Safely append a single JSON object to a .jsonl file."""
    # Ensure parent exists if pipeline flow expects it
    path.parent.mkdir(parents=True, exist_ok=True)

    # Serialize to string first to ensure complete write
    line = json.dumps(record, default=str) + "\n"

    # Use atomic-ish approach: open, write, flush, fsync
    # Note: On Windows, fsync isn't always fully supported as expected by POSIX,
    # but this is the safest conventional approach in Python.
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
