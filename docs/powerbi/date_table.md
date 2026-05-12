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

The generated `dim_time.csv` includes these essential columns:

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| **time_id** | Integer | Primary key (YYYYMMDD format) | 20250819 |
| **date** | Date | Actual date value | 2025-08-19 |
| **year** | Integer | Calendar year | 2025 |
| **quarter** | Integer | Calendar quarter (1-4) | 3 |
| **month** | Integer | Month number (1-12) | 8 |
| **month_name** | String | Full month name | August |
| **month_short** | String | Abbreviated month | Aug |
| **week_iso** | Integer | ISO week number (1-53) | 34 |
| **day** | Integer | Day of month (1-31) | 19 |
| **day_of_week** | Integer | Day of week (1=Monday, 7=Sunday) | 2 |
| **day_name** | String | Full day name | Tuesday |
| **day_short** | String | Abbreviated day | Tue |
| **is_weekend** | Boolean | Weekend flag | false |
| **is_holiday** | Boolean | Holiday flag (configurable) | false |
| **fiscal_year** | Integer | Fiscal year (configurable) | 2026 |
| **fiscal_quarter** | Integer | Fiscal quarter (1-4) | 1 |
| **fiscal_month** | Integer | Fiscal month (1-12) | 2 |

## 🔧 Generation Process

### Using the CLI

```bash
# Generate date table for specific range
python scripts/generate_dim_time.py \
  --start 2020-01-01 \
  --end 2025-12-31 \
  --fiscal-start 10 \
  --holidays US \
  --output dist/star/dim_time.csv
```

### Parameters

- `--start`: Start date (default: 3 years ago)
- `--end`: End date (default: 2 years future)
- `--fiscal-start`: Fiscal year start month (default: 1)
- `--holidays`: Holiday calendar (US, UK, EU, custom)
- `--week-start`: Week start day (1=Monday, 7=Sunday)
- `--output`: Output file path

### Programmatic Generation

```python
from data_quality_toolkit.exporters.bi import generate_date_table

dim_time = generate_date_table(
    start_date="2020-01-01",
    end_date="2025-12-31",
    fiscal_year_start_month=10,
    holidays="US",
    week_starts_monday=True
)

dim_time.to_csv("dist/star/dim_time.csv", index=False)
```

## ⚙️ Power BI Configuration

### 1. Import the Date Table

The date table is automatically included in the Power BI package at:
```
dist/powerbi_package/star/dim_time.csv
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

Configure sort orders for proper display:

```dax
// DAX expressions automatically generated
Month Name = SORT BY dim_time[month]
Day Name = SORT BY dim_time[day_of_week]
Quarter = "Q" & dim_time[quarter]
```

## 📈 Time Intelligence Measures

The toolkit generates standard time intelligence DAX measures:

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
- Regenerate with correct `--fiscal-start`
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

### Custom Holidays

Create custom holiday configuration:

```yaml
# config/holidays.yaml
holidays:
  - name: "Company Holiday"
    date: "2025-07-01"
  - name: "Fiscal Year End"
    date: "2025-09-30"
    is_business_day: false
```

### Multiple Calendars

Support for multiple calendar types:
- Standard (Gregorian)
- Fiscal (configurable)
- 4-4-5 Retail
- ISO Week
- Custom business calendars

### Special Periods

Additional period markers:
- Peak seasons
- Blackout dates
- Promotional periods
- Quarter/Year end flags

## 🔍 Validation Checklist

Before using the date table:

- [ ] Date range covers all fact dates
- [ ] No missing dates in range
- [ ] Marked as date table in Power BI
- [ ] Relationships created and active
- [ ] Sort orders configured
- [ ] Time intelligence measures work
- [ ] Fiscal year alignment correct
- [ ] Holiday flags accurate

## 📚 Related Documentation

- [Incremental Refresh Setup](incremental_refresh.md)
- [Time Intelligence DAX Patterns](../dax/time_intelligence.md)
- [Fiscal Calendar Configuration](../config/fiscal_calendar.md)
- [Power BI Best Practices](../powerbi_best_practices.md)

## 🆘 Troubleshooting

For additional help:
1. Check the [FAQ](../faq.md#date-table)
2. Review [example notebooks](../../examples/03_date_table_setup.ipynb)
3. Open a GitHub issue

---

**Last Updated**: August 2025
**Toolkit Version**: 0.0.0
