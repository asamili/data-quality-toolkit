"""``dqt stats`` - descriptive statistics and first-wave hypothesis tests."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

import data_quality_toolkit.adapters.cli.main as _m
from data_quality_toolkit.adapters.cli.utils.parser import (
    CROSS_FALLBACK,
    CSV_PATH_HELP,
    parse_bool_flag,
)

_ALTERNATIVES = ("two-sided", "greater", "less")
_ONE_SAMPLE_KEYS = frozenset({"ONE_T", "ONE_Z"})
_TWO_SAMPLE_KEYS = frozenset({"TWO_T_WELCH", "TWO_T_EQ", "TWO_Z", "PAIRED_T"})


def _split_csv_values(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def _stats_csv_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    kw: dict[str, Any] = {}
    if getattr(args, "sep", None) is not None:
        kw["sep"] = args.sep
    if getattr(args, "encoding", None) is not None:
        kw["encoding"] = args.encoding
    if getattr(args, "na_values", None):
        kw["na_values"] = _split_csv_values(args.na_values)
    return kw


def _status_exit_code(result: dict[str, Any]) -> int:
    return 0 if result.get("status") == "ok" else 1


def _print_json_if_enabled(args: argparse.Namespace, result: dict[str, Any]) -> None:
    if not getattr(args, "no_json", False):
        print(_m._json_dump(result))


def _print_status_summary(label: str, result: dict[str, Any]) -> None:
    status = result.get("status")
    marker = "[OK]" if status == "ok" else _m._safe_text("x", CROSS_FALLBACK)
    print(f"{marker} {label}: {status}", file=sys.stderr)
    if reason := result.get("reason"):
        print(f"  - Reason: {reason}", file=sys.stderr)


def _print_result_notes(result: dict[str, Any]) -> None:
    """Echo the backend result's own warnings and messages to stderr.

    Presentation only: the CLI never decides which diagnostics exist. Whatever the
    authoritative statistical result carries — expected-count reliability warnings,
    continuity-correction disclosure — is printed verbatim, and the JSON payload
    already carries the same fields structurally.
    """
    for warning in result.get("warnings") or []:
        print(f"  - Warning: {warning}", file=sys.stderr)
    for message in result.get("messages") or []:
        print(f"  - Note: {message}", file=sys.stderr)


def cmd_stats_profile(args: argparse.Namespace) -> int:
    """Profile a CSV with the public statistics facade."""
    columns = _split_csv_values(getattr(args, "columns", None))
    result = _m.stats_profile_csv(args.csv, columns=columns, **_stats_csv_kwargs(args))

    if result.get("status") != "ok":
        _print_status_summary("Statistics profile", result)
        _print_json_if_enabled(args, result)
        return 1

    profile = result.get("profile") or {}
    numeric_summary = result.get("numeric_summary") or []
    print("[OK] Statistics profile complete", file=sys.stderr)
    print(f"  - Rows: {profile.get('n_rows', 0)}", file=sys.stderr)
    print(f"  - Columns: {profile.get('n_columns', 0)}", file=sys.stderr)
    print(f"  - Numeric columns: {len(numeric_summary)}", file=sys.stderr)
    _print_json_if_enabled(args, result)
    return 0


def cmd_stats_select_test(args: argparse.Namespace) -> int:
    """Select a statistical test from typed setup inputs."""
    result = _m.select_statistical_test(
        args.variable_type,
        args.group_structure,
        sigma_known=args.sigma_known,
        equal_variance_assumed=args.equal_variance_assumed,
        paired=args.paired,
        alternative=args.alternative,
        alpha=args.alpha,
    )

    _print_status_summary("Statistical test selection", result)
    if test_key := result.get("test_key"):
        print(f"  - Test: {test_key}", file=sys.stderr)
    if explanation := result.get("explanation"):
        print(f"  - {explanation}", file=sys.stderr)
    _print_json_if_enabled(args, result)
    return _status_exit_code(result)


def _read_csv_rows(
    csv_path: str,
    *,
    sep: str | None = None,
    encoding: str | None = None,
) -> tuple[list[str], list[dict[str, str | None]]]:
    with Path(csv_path).open("r", encoding=encoding or "utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=sep or ",")
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    if not fieldnames:
        raise ValueError("CSV must include a header row")
    return fieldnames, rows


def _is_missing(value: str | None, na_values: set[str]) -> bool:
    if value is None:
        return True
    stripped = value.strip()
    return not stripped or stripped in na_values


def _numeric_value(raw: str | None, column: str, na_values: set[str]) -> float | None:
    if _is_missing(raw, na_values):
        return None
    assert raw is not None
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"column {column!r} contains a non-numeric value: {raw!r}") from exc


def _numeric_sample(
    csv_path: str,
    value_column: str,
    *,
    sep: str | None = None,
    encoding: str | None = None,
    na_values: list[str] | None = None,
) -> list[float]:
    fieldnames, rows = _read_csv_rows(csv_path, sep=sep, encoding=encoding)
    if value_column not in fieldnames:
        raise ValueError(f"value column {value_column!r} not found")
    na_set = set(na_values or [])
    sample = [
        value
        for row in rows
        if (value := _numeric_value(row.get(value_column), value_column, na_set)) is not None
    ]
    if not sample:
        raise ValueError(f"value column {value_column!r} has no finite numeric values")
    return sample


def _numeric_samples_by_group(
    csv_path: str,
    value_column: str,
    group_column: str,
    group_a: str,
    group_b: str,
    *,
    sep: str | None = None,
    encoding: str | None = None,
    na_values: list[str] | None = None,
) -> tuple[list[float], list[float]]:
    fieldnames, rows = _read_csv_rows(csv_path, sep=sep, encoding=encoding)
    missing = [column for column in (value_column, group_column) if column not in fieldnames]
    if missing:
        raise ValueError(f"CSV is missing required column(s): {', '.join(missing)}")

    na_set = set(na_values or [])
    sample_a: list[float] = []
    sample_b: list[float] = []
    for row in rows:
        group = row.get(group_column)
        if group not in {group_a, group_b}:
            continue
        value = _numeric_value(row.get(value_column), value_column, na_set)
        if value is None:
            continue
        if group == group_a:
            sample_a.append(value)
        else:
            sample_b.append(value)

    if not sample_a or not sample_b:
        raise ValueError("both groups must contain at least one numeric value")
    return sample_a, sample_b


def _numeric_test_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    key = args.test_key.upper()
    common = _stats_csv_kwargs(args)
    if key in _ONE_SAMPLE_KEYS:
        return {
            "sample": _numeric_sample(args.csv, args.value_column, **common),
            "null_mean": args.null_mean,
            "sigma": args.sigma,
        }
    if key in _TWO_SAMPLE_KEYS:
        if not (args.group_column and args.group_a and args.group_b):
            raise ValueError(
                "--group-column, --group-a, and --group-b are required for two-sample tests"
            )
        sample_a, sample_b = _numeric_samples_by_group(
            args.csv,
            args.value_column,
            args.group_column,
            args.group_a,
            args.group_b,
            **common,
        )
        return {
            "sample_a": sample_a,
            "sample_b": sample_b,
            "null_difference": args.null_difference,
            "sigma": args.sigma,
            "sigma_a": args.sigma_a,
            "sigma_b": args.sigma_b,
        }
    raise ValueError(
        "dqt stats test currently supports ONE_T, ONE_Z, TWO_T_WELCH, TWO_T_EQ, TWO_Z, "
        "and PAIRED_T"
    )


def cmd_stats_test(args: argparse.Namespace) -> int:
    """Run a narrow CSV-backed numeric statistical test."""
    test_key = args.test_key.upper()
    result = _m.run_statistical_test(
        test_key,
        **_numeric_test_kwargs(args),
        alternative=args.alternative,
        alpha=args.alpha,
    )

    _print_status_summary("Statistical test", result)
    if result.get("statistic") is not None:
        print(f"  - Statistic: {result['statistic']}", file=sys.stderr)
    if result.get("p_value") is not None:
        print(f"  - p-value: {result['p_value']}", file=sys.stderr)
    _print_result_notes(result)
    _print_json_if_enabled(args, result)
    return _status_exit_code(result)


def cmd_stats_ab(args: argparse.Namespace) -> int:
    """Run a numeric A/B comparison from a local CSV."""
    sample_a, sample_b = _numeric_samples_by_group(
        args.csv,
        args.metric_column,
        args.group_column,
        args.group_a,
        args.group_b,
        **_stats_csv_kwargs(args),
    )
    result = _m.compare_ab(
        sample_a,
        sample_b,
        variable_type="numeric",
        group_structure="two_independent",
        alpha=args.alpha,
        alternative=args.alternative,
        equal_variance_assumed=args.equal_variance_assumed,
    )

    _print_status_summary("A/B comparison", result)
    if test_key := result.get("test_key"):
        print(f"  - Test: {test_key}", file=sys.stderr)
    if result.get("p_value") is not None:
        print(f"  - p-value: {result['p_value']}", file=sys.stderr)
    _print_json_if_enabled(args, result)
    return _status_exit_code(result)


def _add_stats_csv_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sep", help="CSV delimiter (default: ',')")
    parser.add_argument("--encoding", help="CSV encoding (default: utf-8)")
    parser.add_argument("--na-values", help="Comma-separated NA values to skip")


def _add_test_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--alpha", type=float, default=0.05, help="Significance level")
    parser.add_argument("--alternative", choices=_ALTERNATIVES, default="two-sided")


def register(sub: argparse._SubParsersAction) -> None:
    sp_stats = sub.add_parser("stats", help="Run descriptive statistics and A/B tests")
    stats_sub = sp_stats.add_subparsers(dest="stats_command", required=True)

    sp_profile = stats_sub.add_parser("profile", help="Profile a CSV with descriptive stats")
    sp_profile.add_argument("csv", help=CSV_PATH_HELP)
    sp_profile.add_argument("--columns", help="Comma-separated subset of columns to profile")
    _add_stats_csv_options(sp_profile)
    sp_profile.set_defaults(func=cmd_stats_profile)

    sp_select = stats_sub.add_parser("select-test", help="Select a hypothesis test")
    sp_select.add_argument("--variable-type", required=True)
    sp_select.add_argument("--group-structure", required=True)
    sp_select.add_argument("--sigma-known", type=parse_bool_flag, default=None)
    sp_select.add_argument("--equal-variance-assumed", type=parse_bool_flag, default=None)
    sp_select.add_argument("--paired", type=parse_bool_flag, default=None)
    _add_test_common_options(sp_select)
    sp_select.set_defaults(func=cmd_stats_select_test)

    sp_test = stats_sub.add_parser("test", help="Run a CSV-backed numeric test")
    sp_test.add_argument("csv", help=CSV_PATH_HELP)
    sp_test.add_argument("--test-key", required=True)
    sp_test.add_argument("--value-column", required=True)
    sp_test.add_argument("--group-column")
    sp_test.add_argument("--group-a")
    sp_test.add_argument("--group-b")
    sp_test.add_argument("--null-mean", type=float, default=0.0)
    sp_test.add_argument("--null-difference", type=float, default=0.0)
    sp_test.add_argument("--sigma", type=float, default=None)
    sp_test.add_argument("--sigma-a", type=float, default=None)
    sp_test.add_argument("--sigma-b", type=float, default=None)
    _add_test_common_options(sp_test)
    _add_stats_csv_options(sp_test)
    sp_test.set_defaults(func=cmd_stats_test)

    sp_ab = stats_sub.add_parser("ab", help="Run a numeric A/B comparison from a CSV")
    sp_ab.add_argument("csv", help=CSV_PATH_HELP)
    sp_ab.add_argument("--group-column", required=True)
    sp_ab.add_argument("--metric-column", required=True)
    sp_ab.add_argument("--group-a", required=True)
    sp_ab.add_argument("--group-b", required=True)
    sp_ab.add_argument("--equal-variance-assumed", type=parse_bool_flag, default=False)
    _add_test_common_options(sp_ab)
    _add_stats_csv_options(sp_ab)
    sp_ab.set_defaults(func=cmd_stats_ab)
