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


def read_jsonl_records(path: Path) -> list[Any]:
    """Read all valid JSON lines from a JSONL file.

    Missing file returns []. Blank and malformed lines are skipped. Preserves file order.
    """
    if not path.exists():
        return []
    records: list[Any] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return records


def read_drift_history(path: Path) -> list[Any]:
    """Return drift_history_record entries from a JSONL file.

    Filters to kind == "drift_history_record". Preserves append order. Missing file returns [].
    """
    return [r for r in read_jsonl_records(path) if r.get("kind") == "drift_history_record"]
