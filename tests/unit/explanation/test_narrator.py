"""Table-driven unit tests for the StoryLens Level 0 deterministic narrator."""

from __future__ import annotations

import pytest

from data_quality_toolkit.application.explanation import (
    Explanation,
    explain_constant_column_issue,
    explain_drift_detected,
    explain_export_artifacts,
    explain_missing_value_issue,
    explain_no_drift,
    explain_not_enough_runs,
    explain_quality_score,
)

# ---------------------------------------------------------------------------
# Type / shape guards
# ---------------------------------------------------------------------------


def _assert_shape(exp: Explanation) -> None:
    assert isinstance(exp, Explanation)
    assert isinstance(exp.title, str) and exp.title
    assert isinstance(exp.summary, str) and exp.summary
    assert isinstance(exp.evidence, tuple)
    assert all(isinstance(e, str) for e in exp.evidence)
    assert isinstance(exp.why_it_matters, str) and exp.why_it_matters
    assert isinstance(exp.recommended_action, str) and exp.recommended_action
    assert isinstance(exp.limitations, str) and exp.limitations
    assert exp.severity in ("info", "ok", "warn", "breach")


# ---------------------------------------------------------------------------
# 1. Quality score
# ---------------------------------------------------------------------------


def test_quality_score_ok():
    exp = explain_quality_score(score=0.95, rows=170, columns=14, issues_total=3)
    _assert_shape(exp)
    assert exp.severity == "ok"
    assert "95" in exp.title
    assert "170" in exp.summary
    assert "14" in exp.summary
    assert "3" in exp.summary


def test_quality_score_evidence_contains_exact_facts():
    exp = explain_quality_score(score=0.95, rows=170, columns=14, issues_total=3)
    ev = " ".join(exp.evidence)
    assert "score=0.9500" in ev
    assert "rows=170" in ev
    assert "columns=14" in ev
    assert "issues_total=3" in ev


def test_quality_score_warn_below_threshold():
    exp = explain_quality_score(score=0.75, rows=100, columns=5, issues_total=10)
    assert exp.severity == "warn"
    assert "75" in exp.title


def test_quality_score_boundary_090_is_ok():
    exp = explain_quality_score(score=0.90, rows=50, columns=3, issues_total=0)
    assert exp.severity == "ok"


def test_quality_score_boundary_089_is_warn():
    exp = explain_quality_score(score=0.899, rows=50, columns=3, issues_total=1)
    assert exp.severity == "warn"


def test_quality_score_determinism():
    a = explain_quality_score(score=0.95, rows=170, columns=14, issues_total=3)
    b = explain_quality_score(score=0.95, rows=170, columns=14, issues_total=3)
    assert a == b


# ---------------------------------------------------------------------------
# 2. Missing value
# ---------------------------------------------------------------------------


def test_missing_value_warn():
    exp = explain_missing_value_issue(column="discount_pct", null_pct=0.25)
    _assert_shape(exp)
    assert exp.severity == "warn"
    assert "discount_pct" in exp.title
    assert "25" in exp.title


def test_missing_value_evidence_facts():
    exp = explain_missing_value_issue(column="discount_pct", null_pct=0.25)
    ev = " ".join(exp.evidence)
    assert "column=discount_pct" in ev
    assert "null_pct=0.2500" in ev
    assert "issue_type=missing" in ev


def test_missing_value_no_root_cause():
    exp = explain_missing_value_issue(column="discount_pct", null_pct=0.25)
    assert "DQT reports the gap" in exp.limitations
    assert "cannot determine why" in exp.limitations


def test_missing_value_determinism():
    a = explain_missing_value_issue(column="notes", null_pct=0.40)
    b = explain_missing_value_issue(column="notes", null_pct=0.40)
    assert a == b


# ---------------------------------------------------------------------------
# 3. Constant column
# ---------------------------------------------------------------------------


def test_constant_column_shape():
    exp = explain_constant_column_issue(column="currency")
    _assert_shape(exp)
    assert exp.severity in ("info", "warn")
    assert "currency" in exp.title


def test_constant_column_evidence():
    exp = explain_constant_column_issue(column="currency")
    ev = " ".join(exp.evidence)
    assert "column=currency" in ev
    assert "constant_column" in ev


def test_constant_column_legitimacy_note():
    exp = explain_constant_column_issue(column="currency")
    full = exp.limitations + exp.recommended_action
    # Must acknowledge the column may be legitimately constant
    assert "legitimate" in full.lower() or "not an error" in full.lower()


def test_constant_column_determinism():
    a = explain_constant_column_issue(column="region")
    b = explain_constant_column_issue(column="region")
    assert a == b


# ---------------------------------------------------------------------------
# 4. Drift detected
# ---------------------------------------------------------------------------


def test_drift_detected_breach():
    exp = explain_drift_detected(column="quantity", metric="PSI", metric_value=0.35, breached=True)
    _assert_shape(exp)
    assert exp.severity == "breach"
    assert "quantity" in exp.title


def test_drift_detected_evidence():
    exp = explain_drift_detected(
        column="unit_price", metric="PSI", metric_value=0.28, breached=True
    )
    ev = " ".join(exp.evidence)
    assert "column=unit_price" in ev
    assert "drift_detected=true" in ev
    assert "PSI=0.2800" in ev
    assert "breached=True" in ev


def test_drift_detected_distribution_change_phrase():
    exp = explain_drift_detected(column="quantity", metric="PSI", metric_value=0.35, breached=True)
    full = exp.limitations + exp.summary
    assert "distribution change" in full.lower()


def test_drift_detected_no_defect_language():
    exp = explain_drift_detected(column="quantity", metric="PSI", metric_value=0.35, breached=True)
    # Limitations must carry the safety phrase
    assert "distribution change" in exp.limitations
    assert "not a defect" in exp.limitations


def test_drift_detected_not_breached_is_warn():
    exp = explain_drift_detected(column="quantity", metric="PSI", metric_value=0.10, breached=False)
    assert exp.severity == "warn"


def test_drift_detected_with_run_id():
    exp = explain_drift_detected(
        column="quantity", metric="JS", metric_value=0.15, breached=True, run_id="abc123"
    )
    ev = " ".join(exp.evidence)
    assert "run_id=abc123" in ev


def test_drift_detected_determinism():
    a = explain_drift_detected(column="price", metric="PSI", metric_value=0.4, breached=True)
    b = explain_drift_detected(column="price", metric="PSI", metric_value=0.4, breached=True)
    assert a == b


# ---------------------------------------------------------------------------
# 5. No drift
# ---------------------------------------------------------------------------


def test_no_drift_ok():
    exp = explain_no_drift(drift_detected=False, columns_tested=12, columns_skipped=2)
    _assert_shape(exp)
    assert exp.severity == "ok"


def test_no_drift_evidence():
    exp = explain_no_drift(drift_detected=False, columns_tested=12, columns_skipped=2)
    ev = " ".join(exp.evidence)
    assert "drift_detected=False" in ev
    assert "columns_tested=12" in ev
    assert "columns_skipped=2" in ev


def test_no_drift_only_tested_columns():
    exp = explain_no_drift(drift_detected=False, columns_tested=5)
    assert "only tested columns" in exp.limitations.lower()
    assert "skip_reason" in exp.limitations


def test_no_drift_determinism():
    a = explain_no_drift(drift_detected=False, columns_tested=8)
    b = explain_no_drift(drift_detected=False, columns_tested=8)
    assert a == b


# ---------------------------------------------------------------------------
# 6. Not enough runs
# ---------------------------------------------------------------------------


def test_not_enough_runs_info():
    exp = explain_not_enough_runs(run_count=1)
    _assert_shape(exp)
    assert exp.severity == "info"


def test_not_enough_runs_evidence():
    exp = explain_not_enough_runs(run_count=1)
    ev = " ".join(exp.evidence)
    assert "run_count=1" in ev
    assert "not_enough_runs" in ev


def test_not_enough_runs_recommends_two_exports():
    exp = explain_not_enough_runs(run_count=0)
    action = exp.recommended_action.lower()
    assert "export" in action
    assert "twice" in action or "at least two" in action or "least twice" in action


def test_not_enough_runs_zero():
    exp = explain_not_enough_runs(run_count=0)
    assert exp.severity == "info"
    assert "0" in exp.summary


def test_not_enough_runs_determinism():
    a = explain_not_enough_runs(run_count=1)
    b = explain_not_enough_runs(run_count=1)
    assert a == b


# ---------------------------------------------------------------------------
# 7. Export artifacts
# ---------------------------------------------------------------------------

_STANDARD_ARTIFACTS = (
    "quality_report.json",
    "fact_issues.csv",
    "fact_quality_metrics.csv",
)


def test_export_artifacts_ok():
    exp = explain_export_artifacts(artifact_basenames=_STANDARD_ARTIFACTS)
    _assert_shape(exp)
    assert exp.severity in ("ok", "info")


def test_export_artifacts_evidence_basenames_only():
    exp = explain_export_artifacts(artifact_basenames=_STANDARD_ARTIFACTS)
    for ev_item in exp.evidence:
        # Must not contain path separators
        assert "/" not in ev_item, f"Absolute path in evidence: {ev_item}"
        assert "\\" not in ev_item, f"Absolute path in evidence: {ev_item}"


def test_export_artifacts_known_names_described():
    exp = explain_export_artifacts(artifact_basenames=_STANDARD_ARTIFACTS)
    for name in _STANDARD_ARTIFACTS:
        assert name in exp.summary or any(name in e for e in exp.evidence)


def test_export_artifacts_count_in_title():
    exp = explain_export_artifacts(artifact_basenames=_STANDARD_ARTIFACTS)
    assert "3" in exp.title


def test_export_artifacts_determinism():
    a = explain_export_artifacts(artifact_basenames=_STANDARD_ARTIFACTS)
    b = explain_export_artifacts(artifact_basenames=_STANDARD_ARTIFACTS)
    assert a == b


def test_export_artifacts_outdir_basename_in_title():
    exp = explain_export_artifacts(artifact_basenames=_STANDARD_ARTIFACTS, outdir_name="dist/demo")
    assert "dist/demo" in exp.title


# ---------------------------------------------------------------------------
# 8. Type / shape across all functions
# ---------------------------------------------------------------------------

_ALL_SAMPLE_OUTPUTS = [
    lambda: explain_quality_score(score=0.95, rows=170, columns=14, issues_total=3),
    lambda: explain_missing_value_issue(column="discount_pct", null_pct=0.25),
    lambda: explain_constant_column_issue(column="currency"),
    lambda: explain_drift_detected(
        column="quantity", metric="PSI", metric_value=0.35, breached=True
    ),
    lambda: explain_no_drift(drift_detected=False, columns_tested=12, columns_skipped=2),
    lambda: explain_not_enough_runs(run_count=1),
    lambda: explain_export_artifacts(artifact_basenames=_STANDARD_ARTIFACTS),
]


@pytest.mark.parametrize("factory", _ALL_SAMPLE_OUTPUTS)
def test_all_outputs_valid_shape(factory):
    exp = factory()
    _assert_shape(exp)


@pytest.mark.parametrize("factory", _ALL_SAMPLE_OUTPUTS)
def test_all_outputs_are_deterministic(factory):
    assert factory() == factory()
