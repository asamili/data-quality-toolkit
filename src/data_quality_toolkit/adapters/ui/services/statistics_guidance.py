"""Framework-free interpretation guidance for Statistics Lab results.

This module turns an *already computed* statistical result into a typed,
deterministic reading aid. It never runs, re-runs, selects or changes a test, and
it never invents a value: every number it mentions is read straight off the
result contract, and anything the result did not produce is reported as an
explicitly unavailable field rather than defaulted, zeroed or guessed.

The guidance is deliberately evidence-oriented rather than verdict-oriented:

* a p-value is reported next to alpha and the alternative, and is never the only
  thing said about a result;
* not rejecting a null is never described as proof of the null, as equivalence,
  or as the absence of an effect;
* statistical evidence is never converted into practical importance, a causal
  claim, a post-hoc pairwise conclusion, or a business decision;
* assumption notes stay informational — they never switch a test, gate a result,
  or become a compliance score.

Structural rules: no Streamlit, no session state, no filesystem, no network, no
input mutation, and no statistical execution. Guidance and limitation lists are
capped and de-duplicated so a result can never emit an unbounded wall of text.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# Bounded guidance: no result may emit more than this many items per list.
GUIDANCE_MAX_ITEMS = 8
LIMITATIONS_MAX_ITEMS = 8

# Wording this module must never produce. Tests assert every generated string
# against this list so significance theatre and business verdicts cannot creep
# back in through a later edit.
FORBIDDEN_GUIDANCE_PHRASES: tuple[str, ...] = (
    "proves",
    "proven",
    "disproves",
    "disproved",
    "accept the null",
    "accepts the null",
    "definitely no",
    "therefore important",
    "therefore equivalent",
    "are equivalent",
    "caused by",
    "causes the",
    "we recommend",
    "you should",
    "a good result",
    "a bad result",
    "passes the test",
    "fails the test",
)

# Reusable caveats. Each states one limit of the evidence without implying a
# decision the evidence cannot support.
_CAVEAT_PRACTICAL = (
    "Whether a difference of this size matters is a domain judgement; the "
    "statistics here measure evidence, not importance."
)
_CAVEAT_NON_REJECTION = (
    "Not rejecting the null is not evidence that the null holds, and it does not "
    "establish equivalence or the absence of an effect."
)
_CAVEAT_MULTIPLE = (
    "p-values shown in Statistics Lab are uncorrected for multiple testing; "
    "running many comparisons raises the chance of at least one small p-value."
)
_CAVEAT_OBSERVATIONAL = (
    "These values describe the analyzed rows. Without a randomised or otherwise "
    "controlled design, a difference here does not establish cause."
)
_CAVEAT_EXCLUSION = (
    "Rows excluded for missing or non-finite values are not missing at random by "
    "assumption; check whether the excluded rows differ from the retained ones."
)


@dataclass(frozen=True)
class ResultGuidance:
    """One result's deterministic, capped interpretation structure.

    ``estimate``, ``uncertainty``, ``evidence`` and ``effect`` are ``None`` when
    the result did not expose the underlying value; the field name is then listed
    in ``unavailable`` so absence is visible rather than silently filled.
    """

    family: str
    compared: str
    estimate: str | None = None
    uncertainty: str | None = None
    evidence: str | None = None
    effect: str | None = None
    assumptions: tuple[str, ...] = field(default_factory=tuple)
    limitations: tuple[str, ...] = field(default_factory=tuple)
    do_not_conclude: tuple[str, ...] = field(default_factory=tuple)
    next_steps: tuple[str, ...] = field(default_factory=tuple)
    unavailable: tuple[str, ...] = field(default_factory=tuple)


# ── shared construction helpers ───────────────────────────────────────────────


def _capped(items: Iterable[Any], limit: int) -> tuple[str, ...]:
    """Return de-duplicated, order-preserving, capped text items."""
    kept: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in kept:
            continue
        kept.append(text)
        if len(kept) >= limit:
            break
    return tuple(kept)


def _guidance(
    family: str,
    compared: str,
    *,
    estimate: str | None = None,
    uncertainty: str | None = None,
    evidence: str | None = None,
    effect: str | None = None,
    assumptions: Iterable[Any] = (),
    limitations: Iterable[Any] = (),
    do_not_conclude: Iterable[Any] = (),
    next_steps: Iterable[Any] = (),
    unavailable: Iterable[Any] = (),
) -> ResultGuidance:
    """Assemble a capped guidance structure, marking empty sections unavailable."""
    missing = list(unavailable)
    for name, value in (
        ("estimate", estimate),
        ("uncertainty", uncertainty),
        ("evidence", evidence),
        ("effect", effect),
    ):
        if value is None:
            missing.append(name)
    return ResultGuidance(
        family=str(family),
        compared=str(compared),
        estimate=estimate,
        uncertainty=uncertainty,
        evidence=evidence,
        effect=effect,
        assumptions=_capped(assumptions, GUIDANCE_MAX_ITEMS),
        limitations=_capped(limitations, LIMITATIONS_MAX_ITEMS),
        do_not_conclude=_capped(do_not_conclude, GUIDANCE_MAX_ITEMS),
        next_steps=_capped(next_steps, GUIDANCE_MAX_ITEMS),
        unavailable=_capped(missing, GUIDANCE_MAX_ITEMS),
    )


def _number(value: Any) -> str | None:
    """Format a finite number for guidance text, or None when it is unusable."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return f"{number:.4g}"


def _count(value: Any) -> str | None:
    text = _number(value)
    if text is None:
        return None
    try:
        return f"{int(float(value)):,}"
    except (TypeError, ValueError, OverflowError):
        return text


def _label(value: Any, fallback: str) -> str:
    text = "" if value is None else str(value).strip()
    return text or fallback


def _is_ok(result: Mapping[str, Any]) -> bool:
    return str(result.get("status") or "") == "ok"


def _evidence_sentence(
    result: Mapping[str, Any],
    *,
    mention_alternative: bool = True,
) -> str | None:
    """Describe the hypothesis-test evidence without turning it into a verdict.

    Reports the result's own p-value, alpha and decision verbatim. ``mention_
    alternative`` is disabled for right-tail chi-square families, whose contract
    carries no directional alternative to report.
    """
    p_value = _number(result.get("p_value"))
    alpha = _number(result.get("alpha"))
    if p_value is None or alpha is None:
        return None
    reject = result.get("reject_null")
    if reject is None:
        reject = result.get("significant")
    if reject is True:
        stance = f"the p-value {p_value} is below alpha {alpha}, so the null is rejected"
    elif reject is False:
        stance = f"the p-value {p_value} is not below alpha {alpha}, so the null is not rejected"
    else:
        return None
    if mention_alternative:
        stance = f"{stance} for the {_label(result.get('alternative'), 'two-sided')} alternative"
    return (
        f"Evidence: {stance}. A p-value measures how surprising the data are under "
        "the null; it does not measure the size of the difference."
    )


def _shared_do_not_conclude(*, non_rejection: bool) -> list[str]:
    items = [
        "A small p-value is a statement about evidence against the null, not about "
        "how large or how useful the difference is.",
        _CAVEAT_PRACTICAL,
    ]
    if non_rejection:
        items.insert(0, _CAVEAT_NON_REJECTION)
    return items


def _non_rejection(result: Mapping[str, Any]) -> bool:
    reject = result.get("reject_null")
    if reject is None:
        reject = result.get("significant")
    return reject is False


def _exclusion_note(result: Mapping[str, Any]) -> str | None:
    excluded = _count(result.get("excluded_rows"))
    if excluded is None or excluded == "0":
        return None
    return f"{excluded} row(s) were excluded for a missing or non-finite value. {_CAVEAT_EXCLUSION}"


# ── chi-square goodness of fit ────────────────────────────────────────────────


def guidance_for_goodness_of_fit(
    result: Mapping[str, Any],
    *,
    evidence: Mapping[str, Any] | None = None,
) -> ResultGuidance:
    """Guidance for a completed chi-square goodness-of-fit result."""
    column = _label(result.get("column"), "the selected column")
    mode = _label(result.get("expected_mode"), "equal")
    compared = (
        f"The observed category distribution of {column} against the "
        f"{mode} expected distribution."
    )
    if not _is_ok(result):
        return _guidance(
            "chi-square goodness of fit",
            compared,
            unavailable=["result"],
            limitations=["No completed result is available to interpret."],
        )
    categories = _count(result.get("category_count"))
    valid = _count(result.get("valid_rows"))
    estimate = (
        f"Observed counts across {categories or 'the retained'} categories "
        f"({valid or 'the retained'} retained rows) beside their expected counts."
    )
    top = _top_contribution_text(evidence)
    assumptions = [
        "Rows are treated as independent observations of one categorical column.",
        "Expected counts should be large enough for the chi-square approximation; "
        "the result's own expected-count notes are informational and do not change the test.",
    ]
    return _guidance(
        "chi-square goodness of fit",
        compared,
        estimate=estimate,
        uncertainty=None,
        evidence=_evidence_sentence(result, mention_alternative=False),
        effect=top,
        assumptions=assumptions,
        limitations=[
            "A cell contribution localises where observed and expected disagree; it does "
            "not explain why they disagree.",
            _exclusion_note(result),
            _CAVEAT_MULTIPLE,
        ],
        do_not_conclude=_shared_do_not_conclude(non_rejection=_non_rejection(result))
        + ["A mismatch with the expected distribution does not identify its source."],
        next_steps=[
            "Check whether the largest-contribution categories reflect a real process "
            "change or a data-quality issue such as a renamed or split category.",
            "Review how the expected distribution was chosen before reading the result further.",
        ],
    )


def _top_contribution_text(evidence: Mapping[str, Any] | None) -> str | None:
    """Name the largest-contribution category from prepared evidence, if any."""
    if not isinstance(evidence, Mapping) or str(evidence.get("status") or "") != "ok":
        return None
    if not evidence.get("contribution_available"):
        return None
    data = evidence.get("data")
    records: Sequence[Mapping[str, Any]]
    try:
        records = data.to_dict("records")  # type: ignore[union-attr]
    except AttributeError:
        return None
    ranked = [row for row in records if _number(row.get("contribution")) is not None]
    if not ranked:
        return None
    top = max(ranked, key=lambda row: float(row.get("contribution") or 0.0))
    share = _number(top.get("contribution_share"))
    label = _label(top.get("category"), "a category")
    difference = _number(top.get("difference"))
    if difference is None:
        direction = "away from"
    else:
        direction = "above" if float(difference) > 0 else "below"
    share_text = f" ({share} of the total chi-square contribution)" if share else ""
    return (
        f"Largest mismatch: {label} is {direction} its expected count{share_text}. "
        "Contribution shows where the mismatch sits, not what produced it."
    )


# ── chi-square independence / homogeneity ─────────────────────────────────────

_INDEPENDENCE = "independence"
_HOMOGENEITY = "homogeneity"


def guidance_for_contingency(
    result: Mapping[str, Any],
    *,
    family: str = _INDEPENDENCE,
    evidence: Mapping[str, Any] | None = None,
) -> ResultGuidance:
    """Guidance for a completed contingency chi-square result."""
    homogeneity = str(family) == _HOMOGENEITY
    title = f"chi-square {_HOMOGENEITY if homogeneity else _INDEPENDENCE}"
    if homogeneity:
        compared = (
            f"The outcome distribution of {_label(result.get('outcome_column'), 'the outcome')} "
            f"across the groups in {_label(result.get('group_column'), 'the group column')}."
        )
        null_note = "The null is that every group has the same outcome distribution."
        not_conclude = (
            "A difference between groups does not identify which group differs, or by how much."
        )
    else:
        compared = (
            f"Whether {_label(result.get('first_column'), 'the first column')} and "
            f"{_label(result.get('second_column'), 'the second column')} vary together."
        )
        null_note = "The null is that the two variables are independent."
        not_conclude = (
            "An association between two categorical columns does not establish that one "
            "drives the other, or that a third factor is absent."
        )
    if not _is_ok(result):
        return _guidance(
            title,
            compared,
            unavailable=["result"],
            limitations=["No completed result is available to interpret."],
        )
    return _guidance(
        title,
        compared,
        estimate=_contingency_estimate_text(result),
        uncertainty=None,
        evidence=_evidence_sentence(result, mention_alternative=False),
        effect=_top_residual_text(evidence),
        assumptions=[
            null_note,
            "Each row contributes to exactly one cell and rows are treated as independent.",
            _sparse_note(evidence),
        ],
        limitations=[
            "A signed residual shows the direction of a cell's departure from its expected "
            "count; it carries no p-value of its own.",
            _exclusion_note(result),
            _CAVEAT_OBSERVATIONAL,
            _CAVEAT_MULTIPLE,
        ],
        do_not_conclude=_shared_do_not_conclude(non_rejection=_non_rejection(result))
        + [not_conclude],
        next_steps=[
            "Inspect the largest-residual cells to see where the table departs from its "
            "expected counts.",
            "Confirm the category definitions are stable before reading the pattern further.",
        ],
    )


def _contingency_estimate_text(result: Mapping[str, Any]) -> str | None:
    rows = _count(result.get("row_category_count"))
    cols = _count(result.get("col_category_count"))
    valid = _count(result.get("valid_rows"))
    if rows is None or cols is None:
        return None
    return (
        f"Observed and expected counts for a {rows} x {cols} table built from "
        f"{valid or 'the retained'} retained rows."
    )


def _sparse_note(evidence: Mapping[str, Any] | None) -> str | None:
    if not isinstance(evidence, Mapping) or str(evidence.get("status") or "") != "ok":
        return None
    low = evidence.get("low_expected_cells")
    if not low:
        return None
    return (
        f"{low} cell(s) have a small expected count, which makes the chi-square "
        "approximation less reliable. This note is informational and does not change the test."
    )


def _top_residual_text(evidence: Mapping[str, Any] | None) -> str | None:
    if not isinstance(evidence, Mapping) or str(evidence.get("status") or "") != "ok":
        return None
    ranked = evidence.get("ranked")
    try:
        records = ranked.to_dict("records")  # type: ignore[union-attr]
    except AttributeError:
        return None
    if not records:
        return None
    top = records[0]
    residual = _number(top.get("residual"))
    if residual is None:
        return None
    direction = _label(top.get("direction"), "departs from its expected count")
    return (
        f"Largest departure: {_label(top.get('row_category'), 'row')} x "
        f"{_label(top.get('col_category'), 'column')} is {direction} "
        f"(Pearson residual {residual})."
    )


# ── estimates and confidence intervals ────────────────────────────────────────


def guidance_for_interval(
    result: Mapping[str, Any],
    *,
    label: str = "the estimated mean",
    reference: Any = None,
) -> ResultGuidance:
    """Guidance for a completed estimate-with-interval result."""
    compared = f"{label} for the selected column, with an interval around it."
    if not _is_ok(result):
        return _guidance(
            "estimate and confidence interval",
            compared,
            unavailable=["result"],
            limitations=["No completed interval is available to interpret."],
        )
    point = _number(result.get("point"))
    lower = _number(result.get("lower"))
    upper = _number(result.get("upper"))
    confidence = _number(result.get("confidence"))
    sample = _count(result.get("n"))
    estimate = None if point is None else f"Point estimate {point} from n={sample or 'unknown'}."
    uncertainty = None
    if lower is not None and upper is not None:
        level = f"{float(confidence) * 100:.0f}%" if confidence else "the selected"
        uncertainty = (
            f"{level} interval from {lower} to {upper}. Intervals of this kind capture the "
            "true value at the stated rate across repeated samples; this one interval either "
            "does or does not contain it."
        )
    reference_note = _reference_note(reference, lower, upper)
    return _guidance(
        "estimate and confidence interval",
        compared,
        estimate=estimate,
        uncertainty=uncertainty,
        evidence=reference_note,
        effect=None,
        assumptions=[
            "The interval assumes the retained values are an independent sample from the "
            "population you want to describe.",
            f"Method reported by the result: {_label(result.get('method'), 'not reported')}.",
        ],
        limitations=[
            "An interval covering a reference value is not evidence that the true value "
            "equals that reference.",
            _CAVEAT_PRACTICAL,
        ],
        do_not_conclude=[
            "A wide interval means the data are compatible with many values, not that the "
            "estimate is wrong.",
            "An interval describes the estimated quantity only; it says nothing about "
            "individual rows.",
        ],
        next_steps=[
            "Compare the interval width against the smallest difference that would matter "
            "for your use.",
            "If the interval is too wide to be useful, plan a larger sample in Power & "
            "Sample size.",
        ],
    )


def _reference_note(reference: Any, lower: str | None, upper: str | None) -> str | None:
    value = _number(reference)
    if value is None or lower is None or upper is None:
        return None
    inside = float(lower) <= float(value) <= float(upper)
    if inside:
        return (
            f"The reference value {value} lies inside the interval, so the data are "
            "compatible with it — that is not the same as showing it is the true value."
        )
    return (
        f"The reference value {value} lies outside the interval, so the data are less "
        "compatible with it at this confidence level."
    )


# ── paired results ────────────────────────────────────────────────────────────


def guidance_for_paired(
    result: Mapping[str, Any],
    *,
    first: str,
    second: str,
    evidence: Mapping[str, Any] | None = None,
) -> ResultGuidance:
    """Guidance for a completed paired result (parametric or signed-rank)."""
    compared = (
        f"Paired differences computed as {first} minus {second} on the rows where both "
        "measurements are present."
    )
    if not _is_ok(result):
        return _guidance(
            "paired comparison",
            compared,
            unavailable=["result"],
            limitations=["No completed paired result is available to interpret."],
        )
    pairs = _count(result.get("n_pairs"))
    excluded = _count(result.get("n_excluded_rows")) or _count(result.get("excluded_rows"))
    estimate = _paired_estimate_text(evidence, pairs)
    return _guidance(
        "paired comparison",
        compared,
        estimate=estimate,
        uncertainty=None,
        evidence=_evidence_sentence(result),
        effect=None,
        assumptions=[
            "Pairs are formed positionally: each row supplies one before value and one "
            "after value for the same unit.",
            "A row is used only when both measurements are present and finite"
            + (f"; {excluded} row(s) were excluded." if excluded and excluded != "0" else "."),
            "Paired tests describe the differences within pairs, not two independent groups.",
        ],
        limitations=[
            "Movement within pairs is described here, not explained. Without a controlled "
            "design, a shift between the two measurements does not establish cause.",
            _CAVEAT_PRACTICAL,
            _CAVEAT_EXCLUSION,
        ],
        do_not_conclude=_shared_do_not_conclude(non_rejection=_non_rejection(result))
        + [
            "The direction of the difference follows the order you selected; reversing the "
            "two columns reverses the sign without changing the evidence."
        ],
        next_steps=[
            "Look at the spread of the paired differences, not only their centre.",
            "Check whether the excluded incomplete pairs share a pattern.",
        ],
    )


def _paired_estimate_text(evidence: Mapping[str, Any] | None, pairs: str | None) -> str | None:
    if not isinstance(evidence, Mapping) or str(evidence.get("status") or "") != "ok":
        return None
    summary = evidence.get("difference_summary")
    if not isinstance(summary, Mapping):
        return None
    median = _number(summary.get("median"))
    low = _number(summary.get("minimum"))
    high = _number(summary.get("maximum"))
    if median is None:
        return None
    return (
        f"Across {pairs or 'the complete'} pairs the median difference is {median} "
        f"(range {low} to {high}). These are descriptive summaries of the same differences "
        "the test used."
    )


# ── proportions ───────────────────────────────────────────────────────────────


def guidance_for_proportion(result: Mapping[str, Any], *, mode: str = "one") -> ResultGuidance:
    """Guidance for a completed one- or two-proportion result."""
    two = str(mode) == "two"
    outcome = _label(result.get("outcome_column"), "the outcome column")
    success = _label(result.get("success_label"), "the selected success value")
    if two:
        compared = (
            f"The share of {success} in {outcome} between "
            f"{_label(result.get('group_a_label'), 'the first group')} and "
            f"{_label(result.get('group_b_label'), 'the second group')} "
            "(first minus second)."
        )
    else:
        compared = (
            f"The observed share of {success} in {outcome} against the null proportion "
            f"{_number(result.get('null_proportion')) or 'you entered'}."
        )
    if not _is_ok(result):
        return _guidance(
            "proportion comparison",
            compared,
            unavailable=["result"],
            limitations=["No completed proportion result is available to interpret."],
        )
    estimate, effect = _proportion_estimate(result, two=two)
    return _guidance(
        "proportion comparison",
        compared,
        estimate=estimate,
        uncertainty=None,
        evidence=_evidence_sentence(result),
        effect=effect,
        assumptions=[
            "Each row contributes one binary outcome and rows are treated as independent.",
            "Categories keep their original typed identity, so values that merely look alike "
            "are never merged.",
            "The normal approximation behind a z-test is weaker when successes or failures "
            "are few.",
        ],
        limitations=[
            "This result exposes counts and proportions; no interval is drawn unless the "
            "result itself carries one.",
            _exclusion_note(result),
            _CAVEAT_OBSERVATIONAL,
        ],
        do_not_conclude=_shared_do_not_conclude(non_rejection=_non_rejection(result))
        + ["A difference in shares does not by itself say the difference is worth acting on."],
        next_steps=[
            "Read the difference next to its denominators — the same gap means less with "
            "few observations.",
            "Use Power & Sample size to see what difference the current sample could detect.",
        ],
    )


def _proportion_estimate(result: Mapping[str, Any], *, two: bool) -> tuple[str | None, str | None]:
    if two:
        p_a = _number(result.get("proportion_a"))
        p_b = _number(result.get("proportion_b"))
        difference = _number(result.get("proportion_difference"))
        if p_a is None or p_b is None:
            return None, None
        estimate = (
            f"{_count(result.get('successes_a'))} of {_count(result.get('n_a'))} ({p_a}) "
            f"versus {_count(result.get('successes_b'))} of {_count(result.get('n_b'))} ({p_b})."
        )
        effect = (
            None
            if difference is None
            else f"Observed difference (first minus second): {difference}."
        )
        return estimate, effect
    observed = _number(result.get("observed_proportion"))
    if observed is None:
        return None, None
    estimate = (
        f"{_count(result.get('success_count'))} successes in "
        f"{_count(result.get('valid_rows'))} valid rows ({observed})."
    )
    null_value = _number(result.get("null_proportion"))
    effect = (
        None
        if null_value is None
        else f"Observed proportion {observed} against the null proportion {null_value}."
    )
    return estimate, effect


# ── group comparisons and effect sizes ────────────────────────────────────────


def guidance_for_two_group(result: Mapping[str, Any]) -> ResultGuidance:
    """Guidance for the existing two-group numeric comparison panel."""
    group_a = _label(result.get("group_a"), "group A")
    group_b = _label(result.get("group_b"), "group B")
    metric = _label(result.get("metric"), "the selected metric")
    compared = f"{metric} between {group_a} and {group_b}."
    if not _is_ok(result):
        return _guidance(
            "two-group comparison",
            compared,
            unavailable=["result"],
            limitations=["No completed group comparison is available to interpret."],
        )
    mean_a = _number(result.get("mean_a"))
    mean_b = _number(result.get("mean_b"))
    delta = _number(result.get("delta_mean"))
    cohens_d = _number(result.get("cohens_d"))
    estimate = (
        None
        if mean_a is None or mean_b is None
        else (
            f"Group means {mean_a} ({group_a}, n={_count(result.get('n_a'))}) and "
            f"{mean_b} ({group_b}, n={_count(result.get('n_b'))})."
        )
    )
    effect = None if delta is None else f"Difference in means (A minus B): {delta}."
    if cohens_d is not None:
        effect = f"{effect or ''} Standardised difference (Cohen's d): {cohens_d}.".strip()
    return _guidance(
        "two-group comparison",
        compared,
        estimate=estimate,
        uncertainty=None,
        evidence=_two_group_evidence(result),
        effect=effect,
        assumptions=[
            "The two groups are treated as independent samples.",
            "The Welch test does not assume equal variances; the rank test does not assume "
            "normal data.",
            "Assumption checks in this tab are informational and never change which test ran.",
        ],
        limitations=[
            "This panel reports two two-sided tests on the same split; reading whichever is "
            "smaller inflates the chance of a small p-value.",
            _CAVEAT_OBSERVATIONAL,
            _CAVEAT_PRACTICAL,
        ],
        do_not_conclude=_shared_do_not_conclude(non_rejection=False) + [_CAVEAT_NON_REJECTION],
        next_steps=[
            "Read the group centres and spread together with the test evidence.",
            "If the two tests disagree, look at skew and outliers before choosing what to "
            "report.",
        ],
    )


def _two_group_evidence(result: Mapping[str, Any]) -> str | None:
    welch = result.get("welch")
    mann = result.get("mann_whitney")
    alpha = _number(result.get("alpha"))
    if not isinstance(welch, Mapping) or not isinstance(mann, Mapping) or alpha is None:
        return None
    welch_p = _number(welch.get("p_value"))
    mann_p = _number(mann.get("p_value"))
    if welch_p is None or mann_p is None:
        return None
    return (
        f"Evidence at alpha {alpha}: Welch t-test p={welch_p}, Mann-Whitney U p={mann_p}. "
        "Both are two-sided and neither measures how large the difference is."
    )


def guidance_for_multi_group(result: Mapping[str, Any]) -> ResultGuidance:
    """Guidance for the existing omnibus multi-group comparison."""
    metric = _label(result.get("metric"), "the selected metric")
    group_col = _label(result.get("group_col"), "the group column")
    compared = f"{metric} across the levels of {group_col} in one omnibus test."
    if not _is_ok(result):
        return _guidance(
            "multi-group omnibus comparison",
            compared,
            unavailable=["result"],
            limitations=["No completed omnibus result is available to interpret."],
        )
    groups = _count(result.get("n_groups"))
    return _guidance(
        "multi-group omnibus comparison",
        compared,
        estimate=f"Per-group sizes and centres across {groups or 'the retained'} groups.",
        uncertainty=None,
        evidence=_multi_group_evidence(result),
        effect=None,
        assumptions=[
            "ANOVA assumes roughly normal residuals and comparable variances; "
            "Kruskal-Wallis compares distributions by rank instead.",
            "Groups are treated as independent samples.",
        ],
        limitations=[
            "An omnibus result does not identify which groups differ, and this panel "
            "performs no post-hoc pairwise comparison.",
            "Group truncation, when reported by the result, changes which levels were tested.",
            _CAVEAT_OBSERVATIONAL,
        ],
        do_not_conclude=_shared_do_not_conclude(non_rejection=False)
        + [
            "Do not read the largest group mean as the group that differs; that is a "
            "pairwise claim this test does not make.",
            _CAVEAT_NON_REJECTION,
        ],
        next_steps=[
            "Use the per-group summary to see spread and sizes before interpreting the "
            "omnibus evidence.",
            "If a specific pair matters, compare that pair deliberately rather than reading "
            "it out of the omnibus result.",
        ],
    )


def _multi_group_evidence(result: Mapping[str, Any]) -> str | None:
    anova = result.get("anova")
    kruskal = result.get("kruskal")
    alpha = _number(result.get("alpha"))
    if not isinstance(anova, Mapping) or not isinstance(kruskal, Mapping) or alpha is None:
        return None
    anova_p = _number(anova.get("p_value"))
    kruskal_p = _number(kruskal.get("p_value"))
    if anova_p is None or kruskal_p is None:
        return None
    return (
        f"Evidence at alpha {alpha}: ANOVA p={anova_p}, Kruskal-Wallis p={kruskal_p}. "
        "Both ask only whether some group differs, not which one."
    )


def guidance_for_effect_sizes(result: Mapping[str, Any]) -> ResultGuidance:
    """Guidance for the existing nonparametric effect-size panel."""
    group_a = _label(result.get("group_a"), "group A")
    group_b = _label(result.get("group_b"), "group B")
    compared = f"How far the two distributions are apart, {group_a} versus {group_b}."
    if not _is_ok(result):
        return _guidance(
            "nonparametric effect size",
            compared,
            unavailable=["result"],
            limitations=["No completed effect-size result is available to interpret."],
        )
    delta = _number(result.get("cliffs_delta"))
    band = result.get("hodges_lehmann")
    band = band if isinstance(band, Mapping) else {}
    shift = _number(band.get("estimate"))
    lower = _number(band.get("lower"))
    upper = _number(band.get("upper"))
    confidence = _number(result.get("confidence"))
    uncertainty = None
    if lower is not None and upper is not None:
        level = f"{float(confidence) * 100:.0f}%" if confidence else "the selected"
        uncertainty = f"{level} Hodges-Lehmann interval from {lower} to {upper}."
    return _guidance(
        "nonparametric effect size",
        compared,
        estimate=None if shift is None else f"Hodges-Lehmann location shift: {shift}.",
        uncertainty=uncertainty,
        evidence=None,
        effect=(
            None
            if delta is None
            else (
                f"Cliff's delta {delta} "
                f"({_label(result.get('cliffs_interpretation'), 'unlabelled')} band). "
                "A positive value favours the first group."
            )
        ),
        assumptions=[
            "Both estimates are rank-based and make no normality assumption.",
            "The two groups are treated as independent samples.",
        ],
        limitations=[
            "Magnitude bands are conventional labels, not thresholds of importance.",
            _CAVEAT_PRACTICAL,
            _CAVEAT_OBSERVATIONAL,
        ],
        do_not_conclude=[
            "An effect-size band is not a decision rule and carries no p-value.",
            _CAVEAT_PRACTICAL,
        ],
        next_steps=[
            "Read the shift estimate in the metric's own units before judging its size.",
            "Where the interval is unavailable, treat the point estimate as provisional.",
        ],
        unavailable=[] if uncertainty else ["hodges_lehmann_interval"],
    )


# ── distributions ─────────────────────────────────────────────────────────────


def guidance_for_distribution(result: Mapping[str, Any]) -> ResultGuidance:
    """Guidance for a theoretical distribution lookup."""
    distribution = _label(result.get("distribution"), "the selected distribution")
    calculation = _label(result.get("calculation"), "the selected calculation")
    compared = f"A {calculation} value read from the theoretical {distribution} distribution."
    if not _is_ok(result):
        return _guidance(
            "theoretical distribution",
            compared,
            unavailable=["result"],
            limitations=["No completed distribution value is available to interpret."],
        )
    value = _number(result.get("value"))
    parameters = result.get("parameters")
    parameter_text = _parameter_text(parameters)
    return _guidance(
        "theoretical distribution",
        compared,
        estimate=None if value is None else f"{calculation} value: {value}.",
        uncertainty=None,
        evidence=None,
        effect=parameter_text,
        assumptions=[
            "The curve is the theoretical distribution for the parameters you entered.",
            "A tail or interval shown here matches the calculation the result reports.",
        ],
        limitations=[
            "This is a lookup against an assumed distribution; it makes no claim that the "
            "active dataset follows that distribution.",
            "No goodness-of-fit test is performed here.",
        ],
        do_not_conclude=[
            "Reading a probability from this curve does not validate the distribution "
            "choice for your data.",
        ],
        next_steps=[
            "If you need to know whether your data match a distribution, run an explicit "
            "goodness-of-fit test instead.",
        ],
    )


def _parameter_text(parameters: Any) -> str | None:
    if not isinstance(parameters, Mapping) or not parameters:
        return None
    parts = []
    for name, value in list(parameters.items())[:GUIDANCE_MAX_ITEMS]:
        formatted = _number(value)
        parts.append(f"{name}={formatted if formatted is not None else value}")
    return "Parameters: " + ", ".join(parts) + "."


# ── power and sample size ─────────────────────────────────────────────────────


def guidance_for_power(
    result: Mapping[str, Any],
    *,
    analysis: str,
    alpha: Any = None,
    alternative: Any = None,
) -> ResultGuidance:
    """Guidance for a power or required-sample-size calculation."""
    compared = f"A planning calculation: {_label(analysis, 'power or sample size')}."
    if not _is_ok(result):
        return _guidance(
            "power and sample size",
            compared,
            unavailable=["result"],
            limitations=["No completed planning result is available to interpret."],
        )
    power = _number(result.get("power"))
    required = (
        _count(result.get("n")) or _count(result.get("n1")) or _count(result.get("n_per_group"))
    )
    estimate = None
    if power is not None:
        estimate = f"Power at the entered design: {float(power) * 100:.1f}%."
    elif required is not None:
        estimate = f"Required sample size at the entered target: {required}."
    alpha_text = _number(alpha)
    sided = _label(alternative, "two-sided")
    return _guidance(
        "power and sample size",
        compared,
        estimate=estimate,
        uncertainty=None,
        evidence=None,
        effect=(
            f"Planning assumptions: alpha {alpha_text or 'as selected'}, {sided} alternative, "
            "and the effect size you entered."
        ),
        assumptions=[
            "The effect size is an assumption you supply, not a measurement from the data.",
            "These are closed-form normal-approximation calculations.",
            "Power is computed for the alpha and alternative shown; changing either changes "
            "the curve.",
        ],
        limitations=[
            "A curve shows how power or required size moves with one parameter while every "
            "other input stays fixed.",
            "Planning numbers do not account for dropout, clustering, or measurement error.",
            "Points where the calculation is undefined are skipped rather than plotted as zero.",
        ],
        do_not_conclude=[
            "Reaching a target power does not make a future result meaningful; it only "
            "bounds the chance of detecting the assumed effect.",
            _CAVEAT_PRACTICAL,
        ],
        next_steps=[
            "Vary the assumed effect size to see how sensitive the plan is to that guess.",
            "Choose the sample size that fits the smallest difference worth detecting.",
        ],
    )


# ── assumption checks ─────────────────────────────────────────────────────────


def guidance_for_assumptions(result: Mapping[str, Any]) -> ResultGuidance:
    """Guidance framing the existing informational assumption checks."""
    compared = "Conditions the selected tests lean on, reported for interpretation only."
    if not _is_ok(result):
        return _guidance(
            "assumption checks",
            compared,
            unavailable=["result"],
            limitations=["No completed assumption checks are available to interpret."],
        )
    checks = [check for check in (result.get("checks") or []) if isinstance(check, Mapping)]
    names = [
        f"{_label(check.get('name'), 'check')}: {_label(check.get('status'), 'unknown')}"
        for check in checks[:GUIDANCE_MAX_ITEMS]
    ]
    return _guidance(
        "assumption checks",
        compared,
        estimate="; ".join(names) if names else None,
        uncertainty=None,
        evidence=None,
        effect=None,
        assumptions=[
            "These checks are informational: they never switch the selected test, change a "
            "p-value, or block a result.",
            "Sample-size thresholds shown here are rules of thumb, not mathematical " "guarantees.",
            "Normality and equal-variance checks are themselves tests, so large samples "
            "flag small departures.",
        ],
        limitations=[
            "A check that reports caution does not invalidate the result it sits beside.",
            "Excluded observations can affect both the checks and the test they inform.",
            _CAVEAT_MULTIPLE,
        ],
        do_not_conclude=[
            "Do not treat these checks as a compliance score or a gate; they carry no "
            "verdict of their own.",
            "Do not switch tests automatically because a check reports caution.",
        ],
        next_steps=[
            "Read each check next to the test it informs, along with your domain knowledge.",
            "Where a check reports caution, consider whether a rank-based comparison also "
            "answers your question.",
        ],
    )


# ── rendering support (framework-free) ────────────────────────────────────────

_SECTION_ORDER: tuple[tuple[str, str], ...] = (
    ("What was compared", "compared"),
    ("Estimate", "estimate"),
    ("Uncertainty", "uncertainty"),
    ("Hypothesis-test evidence", "evidence"),
    ("Effect", "effect"),
    ("Assumptions", "assumptions"),
    ("Limitations", "limitations"),
    ("What this does not show", "do_not_conclude"),
    ("Reasonable next steps", "next_steps"),
    ("Not available from this result", "unavailable"),
)


def guidance_sections(guidance: ResultGuidance) -> list[tuple[str, str]]:
    """Flatten guidance into ordered ``(heading, text)`` pairs for rendering.

    Empty sections are omitted; list sections are joined with a bounded separator
    so a caller renders one line per section without re-deriving the order.
    """
    sections: list[tuple[str, str]] = []
    for heading, attribute in _SECTION_ORDER:
        value = getattr(guidance, attribute, None)
        if value is None:
            continue
        if isinstance(value, tuple):
            if not value:
                continue
            joined = " ".join(f"({index + 1}) {item}" for index, item in enumerate(value))
            sections.append((heading, joined))
            continue
        text = str(value).strip()
        if text:
            sections.append((heading, text))
    return sections


__all__ = [
    "FORBIDDEN_GUIDANCE_PHRASES",
    "GUIDANCE_MAX_ITEMS",
    "LIMITATIONS_MAX_ITEMS",
    "ResultGuidance",
    "guidance_for_assumptions",
    "guidance_for_contingency",
    "guidance_for_distribution",
    "guidance_for_effect_sizes",
    "guidance_for_goodness_of_fit",
    "guidance_for_interval",
    "guidance_for_multi_group",
    "guidance_for_paired",
    "guidance_for_power",
    "guidance_for_proportion",
    "guidance_for_two_group",
    "guidance_sections",
]
