# DQT Dashboard — CSV to Dashboard Walkthrough

The DQT dashboard is an experimental Streamlit app that visualizes run
history: a score trend and a latest-run issues breakdown.

**The dashboard does not open a raw CSV file directly.** It reads a
dashboard-readable SQLite database (`dqt.db`) plus a `dataset_id`. You produce
that database by running `dqt export` on your CSV first.

---

## Prerequisites

Install the UI extra:

```bash
pip install data-quality-toolkit[ui]
```

---

## Step 1 — Export your CSV

`dqt export` profiles and assesses the CSV, then writes dashboard-readable
artifacts into the output directory:

```bash
dqt export data/orders.csv --outdir dist
```

Windows:

```powershell
dqt export data\orders.csv --outdir dist
```

Among other artifacts, this produces:

- `dist/dqt.db` — the SQLite database the dashboard reads
- `dist/star/quality_report.json` — a per-run summary that contains the `dataset_id`

> `dqt assess` is useful for a quick quality check or a CI gate
> (`--fail-under`), but it only prints results — it does **not** populate
> `dqt.db`. Use `dqt export` for the dashboard.

---

## Step 2 — Find the dataset_id

Open `dist/star/quality_report.json` and copy the `dataset_id` value:

```json
{
  "run_id": "...",
  "dataset_id": "sha1:6f93a3412073e92bec4e09bcc6d7fd9d17aeb64c",
  "score": 0.991
}
```

The same `dataset_id` is included in the JSON that `dqt export` prints to
standard output.

---

## Step 3 — Launch the dashboard

```bash
dqt dashboard
```

This opens the Streamlit app in your browser.

---

## Step 4 — Load your run

In the dashboard, fill in the two fields:

| Field | Value |
|-------|-------|
| Database path | `dist/dqt.db` (Windows: `dist\dqt.db`) |
| Dataset ID | the `dataset_id` copied from `quality_report.json` |

The dashboard then shows the run history for that dataset: the latest-run
issues breakdown, and — once two or more runs exist — the score trend.

Run `dqt export` again on the same CSV with the same `--outdir` to add more
runs and build up the score trend.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| "No run history found for this dataset" | `dataset_id` does not match any run in the database | Re-copy `dataset_id` exactly from `quality_report.json`, including the `sha1:` prefix |
| "Storage error" / database cannot be opened | Wrong database path | Point to the actual `dqt.db` — by default `<outdir>/dqt.db`, e.g. `dist/dqt.db` |
| Dashboard shows nothing after entering values | Only `dqt assess` was run | `assess` does not write `dqt.db`. Run `dqt export <file> --outdir dist` first |
| Issues breakdown shows but no score trend | Fewer than two runs for the dataset | Run `dqt export` on the same CSV at least twice, using the same `--outdir` |
| Windows path not accepted | Mixed forward/backward slashes | Use backslashes on Windows: `dist\dqt.db` |

> **Windows note:** if `dqt` is not on your PATH, invoke the CLI via the
> interpreter, for example:
> `<path-to-python> -m data_quality_toolkit.adapters.cli.main export data\orders.csv --outdir dist`.
> See [Windows-safe invocation](../../README.md#windows-safe-invocation).
