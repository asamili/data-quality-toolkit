"""Consistency guards for the unified UI step labels and the Start page title.

Deterministic source-text checks: no Streamlit rendering and no shared-constant
refactor. Each page declares its own canonical ``Step N of 11 — <Name>`` label;
these tests pin that scheme so the 11 visible step labels stay in lockstep.
"""

from __future__ import annotations

from pathlib import Path

import data_quality_toolkit

_PAGES_DIR = Path(data_quality_toolkit.__file__).resolve().parent / "adapters" / "ui" / "pages"

# Canonical visible step labels (G28F UI cleanup, item 1).
_EXPECTED_STEP_LABELS = {
    "start.py": "Step 1 of 11 — Start / Load Dataset",
    "data_overview.py": "Step 2 of 11 — Data Overview",
    "eda_explorer.py": "Step 3 of 11 — EDA Explorer",
    "statistics_lab.py": "Step 4 of 11 — Statistics Lab",
    "quality_score.py": "Step 5 of 11 — Quality Score",
    "preprocess_studio.py": "Step 6 of 11 — Preprocess Studio",
    "pipeline_runner.py": "Step 7 of 11 — Pipeline Runner",
    "drift_explorer.py": "Step 8 of 11 — Drift Monitoring",
    "artifact_center.py": "Step 9 of 11 — Artifact Center",
    "settings_diagnostics.py": "Step 10 of 11 — Settings / Governance",
    "help_about.py": "Step 11 of 11 — Help / About",
}


def _read(filename: str) -> str:
    return (_PAGES_DIR / filename).read_text(encoding="utf-8")


def test_every_page_declares_its_canonical_step_label() -> None:
    for filename, label in _EXPECTED_STEP_LABELS.items():
        source = _read(filename)
        assert label in source, f"{filename} is missing canonical step label {label!r}"


def test_start_page_title_matches_navigation_label() -> None:
    source = _read("start.py")
    assert '"Start / Load Dataset"' in source
    assert "Start / Dataset Context" not in source
