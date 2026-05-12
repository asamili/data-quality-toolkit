# Power BI Row-Level Security (RLS) Testing Guide

## 🔒 Overview

Row-Level Security (RLS) restricts data access at the row level based on user identity. The Data Quality Toolkit automatically generates RLS roles and filters, ensuring users only see data they're authorized to access. This guide covers testing and validation of RLS implementations.

## 🎯 Purpose

RLS Testing ensures:
- Data security compliance
- Correct user access permissions
- No data leakage between users
- Performance optimization
- Audit trail completeness

## 📋 RLS Architecture

### Generated Roles

The toolkit creates three standard role types:

| Role | Description | Filter Logic |
|------|-------------|--------------|
| **OwnerOnly** | See only owned data | `[owner_email] = USERPRINCIPALNAME()` |
| **DatasetScope** | Access specific datasets | `[dataset_id] IN VALUES(DatasetAccess[dataset_id])` |
| **TimeRange** | Time-bounded access | `[date] >= DATE(2024,1,1) && [date] <= TODAY()` |
| **DepartmentView** | Department-based access | `[department] = LOOKUPVALUE(Users[department], Users[email], USERPRINCIPALNAME())` |
| **Admin** | Full access (no filters) | No filter applied |

### Configuration File

RLS configuration in `config/rls_policy.yaml`:

```yaml
rls_policies:
  OwnerOnly:
    description: "Users see only their own data"
    tables:
      - fact_sales
      - fact_orders
    filter_dax: |
      [owner_email] = USERPRINCIPALNAME()

  RegionalManager:
    description: "Managers see their region's data"
    tables:
      - fact_sales
      - dim_customer
      - dim_store
    filter_dax: |
      [region] = LOOKUPVALUE(
        UserRegions[region],
        UserRegions[email],
        USERPRINCIPALNAME()
      )

  TimeRestricted:
    description: "Last 90 days only"
    tables:
      - fact_events
    filter_dax: |
      [event_date] >= TODAY() - 90
```

## 🧪 Testing Process

### Step 1: Generate RLS Configuration

```bash
# Generate RLS roles and filters
python scripts/generate_rls.py \
  --config config/rls_policy.yaml \
  --output dist/powerbi_package/roles.tmsl.json
```

### Step 2: Import to Power BI

1. Open Power BI Desktop
2. Navigate to Modeling → Manage Roles
3. Import roles from `roles.tmsl.json`
4. Verify filter expressions

### Step 3: Test with "View As"

1. Click Modeling → View As
2. Select role to test
3. Optionally specify user email
4. Verify data filtering

## 🔍 Testing Scenarios

### 1. Basic Access Test

```python
# Test script for basic RLS validation
from data_quality_toolkit.exporters.bi.rls import test_rls_access

test_cases = [
    {
        "user": "alice@company.com",
        "role": "OwnerOnly",
        "expected_rows": 1250,
        "tables": ["fact_sales", "fact_orders"]
    },
    {
        "user": "bob@company.com",
        "role": "RegionalManager",
        "expected_rows": 5430,
        "tables": ["fact_sales", "dim_customer"]
    }
]

results = test_rls_access(
    model_path="dist/powerbi_package/model.pbit",
    test_cases=test_cases
)

for result in results:
    print(f"User: {result['user']}")
    print(f"Role: {result['role']}")
    print(f"Status: {'✅ PASS' if result['passed'] else '❌ FAIL'}")
    print(f"Actual rows: {result['actual_rows']}")
    print("---")
```

### 2. Cross-Role Validation

Test multiple roles for same user:

```dax
// DAX query to validate role combinations
EVALUATE
SUMMARIZECOLUMNS(
    "Role", SELECTEDVALUE(SecurityRole[Role]),
    "RowCount", COUNTROWS(fact_sales),
    "Distinct Owners", DISTINCTCOUNT(fact_sales[owner_email]),
    "Date Range",
        MIN(fact_sales[date]) & " to " & MAX(fact_sales[date])
)
```

### 3. Data Leakage Test

Ensure no unauthorized data access:

```python
# Automated leakage detection
def test_data_isolation():
    users = ["user1@company.com", "user2@company.com"]

    for user in users:
        # Simulate user context
        visible_data = get_visible_data(user, "OwnerOnly")

        # Check for other users' data
        leaked_data = visible_data[
            visible_data['owner_email'] != user
        ]

        assert leaked_data.empty, f"Data leakage for {user}!"
```

### 4. Performance Testing

Measure RLS impact on query performance:

```dax
// Performance comparison query
EVALUATE
{
    ("No RLS", COUNTROWS(fact_sales)),
    ("With RLS", CALCULATE(COUNTROWS(fact_sales),
        FILTER(fact_sales, [owner_email] = "test@company.com")))
}
```

## 📊 View As Testing Guide

### Desktop Testing Steps

1. **Open Model**
   - Load the Power BI template
   - Ensure data is refreshed

2. **Access View As**
   - Click Modeling → View As
   - Select role from dropdown

3. **Add User Context**
   - Click "Other user"
   - Enter test email address
   - Apply selection

4. **Validate Filtering**
   - Check row counts in visuals
   - Verify slicers show correct values
   - Confirm measures calculate properly

5. **Test Edge Cases**
   - Empty result sets
   - Maximum data access
   - Invalid user emails
   - Multiple role assignments

### Service Testing Steps

1. **Publish to Workspace**
   - Upload model to Power BI Service
   - Configure dataset settings

2. **Assign Security**
   - Dataset → Security
   - Add users/groups to roles
   - Save assignments

3. **Test as User**
   - Share report with test users
   - Log in as test user
   - Verify data visibility

4. **Audit Access**
   - Review audit logs
   - Check access patterns
   - Monitor failed attempts

## 🛠️ Automated Testing Framework

### Test Configuration

Create `tests/rls_test_config.json`:

```json
{
  "test_suite": "RLS Validation",
  "model": "dist/powerbi_package/model.pbit",
  "test_cases": [
    {
      "name": "Owner can see own data",
      "user": "alice@company.com",
      "role": "OwnerOnly",
      "assertions": [
        {
          "table": "fact_sales",
          "column": "owner_email",
          "expected_values": ["alice@company.com"],
          "unexpected_values": ["bob@company.com"]
        }
      ]
    },
    {
      "name": "Manager sees region",
      "user": "manager@company.com",
      "role": "RegionalManager",
      "assertions": [
        {
          "table": "dim_store",
          "column": "region",
          "expected_values": ["North", "Northeast"],
          "row_count_min": 100,
          "row_count_max": 500
        }
      ]
    }
  ]
}
```

### Running Tests

```bash
# Run RLS test suite
python -m pytest tests/test_rls.py -v

# Generate test report
python scripts/validate_rls.py \
  --config tests/rls_test_config.json \
  --output reports/rls_validation.html
```

## 🚨 Common Issues and Solutions

### Issue: Users See No Data

**Symptoms**: Blank reports after RLS applied

**Solutions**:
1. Verify user email matches data
2. Check USERPRINCIPALNAME() format
3. Validate filter DAX syntax
4. Ensure relationships are bi-directional if needed

### Issue: Users See All Data

**Symptoms**: RLS not filtering any rows

**Solutions**:
1. Confirm roles are applied to tables
2. Check role assignments in Service
3. Verify filter expressions return FALSE for some rows
4. Test with explicit user context

### Issue: Performance Degradation

**Symptoms**: Slow queries with RLS enabled

**Solutions**:
1. Optimize filter DAX expressions
2. Add indexes on filtered columns
3. Use static tables for user permissions
4. Consider aggregated models

### Issue: Dynamic RLS Not Working

**Symptoms**: LOOKUPVALUE not finding matches

**Solutions**:
```dax
// Add error handling
VAR UserDept =
    LOOKUPVALUE(
        Users[Department],
        Users[Email], USERPRINCIPALNAME(),
        "Unknown"  // Default value
    )
RETURN
    [Department] = UserDept || UserDept = "Unknown"
```

## 📋 Testing Checklist

### Pre-Deployment

- [ ] All roles defined in configuration
- [ ] Filter expressions validated
- [ ] Test users created
- [ ] Test data prepared
- [ ] Relationships verified

### Desktop Testing

- [ ] Each role tested with View As
- [ ] Multiple users tested per role
- [ ] Edge cases validated
- [ ] Performance acceptable
- [ ] Measures calculate correctly

### Service Testing

- [ ] Roles published to Service
- [ ] Users assigned to roles
- [ ] Live testing completed
- [ ] Cross-browser testing
- [ ] Mobile app testing

### Post-Deployment

- [ ] Production users assigned
- [ ] Audit logging enabled
- [ ] Monitoring configured
- [ ] Documentation updated
- [ ] Support team trained

## 🔐 Security Best Practices

### 1. Principle of Least Privilege
- Default to most restrictive access
- Grant additional permissions explicitly
- Regular access reviews

### 2. Static vs Dynamic RLS
- Static: Better performance, easier testing
- Dynamic: More flexible, harder to debug
- Hybrid: Balance based on needs

### 3. Testing Coverage
- Test all roles
- Test all user types
- Test data boundaries
- Test error conditions

### 4. Documentation
- Document all roles and their purpose
- Maintain test user list
- Record test results
- Update on changes

## 📊 Monitoring and Auditing

### Activity Tracking

```python
# Monitor RLS usage
from data_quality_toolkit.telemetry import track_rls_access

@track_rls_access
def get_sales_data(user_context):
    # Your data access code
    pass
```

### Audit Queries

```sql
-- Power BI audit log query
SELECT
    UserName,
    Activity,
    DatasetName,
    ReportName,
    Timestamp
FROM
    PowerBIAuditLog
WHERE
    Activity LIKE '%RLS%'
    AND Timestamp >= DATEADD(day, -7, GETDATE())
```

## 🎯 Advanced Testing Patterns

### 1. Hierarchical Security

```dax
// Manager sees own and subordinates' data
VAR CurrentUser = USERPRINCIPALNAME()
VAR UserLevel =
    LOOKUPVALUE(OrgHierarchy[Level], OrgHierarchy[Email], CurrentUser)
RETURN
    [Level] >= UserLevel || [Manager_Email] = CurrentUser
```

### 2. Time-Based Access

```dax
// Access expires after specific date
VAR AccessExpiry =
    LOOKUPVALUE(UserAccess[ExpiryDate], UserAccess[Email], USERPRINCIPALNAME())
RETURN
    [Date] <= AccessExpiry && [Date] <= TODAY()
```

### 3. Composite Security

```dax
// Combine multiple security dimensions
VAR HasRegionAccess = [Region] IN VALUES(UserRegions[Region])
VAR HasDepartmentAccess = [Department] IN VALUES(UserDepartments[Department])
VAR HasTimeAccess = [Date] >= TODAY() - 90
RETURN
    HasRegionAccess && HasDepartmentAccess && HasTimeAccess
```

## 📚 Related Documentation

- [Date Table Configuration](date_table.md)
- [Incremental Refresh Setup](incremental_refresh.md)
- [Security Best Practices](../security/best_practices.md)
- [DAX Patterns](../dax/patterns.md)

## 🔗 External Resources

- [Microsoft: RLS Guidance](https://docs.microsoft.com/power-bi/admin/service-admin-rls)
- [DAX Patterns: Dynamic Security](https://www.daxpatterns.com/dynamic-security/)
- [Power BI Security Whitepaper](https://docs.microsoft.com/power-bi/guidance/whitepaper-powerbi-security)

---

**Last Updated**: August 2025
**Toolkit Version**: 0.0.0
