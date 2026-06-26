"""Tests for ExplanationProvenance contract and Explanation.provenance integration."""

from __future__ import annotations

import pytest

from data_quality_toolkit.application.explanation.models import Explanation
from data_quality_toolkit.application.explanation.provenance import ExplanationProvenance

# ── ExplanationProvenance contract ────────────────────────────────────────────


def test_provenance_is_frozen() -> None:
    prov = ExplanationProvenance(
        source_feature="data_overview",
        source_metric_keys=("quality_score",),
        generation_mode="deterministic",
    )
    with pytest.raises((AttributeError, TypeError)):
        prov.source_feature = "other"  # type: ignore[misc]


def test_provenance_is_hashable() -> None:
    prov = ExplanationProvenance(
        source_feature="eda_explorer",
        source_metric_keys=("score", "rows"),
        generation_mode="deterministic",
    )
    assert hash(prov) == hash(prov)
    assert {prov} == {prov}


def test_provenance_source_metric_keys_is_tuple() -> None:
    prov = ExplanationProvenance(
        source_feature="export",
        source_metric_keys=("artifact_count",),
        generation_mode="deterministic",
    )
    assert isinstance(prov.source_metric_keys, tuple)


def test_provenance_generation_mode_deterministic() -> None:
    prov = ExplanationProvenance(
        source_feature="run_history",
        source_metric_keys=("run_count",),
        generation_mode="deterministic",
    )
    assert prov.generation_mode == "deterministic"


def test_provenance_generation_mode_optional_ai() -> None:
    prov = ExplanationProvenance(
        source_feature="data_overview",
        source_metric_keys=("quality_score",),
        generation_mode="optional_ai",
    )
    assert prov.generation_mode == "optional_ai"


def test_provenance_optional_fields_default_none() -> None:
    prov = ExplanationProvenance(
        source_feature="drift_explorer",
        source_metric_keys=("drift_detected",),
        generation_mode="deterministic",
    )
    assert prov.dataset_id is None
    assert prov.run_id is None


def test_provenance_no_ts_field() -> None:
    """Narrators must not generate timestamps — no ts field on ExplanationProvenance."""
    prov = ExplanationProvenance(
        source_feature="data_overview",
        source_metric_keys=(),
        generation_mode="deterministic",
    )
    assert not hasattr(prov, "ts")


def test_provenance_equality() -> None:
    a = ExplanationProvenance(
        source_feature="eda_explorer",
        source_metric_keys=("score", "rows"),
        generation_mode="deterministic",
        run_id="r1",
    )
    b = ExplanationProvenance(
        source_feature="eda_explorer",
        source_metric_keys=("score", "rows"),
        generation_mode="deterministic",
        run_id="r1",
    )
    assert a == b


# ── Explanation.provenance integration ────────────────────────────────────────


def _make_explanation(**kwargs: object) -> Explanation:
    defaults: dict[str, object] = {
        "title": "T",
        "summary": "S",
        "evidence": ("e=1",),
        "why_it_matters": "W",
        "recommended_action": "A",
        "limitations": "L",
        "severity": "ok",
    }
    defaults.update(kwargs)
    return Explanation(**defaults)  # type: ignore[arg-type]


def test_explanation_provenance_defaults_to_none() -> None:
    exp = _make_explanation()
    assert exp.provenance is None


def test_explanation_accepts_provenance() -> None:
    prov = ExplanationProvenance(
        source_feature="data_overview",
        source_metric_keys=("quality_score",),
        generation_mode="deterministic",
    )
    exp = _make_explanation(provenance=prov)
    assert exp.provenance is prov
    assert exp.provenance.generation_mode == "deterministic"


def test_explanation_with_provenance_is_frozen() -> None:
    prov = ExplanationProvenance(
        source_feature="data_overview",
        source_metric_keys=("quality_score",),
        generation_mode="deterministic",
    )
    exp = _make_explanation(provenance=prov)
    with pytest.raises((AttributeError, TypeError)):
        exp.provenance = None  # type: ignore[misc]


def test_explanation_equality_considers_provenance() -> None:
    prov = ExplanationProvenance(
        source_feature="data_overview",
        source_metric_keys=("quality_score",),
        generation_mode="deterministic",
    )
    exp_with = _make_explanation(provenance=prov)
    exp_without = _make_explanation()
    assert exp_with != exp_without


def test_explanation_provenance_none_hashable() -> None:
    exp = _make_explanation()
    assert hash(exp) == hash(exp)


def test_explanation_provenance_attached_hashable() -> None:
    prov = ExplanationProvenance(
        source_feature="eda_explorer",
        source_metric_keys=("score",),
        generation_mode="deterministic",
    )
    exp = _make_explanation(provenance=prov)
    assert hash(exp) == hash(exp)
