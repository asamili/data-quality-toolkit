"""Tests for per-column weights and critical penalties."""

from typing import cast

from data_quality_toolkit.assessment.quality_checker import compute_quality_score, compute_score
from data_quality_toolkit.shared.models import Issue


def test_weighted_completeness_score():
    profile = {
        "rows": 100,
        "columns": [
            {"name": "col_good", "nulls": 0},  # 100% complete
            {"name": "col_bad", "nulls": 50},  # 50% complete
        ],
    }

    # Default weights (1.0, 1.0) -> (1.0 + 0.5) / 2 = 0.75
    assert compute_score(profile) == 0.75

    # Weighted: good_weight=3.0, bad_weight=1.0
    # (1.0*3 + 0.5*1) / 4 = 3.5 / 4 = 0.875
    config = {"columns": {"col_good": {"weight": 3.0}, "col_bad": {"weight": 1.0}}}
    assert compute_score(profile, config=config) == 0.875


def test_critical_column_penalty():
    completeness = 0.8
    # 1 Low issue on non-critical column: pen 0.01
    issue_low = cast(
        Issue,
        {
            "type": "duplicate_column_name",
            "column": "col_ok",
            "severity": "low",
            "category": "Schema",
        },
    )

    # 1 Low issue on critical column: pen 0.01 * 2 = 0.02
    issue_crit = cast(
        Issue,
        {
            "type": "duplicate_column_name",
            "column": "col_crit",
            "severity": "low",
            "category": "Schema",
        },
    )

    config = {"columns": {"col_crit": {"critical": True}}}

    # Test low + low crit
    score_low = compute_quality_score(completeness, [issue_low], config=config)
    score_crit = compute_quality_score(completeness, [issue_crit], config=config)

    # Low penalty is 0.01
    expected_low = completeness - 0.01
    expected_crit = completeness - 0.02

    assert round(score_low, 3) == round(expected_low, 3)
    assert round(score_crit, 3) == round(expected_crit, 3)


def test_missing_column_weight_graceful():
    # Weight for a missing column should not be added to total_weight
    profile = {
        "rows": 100,
        "columns": [
            {"name": "col_good", "nulls": 0},
        ],
    }
    config = {
        "columns": {
            "col_good": {"weight": 2.0},
            "col_missing": {"weight": 5.0},  # Should be ignored
        }
    }
    assert compute_score(profile, config=config) == 1.0
