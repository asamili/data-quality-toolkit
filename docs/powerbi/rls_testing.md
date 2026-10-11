# Power BI Row-Level Security (RLS) with DQT Outputs

## Overview

Row-Level Security (RLS) restricts which rows a user can see in a Power BI model. DQT does not
implement RLS — it produces clean, well-shaped tables you secure with Power BI's own RLS roles.
Use DQT to validate the **quality and shape** of the data; author and test the RLS rules in
Power BI.

> **Scope.** This page explains how DQT's exported tables support a Power BI RLS setup. The roles
> and filters themselves are authored and tested by you in Power BI Desktop / Service.

## What DQT provides

`dqt build-pbi` assembles a zero-config Power BI package (default `dist/powerbi_package/`):

- `star/` — `dim_dataset.csv`, `dim_column.csv`, `fact_profile_runs.csv`, `fact_quality_metrics.csv`
- `time/dim_time.csv` — the time dimension
- `relationships.json` — star relationships used by the model
- `parameters.json` — a single `BaseFolder` parameter
- `README.txt` — load instructions

DQT can also profile and assess any candidate RLS mapping table (for example a user→region CSV)
with `dqt profile` / `dqt assess` before you load it into the model — missing or duplicated keys
are a common cause of RLS filters silently failing.

## What DQT does NOT provide

DQT does **not** generate any of the following — author them in Power BI Desktop / Service:

- RLS roles, role filters, or `roles.tmsl.json` / security-role deployment artifacts
- User-to-row mapping tables (you supply these)
- An RLS access-test engine or test runner (there is no `test_rls_access` and no bundled
  `tests/test_rls.py`)
- Telemetry / access-monitoring modules (no `track_rls_access`; use Power BI Service audit logs)

## Authoring and testing RLS in Power BI

1. Build the model from the DQT package (CSVs under `star/` and `time/`).
2. In Power BI Desktop → **Modeling → Manage Roles**, create roles with DAX filters, e.g.:

   ```dax
   // "OwnerOnly" role: a user sees only rows they own
   [owner_email] = USERPRINCIPALNAME()
   ```

   For dynamic security, look up the user's scope from a mapping table:

   ```dax
   // "RegionalManager" role
   [region] = LOOKUPVALUE(UserRegions[region], UserRegions[email], USERPRINCIPALNAME())
   ```

3. Test each role with **Modeling → View As** (optionally as a specific user); confirm row
   counts, slicer values, and measures behave as expected.
4. In the Service, assign users/groups to roles under Dataset → Security, verify with a test
   user, and review audit logs.

> Validate the *quality* of any user-mapping or dimension table with `dqt assess` before relying
> on it for security filters.

## External references

- [Microsoft: Row-level security (RLS)](https://learn.microsoft.com/power-bi/enterprise/service-admin-rls)
- [DAX Patterns: Dynamic security](https://www.daxpatterns.com/dynamic-security/)

## Related documentation

- [Date Table Configuration](date_table.md)
- [Incremental Refresh Setup](incremental_refresh.md)

---

**Last Updated**: June 2026
**Toolkit Version**: 2.10.0
