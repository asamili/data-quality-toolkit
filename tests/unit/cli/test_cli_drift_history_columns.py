# tests/unit/cli/test_cli_drift_history_columns.py
"""Unit tests for the `dqt drift-history columns` command."""

from __future__ import annotations

import json

import data_quality_toolkit.adapters.cli.main as cli
from data_quality_toolkit.adapters.storage.schema import ensure_db

_COLUMN = {
    "run_id": "r1",
    "column_name": "age",
    "kind": "numeric",
    "test": "ks",
    "statistic": 0.42,
    "p_value": 0.001,
    "drift_detected": 1,
    "reference_n": 60,
    "current_n": 60,
    "status": "tested",
    "skip_reason": None,
    "psi": 0.31,
    "js_distance": 0.22,
    "wasserstein": 1.5,
}

# drift_columns INSERT field order (id is autoincrement, omitted).
_COLUMN_FIELDS = (
    "run_id",
    "column_name",
    "kind",
    "test",
    "statistic",
    "p_value",
    "drift_detected",
    "reference_n",
    "current_n",
    "status",
    "skip_reason",
    "psi",
    "js_distance",
    "wasserstein",
)


def _patch(monkeypatch, rows=None):
    """Monkeypatch the lazy reader; record forwarded args."""
    calls: list[tuple[str, dict]] = []
    result = [dict(_COLUMN)] if rows is None else rows

    def fake_read(db_path: str, **filters):
        calls.append((db_path, filters))
        return result

    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "read_drift_columns_sqlite", fake_read)
    return calls


def _insert_columns(db, rows):
    """Insert drift_columns rows into a real SQLite DB."""
    from data_quality_toolkit.adapters.storage.connection import connect

    cols = ", ".join(_COLUMN_FIELDS)
    placeholders = ", ".join("?" for _ in _COLUMN_FIELDS)
    sql = f"INSERT INTO drift_columns({cols}) VALUES ({placeholders})"  # noqa: S608
    with connect(db) as con:
        for row in rows:
            con.execute(sql, tuple(row[f] for f in _COLUMN_FIELDS))
        con.commit()


def test_columns_stdout_is_json_list(monkeypatch, capsys):
    _patch(monkeypatch)
    rc = cli.main(["drift-history", "columns", "--db", "drift.db"])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["column_name"] == "age"


def test_columns_summary_on_stderr(monkeypatch, capsys):
    _patch(monkeypatch)
    cli.main(["drift-history", "columns", "--db", "drift.db"])
    err = capsys.readouterr().err
    assert "Drift columns listed" in err
    assert "drift.db" in err
    assert "Columns: 1" in err
    assert "Drifted columns: 1" in err


def test_columns_drifted_count_reflects_rows(monkeypatch, capsys):
    rows = [
        dict(_COLUMN, column_name="a", drift_detected=1),
        dict(_COLUMN, column_name="b", drift_detected=0),
    ]
    _patch(monkeypatch, rows=rows)
    cli.main(["drift-history", "columns", "--db", "drift.db"])
    err = capsys.readouterr().err
    assert "Columns: 2" in err
    assert "Drifted columns: 1" in err


def test_columns_no_json_suppresses_stdout(monkeypatch, capsys):
    _patch(monkeypatch)
    rc = cli.main(["--no-json", "drift-history", "columns", "--db", "drift.db"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""
    assert "Drift columns listed" in captured.err
    assert "Columns: 1" in captured.err


def test_columns_empty_result_is_empty_json_list(monkeypatch, capsys):
    _patch(monkeypatch, rows=[])
    rc = cli.main(["drift-history", "columns", "--db", "drift.db"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []


def test_columns_forwards_db_path(monkeypatch, capsys):
    calls = _patch(monkeypatch)
    cli.main(["drift-history", "columns", "--db", "path/to/drift.db"])
    assert calls[0][0] == "path/to/drift.db"


def test_columns_forwards_filters_typed(monkeypatch, capsys):
    calls = _patch(monkeypatch)
    cli.main(
        [
            "drift-history",
            "columns",
            "--db",
            "drift.db",
            "--run-id",
            "r1",
            "--column-name",
            "age",
            "--drift-detected",
            "true",
        ]
    )
    filters = calls[0][1]
    assert filters["run_id"] == "r1"
    assert filters["column_name"] == "age"
    assert filters["drift_detected"] is True


def test_columns_drift_detected_false_forwarded_as_false(monkeypatch, capsys):
    calls = _patch(monkeypatch)
    cli.main(["drift-history", "columns", "--db", "drift.db", "--drift-detected", "false"])
    assert calls[0][1]["drift_detected"] is False


def test_columns_defaults_filters_none(monkeypatch, capsys):
    calls = _patch(monkeypatch)
    cli.main(["drift-history", "columns", "--db", "drift.db"])
    filters = calls[0][1]
    assert filters["run_id"] is None
    assert filters["column_name"] is None
    assert filters["drift_detected"] is None


def test_columns_bad_drift_detected_value_exits_2(monkeypatch, capsys):
    _patch(monkeypatch)
    try:
        cli.main(["drift-history", "columns", "--db", "drift.db", "--drift-detected", "maybe"])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - defensive
        raise AssertionError("expected SystemExit for invalid --drift-detected")


def test_columns_requires_db_flag(monkeypatch, capsys):
    _patch(monkeypatch)
    try:
        cli.main(["drift-history", "columns"])
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - defensive
        raise AssertionError("expected SystemExit for missing --db")


def test_columns_missing_db_returns_empty_list(monkeypatch, tmp_path, capsys):
    """Missing DB file follows API behavior: [] with exit 0 (real reader)."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    missing = tmp_path / "nope.db"

    rc = cli.main(["drift-history", "columns", "--db", str(missing)])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []


def test_columns_empty_table_returns_empty_list(monkeypatch, tmp_path, capsys):
    """A DB with an empty drift_columns table returns [] with exit 0."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    db = tmp_path / "drift.db"
    ensure_db(db)

    rc = cli.main(["drift-history", "columns", "--db", str(db)])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []


def test_columns_real_db_returns_inserted_columns(monkeypatch, tmp_path, capsys):
    """End-to-end with a real SQLite DB and inserted drift_columns rows."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    db = tmp_path / "drift.db"
    ensure_db(db)
    _insert_columns(db, [_COLUMN, dict(_COLUMN, column_name="city", kind="categorical")])

    rc = cli.main(["drift-history", "columns", "--db", str(db)])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert {r["column_name"] for r in parsed} == {"age", "city"}
    age = next(r for r in parsed if r["column_name"] == "age")
    assert age["psi"] == 0.31
    assert age["js_distance"] == 0.22
    assert age["wasserstein"] == 1.5
    assert age["drift_detected"] == 1


def test_columns_real_db_drift_detected_filter(monkeypatch, tmp_path, capsys):
    """--drift-detected true narrows real rows to drifted columns only."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    db = tmp_path / "drift.db"
    ensure_db(db)
    _insert_columns(
        db,
        [
            dict(_COLUMN, column_name="a", drift_detected=1),
            dict(_COLUMN, column_name="b", drift_detected=0),
        ],
    )

    rc = cli.main(["drift-history", "columns", "--db", str(db), "--drift-detected", "true"])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert [r["column_name"] for r in parsed] == ["a"]


def test_columns_real_db_column_name_filter(monkeypatch, tmp_path, capsys):
    """--column-name narrows real rows to the matching column."""
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    db = tmp_path / "drift.db"
    ensure_db(db)
    _insert_columns(
        db,
        [dict(_COLUMN, column_name="age"), dict(_COLUMN, column_name="city")],
    )

    rc = cli.main(["drift-history", "columns", "--db", str(db), "--column-name", "city"])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert [r["column_name"] for r in parsed] == ["city"]
