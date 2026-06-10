# Demo Package — Issue Showcase

This demo is the issue-focused counterpart to the Uber happy-path demo.
It uses a tiny crafted CSV that deterministically triggers multiple quality rules
so you can see DQT's detection in action without needing real data.

## Use this demo when

-   You want to show issue detection instead of a clean happy path.
-   You want to show how null-threshold tuning changes results.
-   You want to show export artifacts with visible issues.
-   You want to contrast this demo with the [happy-path demo package](../README.md).

---

## Dataset

`issue_demo.csv` — 5 rows, 4 columns, every column intentionally broken.

| Column | Issue seeded |
| --- | --- |
| ` user_name ` | Leading/trailing whitespace (padded column name) |
| `unnamed` | Placeholder column name |
| `status` | All rows have value `active` — constant column |
| `score` | 4 of 5 rows are empty — 80% missing (critical at default threshold) |

---

## Run the demo

> **Windows (recommended):** use the full interpreter path if `dqt` is not on your PATH.

### Step 1 — Profile

```bash
<path-to-python> -m data_quality_toolkit.adapters.cli.main profile examples/demo/issue_showcase/issue_demo.csv
```

You will see per-column stats including null counts and distinct-value counts.
Notice `status` has `unique: 1` and `score` has `nulls: 4`.

### Step 2 — Assess (default null threshold = 0.20)

```bash
<path-to-python> -m data_quality_toolkit.adapters.cli.main assess examples/demo/issue_showcase/issue_demo.csv
```

Expected issues:

| Issue type | Column | Severity | Category |
| --- | --- | --- | --- |
| `padded_column_name` | ` user_name ` | medium | Schema |
| `placeholder_column_name` | `unnamed` | medium | Schema |
| `constant_column` | `status` | medium | Completeness |
| `missing` | `score` | critical | Completeness |

The overall quality score will be well below 1.0.

### Step 3 — Export star schema artifacts

```bash
<path-to-python> -m data_quality_toolkit.adapters.cli.main export examples/demo/issue_showcase/issue_demo.csv --outdir dist/issue_showcase
```

Produces the following artifacts under `dist/issue_showcase/`:

```text
dist/issue_showcase/
  star/
    dim_dataset.csv
    dim_column.csv
    fact_profile_runs.csv
    fact_quality_metrics.csv
    fact_issues.csv          ← non-empty this time; one row per issue above
    quality_report.json      ← score, issues_total, counts by severity/category
```

Open `fact_issues.csv` to see all four issues as structured rows.
Open `quality_report.json` to see the overall score and issue breakdown.

---

## Tuning completeness sensitivity

The `--null-threshold` flag controls how much missing data triggers a `missing` issue.
Default is `0.20` (20%). Lower it to catch smaller gaps:

```bash
# Flag any column with ≥ 5% missing values
<path-to-python> -m data_quality_toolkit.adapters.cli.main assess examples/demo/issue_showcase/issue_demo.csv --null-threshold 0.05
```

Raise it to suppress low-severity missing-data noise on messy real-world data:

```bash
# Only flag columns with ≥ 50% missing values
<path-to-python> -m data_quality_toolkit.adapters.cli.main assess examples/demo/issue_showcase/issue_demo.csv --null-threshold 0.50
```

---

## Tracking issues over runs with compare

`compare` works here too. After two or more `export` runs against this dataset:

```bash
<path-to-python> -m data_quality_toolkit.adapters.cli.main compare examples/demo/issue_showcase/issue_demo.csv --outdir dist/issue_showcase
```

The first compare will return `not_enough_runs` if only one export run exists.
Run `export` a second time to build the history, then re-run `compare`.

---

## Note on generated outputs

The `dist/` directory is git-ignored. Do not commit anything under `dist/`.

---

## Further reading

- [Uber happy-path demo](../README.md) — clean data, no issues, full export walkthrough
- [Full CLI reference](../../../README.md)
