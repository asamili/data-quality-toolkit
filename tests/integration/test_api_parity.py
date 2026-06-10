from __future__ import annotations

from pathlib import Path

import pytest

from data_quality_toolkit import create_manifest

pytestmark = pytest.mark.integration


def test_create_manifest_api_delegation(tmp_path: Path) -> None:
    # Setup
    run_id = "test-run"
    session_dir = tmp_path / run_id
    session_dir.mkdir()
    (session_dir / "meta").mkdir()
    (session_dir / "meta" / "gates.jsonl").write_text("", encoding="utf-8")

    # Act
    result = create_manifest(run_id=run_id, sessions_root=tmp_path)

    # Assert
    assert isinstance(result, dict)
    assert result["run_id"] == run_id

    # Check if file was written
    manifest_path = session_dir / "artifacts.json"
    assert manifest_path.exists()
