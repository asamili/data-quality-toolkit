# Power BI Date Table Configuration Guide

## 📅 Overview

A properly configured date table is essential for time intelligence in Power BI. The Data Quality Toolkit automatically generates a standards-compliant date dimension table (`dim_time`) with all necessary attributes for advanced time-based analytics.

## 🎯 Purpose

The date table enables:
- Time intelligence functions (YTD, MTD, YoY comparisons)
- Consistent date filtering across all facts
- Fiscal and calendar year analysis
- Week-based reporting (ISO 8601 compliant)
- Holiday and business day calculations

## 📊 Required Fields

The generated `dim_time.csv` includes these columns (always present unless noted):

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| **time_id** | Integer | Primary key (YYYYMMDD format) | 20250819 |
| **date** | String | ISO date value (`YYYY-MM-DD`) | 2025-08-19 |
| **year** | Integer | Calendar year | 2025 |
| **month** | Integer | Month number (1-12) | 8 |
| **day** | Integer | Day of month (1-31) | 19 |
| **quarter** | Integer | Calendar quarter (1-4) | 3 |
| **iso_year** | Integer | ISO 8601 week-numbering year | 2025 |
| **week_iso** | Integer | ISO week number (1-53) | 34 |
| **dow_iso** | Integer | ISO day of week (1=Monday … 7=Sunday) | 2 |
| **dow** | Integer | Day of week under the configured `--week-start` | 2 |
| **day_name** | String | Full day name | Tuesday |
| **month_name** | String | Full month name | August |
| **is_weekend** | Boolean | Weekend flag (Sat/Sun) | false |
| **week_start_date** | String | Start-of-week date for the configured week start | 2025-08-18 |
| **fiscal_year** | Integer | Fiscal year — only when `--fiscal` is set | 2026 |
| **fiscal_quarter** | Integer | Fiscal quarter (1-4) — only when `--fiscal` is set | 1 |

> The time dimension is calendar/fiscal only. There is **no** holiday column or holiday
> calendar: `is_holiday`, abbreviated names (`month_short` / `day_short`), and `fiscal_month`
> are not generated.

## 🔧 Generation Process

### Using the CLI

```bash
# Generate the time dimension into an output directory (writes dim_time.csv)
dqt gen-dim-time \
  --start 2020-01-01 \
  --end 2025-12-31 \
  --fiscal 10 \
  --week-start 1 \
  --out dist/time
```

### Parameters

- `--start`: Inclusive start date, `YYYY-MM-DD` (default: `2018-01-01`)
- `--end`: Inclusive end date, `YYYY-MM-DD` (default: `2030-12-31`)
- `--fiscal`: Fiscal year start month, `1`–`12` (default: calendar year, no fiscal offset)
- `--week-start`: Week start day, `1`=Monday … `7`=Sunday (default: `1`)
- `--out`: Output **directory** for `dim_time.csv` (default: `dist/time`)
- `--json`: Emit a JSON summary (path + arguments) on stdout

### Programmatic Generation

```python
from data_quality_toolkit import generate_dim_time

# Writes dim_time.csv into the output directory and returns a result with its path
result = generate_dim_time(
    "2020-01-01",
    "2025-12-31",
    week_start=1,
    fiscal_year_start=10,
    output_dir="dist/time",
)
print(result["path"])
```

## ⚙️ Power BI Configuration

### 1. Import the Date Table

The date table is automatically included in the Power BI package at:
```
dist/powerbi_package/time/dim_time.csv
```

### 2. Mark as Date Table

**Critical Step**: After import, mark the table as a date table:

1. Select the `dim_time` table in Model view
2. Open Table tools → Mark as date table
3. Choose `date` column as the date column
4. Verify validation passes

### 3. Create Relationships

The toolkit automatically creates relationships:
- Link `time_id` from facts to `time_id` in dim_time
- Relationship type: Many-to-One
- Cross-filter direction: Single

### 4. Sort Columns

Configure sort orders for proper display. DQT does not emit these — author them in Power BI
against the generated `dim_time` columns:

```dax
// Author in Power BI (DQT does not generate these)
Month Name = SORT BY dim_time[month]
Day Name = SORT BY dim_time[dow]
Quarter = "Q" & dim_time[quarter]
```

## 📈 Time Intelligence Measures

DQT does **not** emit DAX measures. The `dim_time` table it generates is what enables the
standard Power BI time-intelligence measures below once you author them in your model:

### Year-to-Date (YTD)
```dax
Revenue YTD =
CALCULATE(
    [Revenue Total],
    DATESYTD(dim_time[date])
)
```

### Month-to-Date (MTD)
```dax
Revenue MTD =
CALCULATE(
    [Revenue Total],
    DATESMTD(dim_time[date])
)
```

### Year-over-Year (YoY)
```dax
Revenue YoY % =
VAR CurrentYear = [Revenue Total]
VAR PreviousYear =
    CALCULATE(
        [Revenue Total],
        SAMEPERIODLASTYEAR(dim_time[date])
    )
RETURN
    DIVIDE(
        CurrentYear - PreviousYear,
        PreviousYear
    )
```

### Period Comparisons
```dax
Revenue vs Last Month =
VAR CurrentMonth = [Revenue Total]
VAR LastMonth =
    CALCULATE(
        [Revenue Total],
        DATEADD(dim_time[date], -1, MONTH)
    )
RETURN
    CurrentMonth - LastMonth
```

## 🚨 Common Issues and Solutions

### Issue: Time Intelligence Functions Not Working

**Symptom**: YTD, MTD calculations return blank or incorrect values

**Solution**:
1. Verify table is marked as date table
2. Check date column has no gaps
3. Ensure contiguous date range
4. Confirm relationships are active

### Issue: Incorrect Week Numbers

**Symptom**: Week numbers don't align with expectations

**Solution**:
- Verify ISO 8601 setting (week starts Monday)
- Check fiscal year configuration
- Use `week_iso` for standard weeks

### Issue: Missing Dates in Visual

**Symptom**: Date axis has gaps

**Solution**:
1. Check "Show items with no data" in visual
2. Verify date table completeness
3. Ensure proper relationship configuration

### Issue: Fiscal Year Misalignment

**Symptom**: Fiscal calculations incorrect

**Solution**:
- Regenerate with correct `--fiscal`
- Update fiscal year measures
- Verify fiscal_year column values

## 🎨 Best Practices

### 1. Date Range
- Include at least 3 years historical
- Include 1-2 years future
- Cover all fact table dates

### 2. Performance
- Keep date table under 10,000 rows
- Index on time_id and date
- Avoid calculated columns

### 3. Consistency
- Use single date table for all facts
- Standard column naming
- Consistent fiscal configuration

### 4. Maintenance
- Regenerate annually
- Update holiday calendars
- Document fiscal year changes

## 📊 Advanced Features

### Calendar and Fiscal Support

The generated dimension covers a standard Gregorian calendar plus an **optional** fiscal
overlay (`--fiscal <month>`), which adds `fiscal_year` and `fiscal_quarter`. ISO 8601 week
fields (`iso_year`, `week_iso`, `dow_iso`) are always included, and `--week-start` controls
the `dow` / `week_start_date` anchoring.

> Not currently generated: holiday calendars, 4-4-5 retail calendars, custom business
> calendars, and special-period markers (peak / blackout / promotional). Add these as Power BI
> calculated columns if you need them.

## 🔍 Validation Checklist

Before using the date table:

- [ ] Date range covers all fact dates
- [ ] No missing dates in range
- [ ] Marked as date table in Power BI
- [ ] Relationships created and active
- [ ] Sort orders configured
- [ ] Time intelligence measures work
- [ ] Fiscal year alignment correct

## 📚 Related Documentation

- [BI Worked Example](../guides/bi_worked_example.md)
- [Incremental Refresh Setup](incremental_refresh.md)
- [RLS Testing Guide](rls_testing.md)

## 🆘 Troubleshooting

For additional help:
1. Review the [Quickstart notebook](../../examples/01_quickstart.ipynb)
2. See the [CLI Reference](../cli.md) and [Python API](../api.md)
3. Open a GitHub issue

---

**Last Updated**: June 2026
**Toolkit Version**: 2.10.0
