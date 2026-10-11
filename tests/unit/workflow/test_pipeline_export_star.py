from __future__ import annotations

import ast
import csv
import inspect
import json
import re
import sqlite3
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from unittest.mock import patch

import pytest

from data_quality_toolkit.application.workflow import pipeline
from data_quality_toolkit.application.workflow.pipeline import (
    _managed_artifact_meta,
    run_export_star,
    run_managed_export_star,
)
from data_quality_toolkit.lineage.manifest.schemas import Manifest
from data_quality_toolkit.shared.managed_export_source import (
    VerifiedManagedExportSource,
    managed_content_id_from_file,
)
from data_quality_toolkit.shared.settings import settings
from data_quality_toolkit.shared.text_redaction import PATH_REDACTED_DISPLAY


def test_run_export_star_creates_csvs_and_relationships(tmp_path):
    f = tmp_path / "tiny.csv"
    f.write_text("id,age\n1,30\n2,40\n", encoding="utf-8")

    out = run_export_star(str(f), output_dir=str(tmp_path))

    # basic structure
    assert set(out.keys()) >= {
        "run_id",
        "dataset_id",
        "ts",
        "meta",
        "profile",
        "star",
        "export_paths",
    }

    # files exist
    paths = out["export_paths"]
    expected = {
        "dim_dataset",
        "dim_column",
        "fact_profile_runs",
        "fact_quality_metrics",
        "fact_issues",
        "quality_history",
        "relationships",
    }
    assert expected.issubset(set(paths.keys()))

    for p in paths.values():
        assert Path(p).exists(), f"missing file: {p}"

    # history file must be a valid JSONL with at least one record
    import json

    history_lines = Path(paths["quality_history"]).read_text(encoding="utf-8").splitlines()
    assert len(history_lines) >= 1
    record = json.loads(history_lines[-1])
    assert "issues_by_severity" in record
    assert "issues_by_category" in record

    # star info consistency
    star = out["star"]
    assert set(star["tables"]) >= {
        "dim_dataset",
        "dim_column",
        "fact_profile_runs",
        "fact_quality_metrics",
    }
    assert isinstance(star["rows"], dict)


def test_run_export_star_emit_manifest_writes_artifacts_json(tmp_path: Path) -> None:
    f = tmp_path / "tiny.csv"
    f.write_text("id,age\n1,30\n2,40\n", encoding="utf-8")

    out = run_export_star(str(f), output_dir=str(tmp_path), emit_manifest=True)

    manifest_path = tmp_path / "artifacts.json"
    assert manifest_path.exists(), "artifacts.json not written"
    assert "manifest" in out["export_paths"]
    assert Path(out["export_paths"]["manifest"]) == manifest_path

    raw = manifest_path.read_text(encoding="utf-8")
    manifest = Manifest.model_validate_json(raw)
    assert manifest.run_id == out["run_id"]

    # dataset contract
    assert len(manifest.datasets) == 1
    assert manifest.datasets[0].kind == "bronze"
    assert manifest.datasets[0].rows == 2

    # artifact paths are relative POSIX strings (no drive letter, no backslash)
    for art in manifest.artifacts:
        assert "\\" not in art.path, f"non-POSIX path in artifact: {art.path!r}"
        assert not art.path.startswith("/"), f"absolute path in artifact: {art.path!r}"
        # each listed artifact resolves under base_out and exists
        resolved = tmp_path / art.path
        assert resolved.exists(), f"artifact path does not exist: {art.path!r}"


def test_run_export_star_reports_the_configured_manifest_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A custom MANIFEST_FILE is both the manifest written and the path reported."""
    monkeypatch.setattr(settings, "manifest_file", "lineage_index.json")
    f = tmp_path / "tiny.csv"
    f.write_text("id,age\n1,30\n2,40\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    out = run_export_star(str(f), output_dir=str(out_dir), emit_manifest=True)

    reported = Path(out["export_paths"]["manifest"])
    assert reported == out_dir / "lineage_index.json"
    assert reported.is_file()
    assert not (out_dir / "artifacts.json").exists()
    assert Manifest.model_validate_json(reported.read_bytes()).run_id == out["run_id"]


def test_run_export_star_default_does_not_emit_manifest(tmp_path: Path) -> None:
    f = tmp_path / "tiny.csv"
    f.write_text("id,age\n1,30\n2,40\n", encoding="utf-8")

    out = run_export_star(str(f), output_dir=str(tmp_path))

    assert not (tmp_path / "artifacts.json").exists()
    assert "manifest" not in out["export_paths"]


def test_run_export_star_manifest_failure_is_nonfatal(tmp_path: Path) -> None:
    f = tmp_path / "tiny.csv"
    f.write_text("id,age\n1,30\n2,40\n", encoding="utf-8")

    with patch(
        "data_quality_toolkit.application.workflow.pipeline.build_and_write",
        side_effect=RuntimeError("injected failure"),
    ):
        out = run_export_star(str(f), output_dir=str(tmp_path), emit_manifest=True)

    # export succeeds despite manifest failure
    assert out["run_id"]
    assert "manifest" not in out["export_paths"]
    assert not (tmp_path / "artifacts.json").exists()


def test_run_export_star_creates_sqlite_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_db = tmp_path / "env-override.db"
    monkeypatch.setenv("DQT_DB_PATH", str(env_db))

    f = tmp_path / "tiny.csv"
    f.write_text("id,age\n1,30\n2,40\n", encoding="utf-8")

    out = run_export_star(str(f), output_dir=str(tmp_path))

    db_path = tmp_path / "dqt.db"
    assert db_path.exists()
    assert not env_db.exists()
    assert out["quality_db_path"] == str(db_path)
    assert out["quality_db_status"] == "persisted"
    assert out["quality_db_error"] is None
    assert out["export_paths"]["quality_db"] == str(db_path)

    con = sqlite3.connect(str(db_path))
    try:
        run_id = out["run_id"]

        # runs table has exactly one row for this run
        assert con.execute("SELECT COUNT(*) FROM runs WHERE run_id=?", (run_id,)).fetchone()[0] == 1

        # quality_metrics: 2 columns × 3 metrics (null_pct, distinct_count, completeness) = 6
        assert (
            con.execute(
                "SELECT COUNT(*) FROM quality_metrics WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            == 6
        )

        # quality_history.jsonl still exists and has at least one record
        qh = Path(out["export_paths"]["quality_history"])
        assert qh.exists()
        record = json.loads(qh.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert "run_id" in record

        # star CSVs still exist
        for key in ("dim_dataset", "dim_column", "fact_profile_runs", "fact_quality_metrics"):
            assert Path(out["export_paths"][key]).exists()
    finally:
        con.close()


def test_run_export_star_without_output_dir_preserves_env_db_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    export_base = tmp_path / "exports"
    env_db = tmp_path / "db" / "custom.db"
    monkeypatch.setenv("EXPORT_BASE_DIR", str(export_base))
    monkeypatch.setenv("DQT_DB_PATH", str(env_db))

    f = tmp_path / "tiny.csv"
    f.write_text("id,age\n1,30\n2,40\n", encoding="utf-8")

    out = run_export_star(str(f))

    assert env_db.exists()
    assert out["quality_db_path"] == str(env_db)
    assert out["quality_db_status"] == "persisted"
    assert out["export_paths"]["quality_db"] == str(env_db)
    assert Path(out["export_paths"]["dim_dataset"]).is_relative_to(export_base)


def test_run_export_star_surfaces_sqlite_failure_in_result(tmp_path: Path) -> None:
    f = tmp_path / "tiny.csv"
    f.write_text("id,age\n1,30\n2,40\n", encoding="utf-8")

    with patch(
        "data_quality_toolkit.application.workflow.pipeline._persist_star_to_sqlite",
        side_effect=RuntimeError(r"cannot open C:\Users\example_user\private\dqt.db"),
    ):
        out = run_export_star(str(f), output_dir=str(tmp_path))

    assert out["run_id"]
    assert out["quality_db_path"] == str(tmp_path / "dqt.db")
    assert out["quality_db_status"] == "failed"
    assert "quality_db" not in out["export_paths"]
    assert "C:\\Users" not in str(out["quality_db_error"])
    assert "dqt.db" in str(out["quality_db_error"])
    assert Path(out["export_paths"]["dim_dataset"]).exists()
    assert Path(out["export_paths"]["quality_report"]).exists()
    assert Path(out["export_paths"]["quality_history"]).exists()


# --- managed export sibling -----------------------------------------------


# A trusted managed source is not merely a file plus some identifiers: the
# managed export path re-verifies path confinement, stat identity, and exact
# content identity immediately before it reads a single byte. These helpers
# therefore build a source that is genuinely trustworthy — written at the
# location its ``relative_posix`` claims, with its real size, stat, and
# canonical content identity — rather than one that only looks like one.

_MANAGED_RELATIVE_DIR = "preprocessed"
_MANAGED_CSV_BODY = "id,age\n1,30\n2,40\n"


def _managed_csv(tmp_path: Path, body: str = _MANAGED_CSV_BODY) -> Path:
    """Write a managed CSV at the confined ``preprocessed/managed.csv`` tail."""
    directory = tmp_path / _MANAGED_RELATIVE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    csv_path = directory / "managed.csv"
    csv_path.write_text(body, encoding="utf-8")
    return csv_path


def _managed_source(csv_path: Path, **overrides: object) -> VerifiedManagedExportSource:
    """Mint provenance that matches ``csv_path`` exactly as it is on disk."""
    resolved = csv_path.resolve()
    st = resolved.stat()
    values: dict[str, object] = {
        "version_id": str(uuid.uuid4()),
        "family_id": str(uuid.uuid4()),
        "content_id": managed_content_id_from_file(resolved),
        "root_content_id": "sha256:" + "b" * 64,
        "parent_version_id": None,
        "version_label": "cleaned v2",
        "display_name": resolved.name,
        "relative_posix": f"{_MANAGED_RELATIVE_DIR}/{resolved.name}",
        "size_bytes": int(st.st_size),
        "modified_ns": int(st.st_mtime_ns),
        "large_file_mode": False,
        "source_path": str(resolved),
    }
    values.update(overrides)
    return VerifiedManagedExportSource(**values)  # type: ignore[arg-type]


def test_managed_sibling_accepts_exactly_one_provenance_object() -> None:
    signature = inspect.signature(run_managed_export_star)
    parameters = list(signature.parameters.values())

    assert [p.name for p in parameters] == ["source", "output_dir"]
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters[1].kind is inspect.Parameter.KEYWORD_ONLY
    # No decomposed provenance parameters may exist.
    forbidden = {
        "version_id",
        "family_id",
        "content_id",
        "root_content_id",
        "managed_source_path",
        "df",
        "dataframe",
        "artifact_meta",
        "trust_root",
    }
    assert forbidden.isdisjoint(set(signature.parameters))


def test_legacy_export_star_signature_is_unchanged() -> None:
    signature = inspect.signature(run_export_star)
    names = list(signature.parameters)

    assert names == [
        "csv_path",
        "output_dir",
        "null_threshold",
        "sample_size",
        "emit_manifest",
        "artifact_meta",
        "read_csv_kwargs",
    ]
    # No optional managed argument was bolted onto the legacy function.
    assert "source" not in signature.parameters
    assert "managed_source" not in signature.parameters


def test_managed_export_produces_star_and_managed_block(tmp_path: Path) -> None:
    csv = _managed_csv(tmp_path)
    source = _managed_source(csv)

    out = run_managed_export_star(source, output_dir=str(tmp_path / "out"))

    assert set(out.keys()) >= {"run_id", "export_paths", "managed_source"}
    for path in out["export_paths"].values():
        assert Path(path).exists()

    managed = out["managed_source"]
    assert managed["version_id"] == source.version_id
    assert managed["family_id"] == source.family_id
    assert managed["content_id"] == source.content_id
    assert managed["root_content_id"] == source.root_content_id
    assert managed["version_label"] == source.version_label
    assert managed["relative_posix"] == source.relative_posix
    assert managed["large_file_mode"] is False


def test_managed_export_emits_manifest_with_managed_lineage(tmp_path: Path) -> None:
    csv = _managed_csv(tmp_path)
    source = _managed_source(csv)

    out = run_managed_export_star(source, output_dir=str(tmp_path / "out"))

    assert "manifest" in out["export_paths"]
    manifest_text = Path(out["export_paths"]["manifest"]).read_text(encoding="utf-8")
    assert source.version_id in manifest_text
    assert source.content_id in manifest_text
    assert source.relative_posix in manifest_text


def test_managed_manifest_metadata_never_carries_the_absolute_path(tmp_path: Path) -> None:
    csv = _managed_csv(tmp_path)
    source = _managed_source(csv)

    meta = _managed_artifact_meta(source)

    assert source.source_path not in json.dumps(meta)
    assert meta["managed"] is True
    assert meta["managed_source_relative_path"] == source.relative_posix
    assert "managed_source_path" not in meta
    assert "source_path" not in meta


def test_managed_artifact_meta_includes_parent_only_when_present(tmp_path: Path) -> None:
    csv = _managed_csv(tmp_path, "id,age\n1,30\n")

    without_parent = _managed_artifact_meta(_managed_source(csv))
    assert "managed_parent_version_id" not in without_parent

    parent_id = str(uuid.uuid4())
    with_parent = _managed_artifact_meta(_managed_source(csv, parent_version_id=parent_id))
    assert with_parent["managed_parent_version_id"] == parent_id


def test_managed_export_delegates_provenance_whole(tmp_path: Path) -> None:
    """The sibling hands the legacy path the source's own locator, undecomposed."""
    csv = _managed_csv(tmp_path, "id,age\n1,30\n")
    source = _managed_source(csv)

    with patch(
        "data_quality_toolkit.application.workflow.pipeline.run_export_star",
        return_value={"export_paths": {}},
    ) as legacy:
        run_managed_export_star(source, output_dir=str(tmp_path / "out"))

    assert legacy.call_count == 1
    assert legacy.call_args.args == (source.source_path,)
    assert legacy.call_args.kwargs["emit_manifest"] is True
    assert legacy.call_args.kwargs["artifact_meta"]["managed_version_id"] == source.version_id


def test_workflow_module_imports_no_ui_layer() -> None:
    tree = ast.parse(inspect.getsource(pipeline))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any(m.startswith("data_quality_toolkit.adapters.ui") for m in modules)
    assert "data_quality_toolkit.shared.managed_export_source" in modules


# --- portable export path privacy -------------------------------------------
#
# Portable export outputs never record a local host path: source provenance is a
# bare file name, and artifact locators are relative to the export root. The
# rule inputs below are plain strings, so each case means the same on any host.

_STAR_ARTIFACTS = ("dim_dataset", "dim_column", "fact_profile_runs", "fact_quality_metrics")
_EXPECTED_REPORT_ARTIFACTS = {
    name: f"star/{name}.csv" for name in (*_STAR_ARTIFACTS, "fact_issues")
}


@pytest.mark.parametrize(
    "source",
    [
        "C:\\Users\\alice\\data\\orders.csv",
        "C:/Users/alice/data/orders.csv",
        "\\\\server\\share\\team\\orders.csv",
        "//server/share/team/orders.csv",
        "/home/alice/data/orders.csv",
        "/Users/alice/data/orders.csv",
        "/tmp/pytest-of-runner/pytest-0/x/preprocessed/orders.csv",
        "C:orders.csv",
        "C:data\\orders.csv",
        "../../secret/orders.csv",
        "..\\..\\secret\\orders.csv",
        "mixed/dir\\sub/orders.csv",
        "./orders.csv",
        "orders.csv",
    ],
)
def test_portable_source_name_keeps_only_the_file_name(source: str) -> None:
    name = pipeline._portable_source_name(source)

    assert name == "orders.csv"
    assert not {"/", "\\", ":"} & set(name)


@pytest.mark.parametrize("source", ["", "   ", "/", "C:\\", "C:", "//", "a/..", "."])
def test_portable_source_name_fails_closed_without_a_safe_leaf(source: str) -> None:
    assert pipeline._portable_source_name(source) == PATH_REDACTED_DISPLAY


def test_portable_artifact_locator_is_export_root_relative(tmp_path: Path) -> None:
    root = tmp_path / "out"

    assert pipeline._portable_artifact_locator(root / "star" / "dim.csv", root) == "star/dim.csv"
    assert pipeline._portable_artifact_locator(str(root / "dqt.db"), root) == "dqt.db"
    assert (
        pipeline._portable_artifact_locator(Path("dist/star/x.csv"), Path("dist")) == "star/x.csv"
    )


@pytest.mark.parametrize(
    "artifact",
    [
        lambda root: root.parent / "db" / "custom.db",
        lambda root: root / "star" / ".." / ".." / "escape.csv",
        lambda root: root,
        lambda root: Path("relative") / "dqt.db",
    ],
)
def test_portable_artifact_locator_fails_closed_outside_the_root(
    tmp_path: Path, artifact: Any
) -> None:
    root = tmp_path / "out"

    assert pipeline._portable_artifact_locator(artifact(root), root) == PATH_REDACTED_DISPLAY


def _json_strings(node: object) -> list[str]:
    """Every string a parsed JSON document contains."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [value for item in node.values() for value in _json_strings(item)]
    if isinstance(node, list):
        return [value for item in node for value in _json_strings(item)]
    return []


def _jsonl_strings(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [value for line in lines if line.strip() for value in _json_strings(json.loads(line))]


def _csv_strings(path: Path) -> list[str]:
    with path.open(encoding="utf-8", newline="") as fh:
        return [cell for row in csv.reader(fh) for cell in row]


_SQL_STRING_LITERAL = re.compile(r"'((?:[^']|'')*)'")


def _sqlite_strings(path: Path) -> list[str]:
    """Every TEXT value in the database, read from its SQL dump (no dynamic queries)."""
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return [
            literal.replace("''", "'")
            for statement in con.iterdump()
            for literal in _SQL_STRING_LITERAL.findall(statement)
        ]
    finally:
        con.close()


_STRING_READERS = {
    ".json": lambda path: _json_strings(json.loads(path.read_text(encoding="utf-8"))),
    ".jsonl": _jsonl_strings,
    ".csv": _csv_strings,
    ".db": _sqlite_strings,
}


def _serialized_strings(path: Path) -> list[str]:
    """Every string value a structured export file serializes."""
    reader = _STRING_READERS.get(path.suffix)
    return reader(path) if reader is not None else []


def _looks_like_host_path(value: str) -> bool:
    """True for an absolute path under POSIX or Windows rules, read host-independently."""
    text = value.strip()
    if not text:
        return False
    windows = PureWindowsPath(text)
    return PurePosixPath(text).is_absolute() or bool(windows.drive) or bool(windows.root)


def _host_path_findings(export_root: Path, host_root: Path) -> list[str]:
    """Structural scan: serialized values that are host paths, or that expose ``host_root``."""
    markers = {str(host_root), host_root.as_posix(), json.dumps(str(host_root))[1:-1]}
    findings: list[str] = []
    for path in sorted(p for p in export_root.rglob("*") if p.is_file()):
        rel = path.relative_to(export_root).as_posix()
        raw = path.read_bytes()
        findings.extend(
            f"{rel}: raw bytes expose the host root" for m in markers if m.encode() in raw
        )
        findings.extend(
            f"{rel}: {value!r}"
            for value in _serialized_strings(path)
            if _looks_like_host_path(value)
        )
    return findings


def test_host_path_scan_detects_planted_paths(tmp_path: Path) -> None:
    """Self-test: the scan flags every planted form on any host, and nothing safe."""
    root = tmp_path / "planted"
    root.mkdir()
    (root / "a.json").write_text(json.dumps({"p": "C:\\Users\\alice\\x.csv"}), encoding="utf-8")
    (root / "b.csv").write_text("id,source_path\n1,/home/alice/x.csv\n", encoding="utf-8")
    (root / "c.jsonl").write_text(
        json.dumps({"q": "\\\\server\\share\\x.csv"}) + "\n", encoding="utf-8"
    )
    con = sqlite3.connect(root / "d.db")
    con.execute("CREATE TABLE t (v TEXT)")
    con.execute("INSERT INTO t VALUES ('/Users/alice/x.csv')")
    con.commit()
    con.close()
    (root / "e.json").write_text(json.dumps({"r": str(tmp_path / "leak.csv")}), encoding="utf-8")
    (root / "safe.json").write_text(
        json.dumps({"a": "orders.csv", "b": "star/dim_dataset.csv", "c": PATH_REDACTED_DISPLAY}),
        encoding="utf-8",
    )

    flagged = {finding.split(":", 1)[0] for finding in _host_path_findings(root, tmp_path)}

    assert flagged == {"a.json", "b.csv", "c.jsonl", "d.db", "e.json"}


def _datasets_source_paths(db_path: Path) -> set[str]:
    con = sqlite3.connect(str(db_path))
    try:
        return {row[0] for row in con.execute("SELECT source_path FROM datasets")}
    finally:
        con.close()


def _star_source_path(export_root: Path) -> str:
    with (export_root / "star" / "dim_dataset.csv").open(encoding="utf-8", newline="") as fh:
        return str(next(csv.DictReader(fh))["source_path"])


def test_unmanaged_export_outputs_carry_no_host_path(tmp_path: Path) -> None:
    source = tmp_path / "private source" / "nested" / "orders.csv"
    source.parent.mkdir(parents=True)
    source.write_text("id,amount\n1,10\n2,\n3,30\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    out = run_export_star(str(source), output_dir=str(out_dir), emit_manifest=True)

    manifest = json.loads(Path(out["export_paths"]["manifest"]).read_text(encoding="utf-8"))
    assert [d["path"] for d in manifest["datasets"]] == ["orders.csv"]
    assert all(not _looks_like_host_path(a["path"]) for a in manifest["artifacts"])
    assert _star_source_path(out_dir) == "orders.csv"
    assert _datasets_source_paths(out_dir / "dqt.db") == {"orders.csv"}
    report = json.loads((out_dir / "star" / "quality_report.json").read_text(encoding="utf-8"))
    assert report["artifacts"] == _EXPECTED_REPORT_ARTIFACTS
    assert _host_path_findings(out_dir, tmp_path) == []
    # In-memory results keep machine paths for callers; only outputs are portable.
    assert Path(out["export_paths"]["dim_dataset"]).is_absolute()


def test_second_export_into_the_same_folder_records_no_host_path(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    first = tmp_path / "src" / "orders.csv"
    second = tmp_path / "src" / "other" / "customers.csv"
    second.parent.mkdir(parents=True)
    first.write_text("id,amount\n1,10\n", encoding="utf-8")
    second.write_text("cid,name\n1,a\n2,b\n", encoding="utf-8")

    run_export_star(str(first), output_dir=str(out_dir))
    run_export_star(str(second), output_dir=str(out_dir), emit_manifest=True)

    assert _datasets_source_paths(out_dir / "dqt.db") == {"orders.csv", "customers.csv"}
    assert _host_path_findings(out_dir, tmp_path) == []


def test_out_of_root_quality_db_is_redacted_in_the_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    export_base = tmp_path / "exports"
    env_db = tmp_path / "db" / "custom.db"
    monkeypatch.setenv("EXPORT_BASE_DIR", str(export_base))
    monkeypatch.setenv("DQT_DB_PATH", str(env_db))
    source = tmp_path / "tiny.csv"
    source.write_text("id,age\n1,30\n2,40\n", encoding="utf-8")

    out = run_export_star(str(source), emit_manifest=True)

    assert out["export_paths"]["quality_db"] == str(env_db)
    raw = Path(out["export_paths"]["manifest"]).read_text(encoding="utf-8")
    paths = [a["path"] for a in json.loads(raw)["artifacts"]]
    assert paths.count(PATH_REDACTED_DISPLAY) == 1
    assert str(env_db) not in raw
    assert env_db.as_posix() not in raw
    assert _host_path_findings(export_base, tmp_path) == []
