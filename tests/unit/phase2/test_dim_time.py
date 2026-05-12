"""Phase 2: Time dimension tests (ISO-correct, lint-clean)."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

from data_quality_toolkit.exporters.time.dim_time_generator import generate_dim_time, write_dim_time


def test_dim_time_basic():
    """Basic generation and key columns."""
    df = generate_dim_time(start_date="2024-01-01", end_date="2024-01-07")

    assert len(df) == 7
    assert list(df.columns[:5]) == ["time_id", "date", "year", "month", "day"]

    # time_id format
    assert df["time_id"].iloc[0] == 20240101
    assert df["time_id"].iloc[-1] == 20240107

    # Weekend flags (Mon..Sun for 2024-01-01..07)
    assert not df["is_weekend"].iloc[0]  # Monday
    assert df["is_weekend"].iloc[5]  # Saturday
    assert df["is_weekend"].iloc[6]  # Sunday

    # ISO DOW range
    assert df["dow_iso"].between(1, 7).all()


def test_dim_time_iso_week_edges():
    """
    Verify ISO year/week rollover behavior around year boundaries.
    Window: 2020-12-28 .. 2021-01-03 is ISO week 53 of ISO year 2020.
    """
    df = generate_dim_time(start_date="2020-12-28", end_date="2021-01-03")

    # 2020-12-28 (Mon) should be ISO week 53 of ISO year 2020
    r1 = df.loc[df["date"] == "2020-12-28"].iloc[0]
    assert r1["dow_iso"] == 1
    assert r1["week_iso"] == 53
    assert r1["iso_year"] == 2020

    # 2021-01-03 (Sun) is still ISO year 2020, week 53
    r2 = df.loc[df["date"] == "2021-01-03"].iloc[0]
    assert r2["dow_iso"] == 7
    assert r2["week_iso"] == 53
    assert r2["iso_year"] == 2020


def test_week_start_changes_week_anchor():
    """Custom week start must affect `dow` and `week_start_date`, not ISO fields."""
    d_mon = generate_dim_time("2024-01-03", "2024-01-03", week_start=1)  # Wed
    d_sun = generate_dim_time("2024-01-03", "2024-01-03", week_start=7)  # Wed

    # Custom DOW differs
    assert d_mon.iloc[0]["dow"] != d_sun.iloc[0]["dow"]
    # Week anchor date differs
    assert d_mon.iloc[0]["week_start_date"] != d_sun.iloc[0]["week_start_date"]

    # ISO fields remain ISO-8601 regardless of custom week_start
    assert d_mon.iloc[0]["dow_iso"] == d_sun.iloc[0]["dow_iso"]
    assert d_mon.iloc[0]["week_iso"] == d_sun.iloc[0]["week_iso"]
    assert d_mon.iloc[0]["iso_year"] == d_sun.iloc[0]["iso_year"]


def test_dim_time_fiscal_year_and_quarter_simple():
    """Fiscal year rollover at July (7)."""
    df = generate_dim_time(
        start_date="2024-06-01",
        end_date="2024-08-01",
        fiscal_year_start=7,  # July
    )

    # June → FY2023? or FY2024?  (By spec: month < fiscal start → prior year)
    june = df[df["month"] == 6]
    july = df[df["month"] == 7]

    assert (june["fiscal_year"] == 2023).all()
    assert (july["fiscal_year"] == 2024).all()

    # Quarter mapping relative to July start
    # July, Aug, Sep → Q1
    assert (df[df["month"] == 7]["fiscal_quarter"] == 1).all()
    assert (df[df["month"] == 8]["fiscal_quarter"] == 1).all()


def test_dim_time_fiscal_year_and_quarter_edge():
    """Check the exact rollover day."""
    df = generate_dim_time("2024-06-30", "2024-07-01", fiscal_year_start=7)

    june = df[df["date"] == "2024-06-30"].iloc[0]
    july = df[df["date"] == "2024-07-01"].iloc[0]

    assert june["fiscal_year"] == 2023 and june["fiscal_quarter"] == 4
    assert july["fiscal_year"] == 2024 and july["fiscal_quarter"] == 1


@pytest.mark.parametrize(
    "start_date,end_date,week_start,fiscal_start,err",
    [
        ("2024-01-10", "2024-01-01", 1, None, ValueError),  # start > end
        ("2024-01-01", "2024-01-10", 0, None, ValueError),  # week_start out of range
        ("2024-01-01", "2024-01-10", 8, None, ValueError),  # week_start out of range
        ("2024-01-01", "2024-01-10", 1, 0, ValueError),  # fiscal start out of range
        ("2024-01-01", "2024-01-10", 1, 13, ValueError),  # fiscal start out of range
        ("bad", "2024-01-10", 1, None, ValueError),  # bad start
        ("2024-01-01", "bad", 1, None, ValueError),  # bad end
    ],
)
def test_param_validation_errors(start_date, end_date, week_start, fiscal_start, err):
    with pytest.raises(err):
        _ = generate_dim_time(
            start_date=start_date,
            end_date=end_date,
            week_start=week_start,
            fiscal_year_start=fiscal_start,
        )


def test_column_order_and_dtypes_no_fiscal():
    """Enforce stable column order and key dtypes when fiscal is absent."""
    df = generate_dim_time("2024-01-01", "2024-01-02")

    expected_prefix = [
        "time_id",
        "date",
        "year",
        "month",
        "day",
        "quarter",
        "iso_year",
        "week_iso",
        "dow_iso",
        "dow",
        "day_name",
        "month_name",
        "is_weekend",
        "week_start_date",
    ]
    assert list(df.columns) == expected_prefix

    # Dtypes (subset check; strings are 'object')
    assert df["time_id"].dtype == "int64"
    assert df["year"].dtype == "int16"
    assert df["month"].dtype == "int8"
    assert df["day"].dtype == "int8"
    assert df["quarter"].dtype == "int8"
    assert df["iso_year"].dtype == "int16"
    assert df["week_iso"].dtype == "int8"
    assert df["dow_iso"].dtype == "int8"
    assert df["dow"].dtype == "int8"
    assert df["is_weekend"].dtype == "bool"


def test_column_order_and_dtypes_with_fiscal():
    """When fiscal is requested, extra columns appear with expected dtypes."""
    df = generate_dim_time("2024-01-01", "2024-01-02", fiscal_year_start=4)

    expected = [
        "time_id",
        "date",
        "year",
        "month",
        "day",
        "quarter",
        "iso_year",
        "week_iso",
        "dow_iso",
        "dow",
        "day_name",
        "month_name",
        "is_weekend",
        "week_start_date",
        "fiscal_year",
        "fiscal_quarter",
    ]
    assert list(df.columns) == expected
    assert df["fiscal_year"].dtype == "int16"
    assert df["fiscal_quarter"].dtype == "int8"


def test_write_dim_time_creates_csv(tmp_path: Path):
    out_dir = tmp_path / "pbi_star"
    path = write_dim_time(
        output_dir=out_dir,
        start_date="2024-01-01",
        end_date="2024-01-03",
        week_start=1,
        fiscal_year_start=7,
    )
    assert os.path.exists(path)

    df = pd.read_csv(path)
    # quick header spot-check
    assert "time_id" in df.columns
    assert "week_start_date" in df.columns
    assert "fiscal_year" in df.columns
    assert len(df) == 3
