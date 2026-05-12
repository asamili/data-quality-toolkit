# Power BI Incremental Refresh Configuration

## 🔄 Overview

Incremental refresh enables Power BI to efficiently update large datasets by refreshing only new or changed data. The Data Quality Toolkit automatically configures incremental refresh policies for optimal performance and reduced refresh times.

## 🎯 Benefits

- **Faster Refreshes**: Only process new/changed data
- **Reduced Load**: Lower impact on source systems
- **Historical Data**: Maintain years of history efficiently
- **Resource Optimization**: Smaller refresh windows
- **Cost Savings**: Reduced compute and transfer costs

## 📋 Prerequisites

### Requirements
- Power BI Pro or Premium license
- Date column in fact tables
- RangeStart and RangeEnd parameters
- Configured refresh policy

### Supported Scenarios
- Time-based fact tables
- Event logs and transactions
- Sensor/telemetry data
- Audit trails
- Any date-partitioned data

## 🔧 Configuration

### 1. Parameters Setup

The toolkit automatically creates these Power Query parameters:

```powerquery
// Generated in parameters.json
RangeStart = #datetime(2024, 1, 1, 0, 0, 0)  // Type: DateTime
RangeEnd = #datetime(2025, 12, 31, 23, 59, 59)  // Type: DateTime
```

**Location**: `dist/powerbi_package/parameters.json`

### 2. Filter Configuration

Each fact table query includes date filtering:

```powerquery
// Automatically applied to fact tables
let
    Source = Csv.Document(...),
    Filtered = Table.SelectRows(Source, each
        [transaction_date] >= RangeStart and
        [transaction_date] < RangeEnd
    )
in
    Filtered
```

### 3. Policy Definition

Configure refresh policy in `config/incremental_refresh.yaml`:

```yaml
incremental_refresh:
  fact_sales:
    enabled: true
    historical_period:
      value: 3
      unit: Years
    incremental_period:
      value: 10
      unit: Days
    detect_data_changes: false
    only_refresh_complete_periods: true

  fact_events:
    enabled: true
    historical_period:
      value: 1
      unit: Years
    incremental_period:
      value: 1
      unit: Days
    detect_data_changes: true
    detect_column: modified_date
```

## 📊 Implementation Steps

### Step 1: Generate Configuration

```bash
# Generate incremental refresh configuration
python scripts/configure_incremental_refresh.py \
  --input config/incremental_refresh.yaml \
  --output dist/powerbi_package/
```

### Step 2: Apply in Power BI

1. Open the generated `.pbit` file
2. Navigate to each fact table
3. Right-click → Incremental refresh
4. Configure using generated settings
5. Publish to Power BI Service

### Step 3: Verify Setup

```dax
// Test query to verify filtering
EVALUATE
SUMMARIZE(
    fact_sales,
    "Min Date", MIN(fact_sales[transaction_date]),
    "Max Date", MAX(fact_sales[transaction_date]),
    "Row Count", COUNTROWS(fact_sales)
)
```

## 🎛️ Policy Settings

### Historical Period
- **Purpose**: Data to keep permanently
- **Recommended**: 2-3 years
- **Format**: Number + Years/Months

### Incremental Period
- **Purpose**: Data to refresh regularly
- **Recommended**: 7-30 days
- **Format**: Number + Days

### Detect Data Changes
- **Purpose**: Identify modified rows
- **Requires**: Last modified column
- **Performance**: May impact refresh time

### Only Refresh Complete Periods
- **Purpose**: Avoid partial period data
- **Default**: True
- **Use Case**: Daily/monthly aggregations

## 📈 Refresh Strategies

### 1. Rolling Window (Default)
```yaml
strategy: rolling_window
historical: 3 Years
incremental: 10 Days
```
- Keeps 3 years of history
- Refreshes last 10 days
- Suitable for most scenarios

### 2. Archive Pattern
```yaml
strategy: archive
historical: 5 Years
incremental: 1 Month
archive_after: 1 Year
```
- Long-term historical storage
- Monthly refresh for recent data
- Archives older partitions

### 3. Real-time Pattern
```yaml
strategy: realtime
historical: 6 Months
incremental: 1 Day
polling_interval: 1 Hour
```
- Near real-time updates
- Shorter historical window
- Frequent refresh cycles

### 4. Hybrid Pattern
```yaml
strategy: hybrid
current_year: Daily
previous_year: Weekly
historical: Monthly
```
- Variable refresh frequencies
- Optimizes for data patterns
- Balances performance/freshness

## 🔍 Monitoring and Validation

### Refresh History

Check refresh performance:

```sql
-- Power BI Service Admin API
GET https://api.powerbi.com/v1.0/myorg/datasets/{datasetId}/refreshes
```

### Partition Information

```dax
// View partition details
EVALUATE
INFO.PARTITIONS()
```

### Performance Metrics

Monitor these KPIs:
- Refresh duration
- Rows processed
- Partition count
- Data volume
- Error rate

## 🚨 Common Issues

### Issue: Parameters Not Recognized

**Symptom**: RangeStart/RangeEnd not filtering data

**Solution**:
```powerquery
// Ensure parameter types
RangeStart = #datetime(2024, 1, 1, 0, 0, 0) meta [IsParameterQuery=true, Type="DateTime"]
RangeEnd = #datetime(2025, 12, 31, 23, 59, 59) meta [IsParameterQuery=true, Type="DateTime"]
```

### Issue: Duplicate Data

**Symptom**: Same records appear multiple times

**Solution**:
1. Check date column consistency
2. Verify filter logic
3. Ensure unique constraints
4. Review overlap periods

### Issue: Missing Recent Data

**Symptom**: Latest data not appearing

**Solution**:
1. Verify incremental period covers today
2. Check time zone settings
3. Confirm source data availability
4. Review refresh schedule

### Issue: Slow Refresh Performance

**Symptom**: Refresh takes too long

**Solution**:
1. Reduce incremental period
2. Add indexes on date columns
3. Optimize source queries
4. Enable query folding

## ⚡ Performance Optimization

### 1. Query Folding
Ensure filters push down to source:

```powerquery
// Good: Foldable
Table.SelectRows(Source, each [date] >= RangeStart)

// Bad: Non-foldable
Table.SelectRows(Source, each Date.From([date]) >= Date.From(RangeStart))
```

### 2. Partition Sizing
- Target: 10-50 million rows per partition
- Avoid: Too many small partitions
- Balance: Processing time vs. granularity

### 3. Source Optimization
- Add indexes on filter columns
- Partition source tables
- Use columnar storage
- Implement CDC if available

## 📊 Advanced Configuration

### Custom Date Columns

```yaml
date_columns:
  fact_sales: order_date
  fact_inventory: snapshot_date
  fact_events: event_timestamp
```

### Multiple Date Filters

```yaml
complex_filter:
  fact_orders:
    primary: order_date
    secondary: ship_date
    logic: "order_date >= RangeStart OR ship_date >= RangeStart"
```

### Time Zone Handling

```yaml
timezone:
  source: "UTC"
  target: "America/New_York"
  conversion: automatic
```

## 🔐 Security Considerations

### Data Retention
- Comply with retention policies
- Implement data purging
- Document retention rules

### Access Control
- Limit parameter modification
- Secure refresh credentials
- Audit refresh activities

## 📋 Validation Checklist

Before deploying incremental refresh:

- [ ] RangeStart/RangeEnd parameters created
- [ ] Date filters applied to queries
- [ ] Policy configured for each table
- [ ] Test refresh in development
- [ ] Verify data completeness
- [ ] Monitor initial refreshes
- [ ] Document configuration
- [ ] Set up alerting

## 🛠️ Troubleshooting Script

```python
# scripts/validate_incremental_refresh.py
from data_quality_toolkit.exporters.bi import validate_incremental_refresh

# Validate configuration
issues = validate_incremental_refresh(
    config_path="config/incremental_refresh.yaml",
    model_path="dist/powerbi_package/model.pbit"
)

if issues:
    print("Issues found:")
    for issue in issues:
        print(f"  - {issue}")
else:
    print("✅ Incremental refresh configuration valid")
```

## 📚 Related Documentation

- [Date Table Configuration](date_table.md)
- [RLS Testing Guide](rls_testing.md)
- [Performance Tuning](../performance/tuning.md)
- [Power BI Best Practices](../powerbi_best_practices.md)

## 🔗 External Resources

- [Microsoft: Incremental Refresh](https://docs.microsoft.com/power-bi/connect-data/incremental-refresh-overview)
- [Power BI REST API](https://docs.microsoft.com/rest/api/power-bi/)
- [Query Folding Guide](https://docs.microsoft.com/power-query/query-folding-basics)

---

**Last Updated**: August 2025
**Toolkit Version**: 0.0.0
