from __future__ import annotations

from pathlib import Path

from data_quality_toolkit.workflow.pipeline import run_assessment, run_profile


def _write_tiny_csv(path: Path) -> None:
    path.write_text("id,name,age\n1,Alice,30\n2,,35\n", encoding="utf-8")


def test_run_profile_shapes_and_meta(tmp_path):
    f = tmp_path / "tiny.csv"
    _write_tiny_csv(f)

    out = run_profile(str(f))
    assert set(out.keys()) >= {"run_id", "dataset_id", "ts", "meta", "profile"}

    # meta
    meta = out["meta"]
    assert meta["dataset_id"].startswith("sha1:")
    assert Path(meta["source_path"]).exists()
    assert meta["rows"] >= 1 and meta["cols"] >= 1

    # profile
    prof = out["profile"]
    assert isinstance(prof["rows"], int)
    assert isinstance(prof["cols"], int)
    assert isinstance(prof["memory_mb"], float)
    assert isinstance(prof["columns"], list) and len(prof["columns"]) > 0
    names = {c["name"] for c in prof["columns"]}
    assert {"id", "name", "age"}.issubset(names)


def test_run_assessment_has_score_and_issues(tmp_path):
    f = tmp_path / "tiny.csv"
    _write_tiny_csv(f)

    out = run_assessment(str(f))
    assert set(out.keys()) >= {"run_id", "dataset_id", "ts", "meta", "profile", "assessment"}

    asmt = out["assessment"]
    assert isinstance(asmt["score"], float)
    assert isinstance(asmt["issues"], list)


def test_null_threshold_controls_completeness_issues(tmp_path):
    # CSV: 2 rows, 'name' has 1 null → 50 % missing rate.
    # threshold=0.6 → 50 % < 60 % → no completeness issue for 'name'
    # threshold=0.4 → 50 % ≥ 40 % → completeness issue flagged
    f = tmp_path / "tiny.csv"
    _write_tiny_csv(f)

    loose = run_assessment(str(f), null_threshold=0.6)
    strict = run_assessment(str(f), null_threshold=0.4)

    loose_completeness = [i for i in loose["assessment"]["issues"] if i.get("type") == "missing"]
    strict_completeness = [i for i in strict["assessment"]["issues"] if i.get("type") == "missing"]

    assert len(loose_completeness) == 0, "threshold=0.6 should not flag 50% null rate"
    assert len(strict_completeness) >= 1, "threshold=0.4 should flag 50% null rate"
