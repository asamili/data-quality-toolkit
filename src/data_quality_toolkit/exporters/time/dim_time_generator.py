"""
Phase 2: Time dimension generator (ISO-correct, lint-clean).

Generates a canonical time dimension with:
- time_id (YYYYMMDD), date, year, month, day, quarter
- ISO week/year/day-of-week (ISO 8601)
- Custom week start support (week_start: 1=Mon .. 7=Sun)
- week_start_date (based on the chosen week_start)
- Weekend flag (Sat/Sun)
- Optional fiscal_year and fiscal_quarter

Notes:
- ISO week/year follow pandas .isocalendar() (ISO-8601).
- Custom week start does NOT change ISO values; it only affects:
  - dow (1..7, where 1 == week_start)
  - week_start_date (aligned to chosen week_start)
"""

from __future__ import annotations

from collections.abc import Iterable  # Ruff UP035: import from collections.abc
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from data_quality_toolkit.utils.helpers import ensure_dir
from data_quality_toolkit.utils.logging import get_logger

__all__ = ["generate_dim_time", "write_dim_time"]

LOGGER_NAME: Final[str] = "dqt.exporters.time.dim_time"
logger = get_logger(LOGGER_NAME)


def _validate_params(
    start_date: str, end_date: str, week_start: int, fiscal_year_start: int | None
) -> None:
    if week_start < 1 or week_start > 7:
        raise ValueError("week_start must be in 1..7 (1=Monday, 7=Sunday)")
    if fiscal_year_start is not None and (fiscal_year_start < 1 or fiscal_year_start > 12):
        raise ValueError("fiscal_year_start must be in 1..12 when provided")
    try:
        pd.Timestamp(start_date)
        pd.Timestamp(end_date)
    except Exception as e:  # noqa: BLE001 (explicitly surfacing validation details)
        raise ValueError(f"Invalid date: {e}") from e
    if pd.Timestamp(start_date) > pd.Timestamp(end_date):
        raise ValueError("start_date must be <= end_date")


def _custom_dow(dayofweek0: Iterable[int], week_start: int) -> NDArray[np.int64]:
    """
    Convert pandas dayofweek (Mon=0..Sun=6) to custom 1..7 where 1 == week_start.

    Example:
      - ISO: Mon=0;
      - week_start=1 (Mon): (0 - 0) % 7 + 1 => 1 (Mon)
      - week_start=7 (Sun): (0 - 6) % 7 + 1 => 2 (Mon), so Sun=1, Mon=2, ...
    """
    ws0 = week_start - 1  # convert to 0..6 base
    arr = np.asarray(list(dayofweek0), dtype=np.int64)
    out = ((arr - ws0) % 7) + 1
    return out.astype(np.int64)


def _week_start_date(dates: pd.DatetimeIndex, week_start: int) -> pd.Series:
    """
    Compute the date of the start of the week for each date using chosen week_start.
    week_start: 1..7 (Mon..Sun)

    Returns a pandas Series[str] (not Index) to satisfy type checkers.
    """
    ws0 = week_start - 1  # 0..6 (Mon=0 ... Sun=6)
    # pandas dayofweek: Mon=0..Sun=6
    dow0 = dates.dayofweek
    # distance back to week start (in days)
    delta = (dow0 - ws0) % 7
    start_dates = dates - pd.to_timedelta(delta, unit="D")
    # Return a Series (not Index) to satisfy Pylance's reportReturnType
    return pd.Series(start_dates.strftime("%Y-%m-%d"), index=dates, name="week_start_date")


def generate_dim_time(
    start_date: str = "2018-01-01",
    end_date: str = "2030-12-31",
    week_start: int = 1,  # 1=Monday .. 7=Sunday
    fiscal_year_start: int | None = None,  # 1..12 (month)
) -> pd.DataFrame:
    """
    Generate a time dimension dataframe.

    Args:
        start_date: Inclusive start (YYYY-MM-DD).
        end_date: Inclusive end (YYYY-MM-DD).
        week_start: 1..7 mapping 1=Monday..7=Sunday for custom week anchoring.
        fiscal_year_start: Optional fiscal year start month (1..12).

    Returns:
        pandas.DataFrame with canonical date features.
    """
    _validate_params(start_date, end_date, week_start, fiscal_year_start)
    logger.info(
        "Generating dim_time from %s to %s (week_start=%s, fiscal=%s)",
        start_date,
        end_date,
        week_start,
        fiscal_year_start,
    )

    dates = pd.date_range(start=start_date, end=end_date, freq="D")
    iso = dates.isocalendar()  # DataFrame with .year, .week, .day (ISO 8601)

    # Core calendar fields
    df = pd.DataFrame(
        {
            "time_id": dates.strftime("%Y%m%d").astype("int64"),
            "date": dates.strftime("%Y-%m-%d"),
            "year": dates.year.astype("int16"),
            "month": dates.month.astype("int8"),
            "day": dates.day.astype("int8"),
            "quarter": dates.quarter.astype("int8"),
            # ISO
            "iso_year": iso.year.astype("int16"),
            "week_iso": iso.week.astype("int8"),
            "dow_iso": iso.day.astype("int8"),  # 1=Mon..7=Sun (ISO)
            # Friendly names
            "day_name": dates.day_name(),
            "month_name": dates.month_name(),
            # Weekend flag (Sat/Sun)
            "is_weekend": (dates.dayofweek >= 5),
        }
    )

    # Custom week start derived fields
    df["dow"] = _custom_dow(dates.dayofweek, week_start).astype("int8")
    df["week_start_date"] = _week_start_date(dates, week_start)

    # Fiscal year/quarter (optional)
    if fiscal_year_start is not None:
        # fiscal year: rolls over when month < fiscal start
        month = dates.month
        fiscal_year = np.where(month >= fiscal_year_start, dates.year, dates.year - 1)
        # fiscal quarter: 1..4 relative to fiscal_year_start
        fiscal_quarter = ((month - fiscal_year_start) % 12) // 3 + 1

        df["fiscal_year"] = pd.Series(fiscal_year, index=df.index, dtype="int16")
        df["fiscal_quarter"] = pd.Series(fiscal_quarter, index=df.index, dtype="int8")

    # Column order (stable)
    ordered = [
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
    if fiscal_year_start is not None:
        ordered += ["fiscal_year", "fiscal_quarter"]

    df = df[ordered]

    logger.info("Generated %d rows for dim_time", len(df))
    return df


def write_dim_time(
    output_dir: str | Path,
    start_date: str = "2018-01-01",
    end_date: str = "2030-12-31",
    week_start: int = 1,
    fiscal_year_start: int | None = None,
) -> str:
    """
    Generate and write the time dimension to CSV.

    Args:
        output_dir: Directory to place dim_time.csv
        start_date, end_date, week_start, fiscal_year_start: See generate_dim_time()

    Returns:
        str path to generated CSV file
    """
    out_dir = ensure_dir(Path(output_dir))
    out_path = out_dir / "dim_time.csv"

    df = generate_dim_time(
        start_date=start_date,
        end_date=end_date,
        week_start=week_start,
        fiscal_year_start=fiscal_year_start,
    )
    # Always write UTF-8 without index
    df.to_csv(out_path, index=False)
    logger.info("Wrote dim_time to %s", out_path)
    return str(out_path)
