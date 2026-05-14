from __future__ import annotations

import json
from pathlib import Path

from data_quality_toolkit.api import assess_csv, compare_runs, export_csv, profile_csv


def _tiny_csv(tmp_path: Path) -> Path:
    p = tmp_path / "tiny.csv"
    p.write_text("id,name,age\n1,Alice,30\n2,,35\n", encoding="utf-8")
    return p


# --- profile_csv ---


def test_profile_csv_accepts_string_path(tmp_path: Path) -> None:
    f = _tiny_csv(tmp_path)
    out = profile_csv(str(f))
    assert set(out.keys()) >= {"run_id", "dataset_id", "ts", "meta", "profile"}
    assert out["profile"]["rows"] >= 1


def test_profile_csv_accepts_path_object(tmp_path: Path) -> None:
    f = _tiny_csv(tmp_path)
    out_str = profile_csv(str(f))
    out_path = profile_csv(f)
    assert out_str["dataset_id"] == out_path["dataset_id"]
    assert out_str["profile"]["rows"] == out_path["profile"]["rows"]


def test_profile_csv_na_values_accepted(tmp_path: Path) -> None:
    f = _tiny_csv(tmp_path)
    out = profile_csv(f, na_values=["NA", ""])
    assert "profile" in out


# --- assess_csv ---


def test_assess_csv_returns_score_and_issues(tmp_path: Path) -> None:
    f = _tiny_csv(tmp_path)
    out = assess_csv(f)
    assert "assessment" in out
    asmt = out["assessment"]
    assert isinstance(asmt["score"], float)
    assert isinstance(asmt["issues"], list)


def test_assess_csv_null_threshold_accepted(tmp_path: Path) -> None:
    # name col: 1 of 2 rows null = 50 % missing rate
    # strict (0.4): 50 % >= 40 % => issue flagged
    # loose (0.6): 50 % < 60 % => no issue
    f = _tiny_csv(tmp_path)
    strict = assess_csv(f, null_threshold=0.4)
    loose = assess_csv(f, null_threshold=0.6)
    strict_missing = [i for i in strict["assessment"]["issues"] if i.get("type") == "missing"]
    loose_missing = [i for i in loose["assessment"]["issues"] if i.get("type") == "missing"]
    assert len(strict_missing) >= 1
    assert len(loose_missing) == 0


# --- export_csv ---


def test_export_csv_creates_artifacts(tmp_path: Path) -> None:
    f = _tiny_csv(tmp_path)
    out = export_csv(f, output_dir=tmp_path)
    paths = out["export_paths"]
    for key in ("dim_dataset", "dim_column", "fact_issues", "quality_report"):
        assert Path(paths[key]).exists(), f"missing artifact: {key}"


def test_export_csv_appends_history(tmp_path: Path) -> None:
    f = _tiny_csv(tmp_path)
    export_csv(f, output_dir=tmp_path)
    history = tmp_path / "star" / "quality_history.jsonl"
    assert history.exists()
    lines = history.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 1
    record = json.loads(lines[-1])
    assert "score" in record


# --- compare_runs ---


def test_compare_runs_not_enough_runs(tmp_path: Path) -> None:
    f = _tiny_csv(tmp_path)
    export_csv(f, output_dir=tmp_path)
    result = compare_runs(f, output_dir=tmp_path)
    assert result["error"] == "not_enough_runs"


def test_compare_runs_returns_deltas(tmp_path: Path) -> None:
    f = _tiny_csv(tmp_path)
    export_csv(f, output_dir=tmp_path)
    export_csv(f, output_dir=tmp_path)
    result = compare_runs(f, output_dir=tmp_path)
    assert "error" not in result
    assert "score_delta" in result
    assert result["dataset_id"].startswith("sha1:")


# --- top-level import ---


def test_api_importable_from_top_level() -> None:
    from data_quality_toolkit import assess_csv as _a
    from data_quality_toolkit import compare_runs as _c
    from data_quality_toolkit import export_csv as _e
    from data_quality_toolkit import profile_csv as _p

    assert callable(_p)
    assert callable(_a)
    assert callable(_e)
    assert callable(_c)
