"""Consistency guards for the unified UI journey step labels.

Every registered page derives its ``Step N of 16 — <Name>`` label from the
single ``journey`` source of truth (``adapters/ui/journey.py``), instead of each
page hard-coding its own count. These tests pin the count, the canonical
per-page labels and their order, verify each page wires its own journey key, and
guard against stale ``of 11`` wording resurfacing (journey/IA alignment).
"""

from __future__ import annotations

from pathlib import Path

import data_quality_toolkit
from data_quality_toolkit.adapters.ui import journey

_UI_DIR = Path(data_quality_toolkit.__file__).resolve().parent / "adapters" / "ui"
_PAGES_DIR = _UI_DIR / "pages"

# page_key -> (source filename, canonical visible label). Order mirrors the
# app.main st.navigation registry (Start -> Analyze -> Prepare -> Operate ->
# Deliver -> System).
_EXPECTED: dict[str, tuple[str, str]] = {
    "start": ("start.py", "Step 1 of 16 — Start / Load Dataset"),
    "data_overview": ("data_overview.py", "Step 2 of 16 — Data Overview"),
    "eda_explorer": ("eda_explorer.py", "Step 3 of 16 — EDA Explorer"),
    "statistics_lab": ("statistics_lab.py", "Step 4 of 16 — Statistics Lab"),
    "quality_score": ("quality_score.py", "Step 5 of 16 — Quality Score"),
    "preprocess_studio": ("preprocess_studio.py", "Step 6 of 16 — Preprocess Studio"),
    "pipeline_runner": ("pipeline_runner.py", "Step 7 of 16 — Pipeline Runner"),
    "drift_explorer": ("drift_explorer.py", "Step 8 of 16 — Drift Monitoring"),
    "export": ("export.py", "Step 9 of 16 — Export"),
    "run_history": ("run_history.py", "Step 10 of 16 — Quality History"),
    "artifact_center": ("artifact_center.py", "Step 11 of 16 — Artifact Center"),
    "kpi_catalog": ("kpi_catalog.py", "Step 12 of 16 — KPI Catalog"),
    "dim_time": ("dim_time.py", "Step 13 of 16 — Dim Time"),
    "manifest_viewer": ("manifest_viewer.py", "Step 14 of 16 — Manifest Viewer"),
    "settings_diagnostics": ("settings_diagnostics.py", "Step 15 of 16 — Settings / Governance"),
    "help_about": ("help_about.py", "Step 16 of 16 — Help / About"),
}


def _read(filename: str) -> str:
    return (_PAGES_DIR / filename).read_text(encoding="utf-8")


def test_journey_step_count_matches_page_surface() -> None:
    # 16 audited UI pages in the app.main navigation registry.
    assert journey.JOURNEY_STEP_COUNT == 16
    assert len(_EXPECTED) == 16
    assert len(journey.JOURNEY) == 16


def test_journey_emits_canonical_labels_in_order() -> None:
    for key, (_, label) in _EXPECTED.items():
        assert journey.step_label(key) == label, f"{key} produced {journey.step_label(key)!r}"
    # Positions 1..16 emit the expected sequence in registry order.
    ordered = [journey.step_label(key) for key, _ in journey.JOURNEY]
    assert ordered == [label for _, label in _EXPECTED.values()]


def test_journey_keys_match_expected_order() -> None:
    assert [key for key, _ in journey.JOURNEY] == list(_EXPECTED)


def test_unknown_page_key_fails_loudly() -> None:
    import pytest

    with pytest.raises(KeyError):
        journey.step_label("not_a_page")


def test_every_page_wires_its_journey_key() -> None:
    for key, (filename, _) in _EXPECTED.items():
        source = _read(filename)
        assert (
            f'journey.step_label("{key}")' in source
        ), f"{filename} is not wired to journey key {key!r}"


def test_no_stale_of_11_wording_in_ui() -> None:
    for path in _PAGES_DIR.glob("*.py"):
        assert "of 11" not in path.read_text(encoding="utf-8"), f"stale 'of 11' in {path.name}"
    assert "of 11" not in (_UI_DIR / "journey.py").read_text(encoding="utf-8")


def test_start_page_title_matches_navigation_label() -> None:
    source = _read("start.py")
    assert '"Start / Load Dataset"' in source
    assert "Start / Dataset Context" not in source
