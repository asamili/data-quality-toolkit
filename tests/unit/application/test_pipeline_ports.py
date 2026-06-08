"""Tests for application port protocols and injectable pipeline helpers (001D)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Ports module
# ---------------------------------------------------------------------------


def test_ports_module_importable() -> None:
    from data_quality_toolkit.application.ports import (
        CsvLoaderPort,
        IssueExporterPort,
        StarBuilderPort,
        StarWriterPort,
    )

    assert CsvLoaderPort is not None
    assert StarBuilderPort is not None
    assert StarWriterPort is not None
    assert IssueExporterPort is not None


def test_ports_are_protocols() -> None:
    from data_quality_toolkit.application.ports import (
        CsvLoaderPort,
        IssueExporterPort,
        StarBuilderPort,
        StarWriterPort,
    )

    for proto in (CsvLoaderPort, StarBuilderPort, StarWriterPort, IssueExporterPort):
        assert isinstance(proto, type), f"{proto} should be a class"
        assert getattr(proto, "_is_protocol", False), f"{proto} should be a Protocol"


def test_ports_all_exports() -> None:
    import data_quality_toolkit.application.ports as ports_mod

    expected = {"CsvLoaderPort", "StarBuilderPort", "StarWriterPort", "IssueExporterPort"}
    assert expected == set(ports_mod.__all__)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_prof(**kw: Any) -> Any:
    base: dict[str, Any] = {
        "run_id": "run-001",
        "dataset_id": "ds-001",
        "ts": "2026-01-01T00:00:00",
        "rows": 5,
        "cols": 2,
        "memory_mb": 0.1,
        "columns": [{"name": "a", "dtype": "int64"}],
    }
    base.update(kw)
    return base


def _make_assessment(**kw: Any) -> Any:
    base: dict[str, Any] = {
        "score": 1.0,
        "completeness_score": 1.0,
        "quality_score": 1.0,
        "issues": [],
    }
    base.update(kw)
    return base


_META: dict[str, Any] = {"dataset_id": "ds-001", "source_path": "data.csv"}


# ---------------------------------------------------------------------------
# _persist_assessment_to_db — injectable storage helper
# ---------------------------------------------------------------------------


def test_persist_assessment_to_db_uses_injected_callables(tmp_path: Path) -> None:
    from data_quality_toolkit.application.workflow.pipeline import _persist_assessment_to_db

    db = tmp_path / "test.db"
    mock_ensure = MagicMock()
    mock_con = MagicMock()
    mock_connect = MagicMock(return_value=mock_con)
    mock_persist = MagicMock()

    _persist_assessment_to_db(
        db,
        _make_prof(),
        _make_assessment(),
        _META,
        1.0,
        0.2,
        _ensure_db=mock_ensure,
        _connect=mock_connect,
        _persist=mock_persist,
    )

    mock_ensure.assert_called_once_with(db)
    mock_connect.assert_called_once_with(db)
    mock_persist.assert_called_once()
    mock_con.close.assert_called_once()


def test_persist_assessment_to_db_passes_correct_fields(tmp_path: Path) -> None:
    from data_quality_toolkit.application.workflow.pipeline import _persist_assessment_to_db

    db = tmp_path / "fields.db"
    issues = [{"column": "x", "severity": "high", "category": "Completeness", "message": "m"}]
    mock_con = MagicMock()
    mock_persist = MagicMock()

    _persist_assessment_to_db(
        db,
        _make_prof(run_id="r1", dataset_id="ds1"),
        _make_assessment(score=0.7, issues=issues),
        {"dataset_id": "ds1", "source_path": "f.csv"},
        2.5,
        0.3,
        _ensure_db=MagicMock(),
        _connect=MagicMock(return_value=mock_con),
        _persist=mock_persist,
    )

    _args, kwargs = mock_persist.call_args
    assert kwargs["run_id"] == "r1"
    assert kwargs["dataset_id"] == "ds1"
    assert kwargs["source_path"] == "f.csv"
    assert kwargs["score"] == 0.7
    assert kwargs["issues_total"] == 1
    assert kwargs["issues_by_severity"] == {"high": 1}
    assert kwargs["issues_by_category"] == {"Completeness": 1}
    assert kwargs["quality_metrics"] == []


def test_persist_assessment_to_db_closes_connection_on_error(tmp_path: Path) -> None:
    from data_quality_toolkit.application.workflow.pipeline import _persist_assessment_to_db

    db = tmp_path / "err.db"
    mock_con = MagicMock()

    try:
        _persist_assessment_to_db(
            db,
            _make_prof(),
            _make_assessment(),
            _META,
            1.0,
            0.1,
            _ensure_db=MagicMock(),
            _connect=MagicMock(return_value=mock_con),
            _persist=MagicMock(side_effect=RuntimeError("db write failed")),
        )
    except RuntimeError:
        pass

    mock_con.close.assert_called_once()


# ---------------------------------------------------------------------------
# _persist_star_to_sqlite — injectable star-export storage helper
# ---------------------------------------------------------------------------


def test_persist_star_to_sqlite_uses_injected_callables(tmp_path: Path) -> None:
    import pandas as pd

    from data_quality_toolkit.application.workflow.pipeline import _persist_star_to_sqlite

    db = tmp_path / "star.db"
    mock_settings = MagicMock()
    mock_get_db = MagicMock(return_value=db)
    mock_ensure = MagicMock()
    mock_con = MagicMock()
    mock_connect = MagicMock(return_value=mock_con)
    mock_persist = MagicMock()

    tables: dict[str, Any] = {"fact_quality_metrics": pd.DataFrame({"metric": ["v"]})}

    _persist_star_to_sqlite(
        mock_settings,
        _make_prof(),
        _make_assessment(),
        _META,
        [],
        1.0,
        0.1,
        tables,
        _get_db=mock_get_db,
        _ensure_db=mock_ensure,
        _connect=mock_connect,
        _persist=mock_persist,
    )

    mock_get_db.assert_called_once_with(mock_settings)
    mock_ensure.assert_called_once_with(db)
    mock_connect.assert_called_once_with(db)
    mock_persist.assert_called_once()
    mock_con.close.assert_called_once()


def test_persist_star_to_sqlite_deletes_before_insert(tmp_path: Path) -> None:
    import pandas as pd

    from data_quality_toolkit.application.workflow.pipeline import _persist_star_to_sqlite

    db = tmp_path / "del.db"
    mock_con = MagicMock()
    tables: dict[str, Any] = {"fact_quality_metrics": pd.DataFrame()}

    _persist_star_to_sqlite(
        MagicMock(),
        _make_prof(run_id="r99"),
        _make_assessment(),
        _META,
        [],
        1.0,
        0.1,
        tables,
        _get_db=MagicMock(return_value=db),
        _ensure_db=MagicMock(),
        _connect=MagicMock(return_value=mock_con),
        _persist=MagicMock(),
    )

    delete_calls = [c for c in mock_con.execute.call_args_list if "DELETE" in str(c)]
    assert len(delete_calls) == 1
    assert "r99" in str(delete_calls[0])


# ---------------------------------------------------------------------------
# Import-boundary regression: existing pipeline @patch targets still work
# ---------------------------------------------------------------------------


def test_run_assessment_db_patch_targets_still_work(tmp_path: Path) -> None:
    """Confirms module-level patch targets used by test_pipeline.py remain valid after refactor."""
    with (
        patch("data_quality_toolkit.application.workflow.pipeline.persist_export_run") as mp,
        patch(
            "data_quality_toolkit.application.workflow.pipeline.connect",
            return_value=MagicMock(),
        ),
        patch("data_quality_toolkit.application.workflow.pipeline.ensure_db"),
        patch(
            "data_quality_toolkit.application.workflow.pipeline.assess",
            return_value=_make_assessment(),
        ),
        patch(
            "data_quality_toolkit.application.workflow.pipeline.run_profiling",
            return_value=_make_prof(),
        ),
        patch(
            "data_quality_toolkit.application.workflow.pipeline.load_csv",
            return_value=(MagicMock(), _META),
        ),
    ):
        from data_quality_toolkit.application.workflow.pipeline import run_assessment

        run_assessment("a.csv", db_path=tmp_path / "t.db")
        mp.assert_called_once()
