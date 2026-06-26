"""Focused G27H-A deterministic drift-narration + provenance tests.

The drift narrators are pure: equal inputs produce equal outputs, they attach
deterministic provenance, and they never leak DB paths, raw bin labels, raw
categorical values, or generated timestamps. Importing them must not load any
optional AI package.
"""

from __future__ import annotations

import importlib
import sys

from data_quality_toolkit.application.explanation.narrator import (
    explain_drift_history_insufficient,
    explain_drift_threshold_fact,
    explain_run_drift_status,
)
from data_quality_toolkit.application.explanation.provenance import ExplanationProvenance

_OPTIONAL_AI_MODULES = frozenset(
    {
        "torch",
        "transformers",
        "tokenizers",
        "safetensors",
        "sentence_transformers",
        "huggingface_hub",
    }
)


def _all_text(exp) -> str:
    """Concatenate every user-facing string field for leak assertions."""
    return " ".join(
        (
            exp.title,
            exp.summary,
            *exp.evidence,
            exp.why_it_matters,
            exp.recommended_action,
            exp.limitations,
        )
    )


# --- insufficient drift history ----------------------------------------------


def test_insufficient_history_gives_drift_history_advice_not_export():
    exp = explain_drift_history_insufficient(run_count=1)
    action = exp.recommended_action.lower()
    assert "drift" in action
    # Must NOT reuse the generic Run-History / export advice.
    assert "dqt export" not in action
    assert "run history" not in action
    assert exp.severity == "info"


def test_insufficient_history_is_deterministic():
    assert explain_drift_history_insufficient(run_count=1) == explain_drift_history_insufficient(
        run_count=1
    )


def test_insufficient_history_distinguishes_trend_from_single_run_comparison():
    exp = explain_drift_history_insufficient(run_count=1)
    text = " ".join((exp.title, exp.summary, exp.why_it_matters, exp.limitations)).lower()
    # Must frame two runs as needed for a trend/history, not a single run's
    # reference-vs-current comparison.
    assert "trend" in text
    assert "reference-vs-current" in text or "reference vs current" in text


def test_insufficient_history_does_not_fabricate_drifted_zero():
    # Without an authoritative count, drifted_runs is unavailable, never 0.
    exp = explain_drift_history_insufficient(run_count=1)
    assert "drifted_runs=0" not in exp.evidence
    assert "drifted_runs=unavailable" in exp.evidence


def test_insufficient_history_uses_authoritative_drifted_count():
    exp = explain_drift_history_insufficient(run_count=1, drifted_runs=1)
    assert "drifted_runs=1" in exp.evidence
    assert "drifted_runs=0" not in exp.evidence


def test_unknown_drift_status_is_not_no_drift():
    exp = explain_run_drift_status(drift_detected=None)
    assert "unknown" in exp.title.lower()
    assert "drift_detected=unknown" in exp.evidence
    assert exp.severity == "info"
    assert "no drift" not in exp.title.lower()


def test_unknown_drift_status_is_deterministic():
    assert explain_run_drift_status(drift_detected=None) == explain_run_drift_status(
        drift_detected=None
    )


# --- drift-present / no-drift cards -------------------------------------------


def test_drift_present_card_exists_and_deterministic():
    a = explain_run_drift_status(drift_detected=True, columns_tested=4, columns_drifted=2)
    b = explain_run_drift_status(drift_detected=True, columns_tested=4, columns_drifted=2)
    assert a == b
    assert a.severity == "warn"
    assert "drift_detected=True" in a.evidence


def test_no_drift_card_exists_and_deterministic():
    a = explain_run_drift_status(drift_detected=False, columns_tested=4, columns_drifted=0)
    b = explain_run_drift_status(drift_detected=False, columns_tested=4, columns_drifted=0)
    assert a == b
    assert a.severity == "ok"


def test_run_status_missing_counts_render_na_not_zero():
    exp = explain_run_drift_status(drift_detected=True)
    assert "columns_tested=N/A" in exp.evidence
    assert "columns_tested=0" not in exp.evidence


# --- threshold fact: strict-greater breach semantics -------------------------


def test_threshold_equality_is_not_a_breach():
    exp = explain_drift_threshold_fact(metric="psi", metric_value=0.2, threshold=0.2)
    assert "breached=False" in exp.evidence
    assert exp.severity == "ok"


def test_threshold_strictly_greater_is_a_breach():
    exp = explain_drift_threshold_fact(metric="psi", metric_value=0.21, threshold=0.2)
    assert "breached=True" in exp.evidence
    assert exp.severity == "breach"


def test_threshold_missing_value_not_breach_and_na():
    exp = explain_drift_threshold_fact(metric="psi", metric_value=None, threshold=0.2)
    assert "breached=False" in exp.evidence
    assert "psi=N/A" in exp.evidence
    assert exp.severity == "ok"


# --- provenance contract ------------------------------------------------------


def test_provenance_is_deterministic_with_metric_keys():
    exp = explain_run_drift_status(drift_detected=True)
    prov = exp.provenance
    assert isinstance(prov, ExplanationProvenance)
    assert prov.generation_mode == "deterministic"
    assert prov.source_feature == "drift_monitoring"
    assert prov.source_metric_keys  # non-empty tuple


def test_provenance_ids_only_when_supplied():
    without = explain_run_drift_status(drift_detected=False).provenance
    assert without is not None
    assert without.dataset_id is None
    assert without.run_id is None
    with_ids = explain_run_drift_status(
        drift_detected=False, run_id="r9", dataset_id="cd1"
    ).provenance
    assert with_ids is not None
    assert with_ids.run_id == "r9"
    assert with_ids.dataset_id == "cd1"


def test_threshold_provenance_metric_keys_is_the_metric():
    prov = explain_drift_threshold_fact(
        metric="js_distance", metric_value=0.1, threshold=0.2
    ).provenance
    assert prov is not None
    assert prov.source_metric_keys == ("js_distance",)


# --- privacy: no paths / bin labels / categorical values / timestamps --------


def test_no_paths_or_raw_artifacts_in_drift_explanations():
    samples = [
        explain_drift_history_insufficient(run_count=1, dataset_id="cd1"),
        explain_run_drift_status(drift_detected=True, run_id="r1", dataset_id="cd1"),
        explain_drift_threshold_fact(metric="psi", metric_value=0.3, threshold=0.2, run_id="r1"),
    ]
    for exp in samples:
        text = _all_text(exp)
        assert ".db" not in text
        assert "/" not in text or "N/A" in text  # no posix paths (N/A is allowed)
        assert "\\" not in text  # no windows paths
        assert "[0," not in text  # no raw bin labels
        # Provenance carries no path/timestamp fields by construction.
        prov = exp.provenance
        assert not hasattr(prov, "ts")
        assert not hasattr(prov, "db_path")


# --- optional AI import guard -------------------------------------------------


def test_importing_drift_narration_does_not_load_optional_ai():
    importlib.import_module("data_quality_toolkit.application.explanation.narrator")
    importlib.import_module("data_quality_toolkit.application.monitoring.view_model")
    loaded = set(sys.modules)
    for mod in _OPTIONAL_AI_MODULES:
        assert mod not in loaded, f"Optional AI module loaded: {mod!r}"
