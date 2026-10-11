"""Pure read-only loading of existing manifest files.

The single canonical way to open an ``artifacts.json`` that already exists on
disk. Deliberately the inverse of :mod:`builder`: it never creates directories,
never writes, never rebuilds, and never scans a session — it only reads one
file and validates it through the existing :class:`Manifest` schema via the
shared serializer (so schema/version behavior is unchanged).
"""

from __future__ import annotations

from pathlib import Path

from data_quality_toolkit.lineage.manifest.schemas import Manifest
from data_quality_toolkit.lineage.manifest.serializer import ManifestSerializer


def load_manifest(manifest_path: str | Path) -> Manifest:
    """Read and validate an existing manifest file, without any write.

    Raises ``OSError`` (including ``FileNotFoundError``) when the file cannot
    be read, and a validation error when the content does not satisfy the
    existing ``Manifest`` schema. Callers own user-facing error handling.
    """
    data = Path(manifest_path).read_bytes()
    return ManifestSerializer().from_json(data)
