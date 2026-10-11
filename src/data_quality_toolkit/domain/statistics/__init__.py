"""Statistical analysis domain modules.

Drift detection, the inferential tier, and the pure statistics kernel
(descriptive stats, distributions, confidence intervals, effect sizes,
bootstrap, and closed-form power). All kernel modules are pure and degrade
gracefully when the optional ``[stats]`` extra (scipy) is absent. No public
``api.py`` exposure is added here — this is the domain-internal surface.
"""

from data_quality_toolkit.domain.statistics.ab import compare_ab
from data_quality_toolkit.domain.statistics.bootstrap import bootstrap_ci
from data_quality_toolkit.domain.statistics.contracts import (
    Alternative,
    GroupStructure,
    HypothesisSetup,
    PValueResult,
    SelectionResult,
    TestKey,
    VariableType,
)
from data_quality_toolkit.domain.statistics.core import (
    confidence_level_to_t,
    confidence_level_to_z,
    scipy_available,
    z_to_confidence_level,
)
from data_quality_toolkit.domain.statistics.descriptive import (
    correlation_matrix,
    numeric_summary,
    quick_profile,
)
from data_quality_toolkit.domain.statistics.drift import detect_drift_frames
from data_quality_toolkit.domain.statistics.effect_size import (
    cliffs_delta,
    cohen_d,
    hodges_lehmann_ci,
    hodges_lehmann_estimate,
)
from data_quality_toolkit.domain.statistics.inference import calculate_p_value
from data_quality_toolkit.domain.statistics.inferential import (
    ab_compare,
    check_normality,
    compare_multi_group,
    compare_two_groups,
)
from data_quality_toolkit.domain.statistics.intervals import (
    ci_mean,
    ci_mean_diff,
    ci_prop,
    ci_prop_diff,
    ci_var,
    ci_var_ratio,
)
from data_quality_toolkit.domain.statistics.multivariate import (
    categorical_associations,
    covariance_matrix,
    grouped_numeric_by_category_summary,
    top_correlations,
    variance_inflation_factors,
)
from data_quality_toolkit.domain.statistics.power import (
    power_mean,
    power_prop,
    required_n_cohend,
    required_n_mean,
    required_n_prop,
    required_n_variance,
)
from data_quality_toolkit.domain.statistics.selection import select_test, suggest_tests

__all__ = [
    # domain-native hypothesis testing contracts and engines
    "Alternative",
    "GroupStructure",
    "HypothesisSetup",
    "PValueResult",
    "SelectionResult",
    "TestKey",
    "VariableType",
    "calculate_p_value",
    "compare_ab",
    "select_test",
    "suggest_tests",
    # drift + inferential tier (existing)
    "ab_compare",
    "check_normality",
    "compare_multi_group",
    "compare_two_groups",
    "detect_drift_frames",
    # core conversions + guard
    "confidence_level_to_t",
    "confidence_level_to_z",
    "z_to_confidence_level",
    "scipy_available",
    # descriptive
    "numeric_summary",
    "quick_profile",
    "correlation_matrix",
    # multivariate diagnostics
    "covariance_matrix",
    "variance_inflation_factors",
    "top_correlations",
    "categorical_associations",
    "grouped_numeric_by_category_summary",
    # effect sizes
    "cohen_d",
    "cliffs_delta",
    "hodges_lehmann_estimate",
    "hodges_lehmann_ci",
    # confidence intervals
    "ci_mean",
    "ci_mean_diff",
    "ci_prop",
    "ci_prop_diff",
    "ci_var",
    "ci_var_ratio",
    # bootstrap
    "bootstrap_ci",
    # power / sample size
    "power_mean",
    "power_prop",
    "required_n_mean",
    "required_n_prop",
    "required_n_variance",
    "required_n_cohend",
]
