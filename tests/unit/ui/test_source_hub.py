"""Focused tests for the Source Hub foundation helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from data_quality_toolkit.adapters.ui.components.source_hub import (
    PATH_REDACTED_DISPLAY,
    SECTION_MONITORING_HISTORY,
    SECTION_OUTPUT_LOCATIONS,
    SECTION_SESSIONS_RUNS,
    SECTION_SOURCE_SUMMARY,
    SQLITE_EXTENSIONS,
    basename_first_display,
    build_source_hub_sections,
    build_source_summary_items,
    derive_workspace_defaults,
    get_source_hub_fields,
    identifier_validation_badges,
    path_validation_badges,
    render_source_hub_section,
    seed_workspace_defaults,
    source_field_badges,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import (
    DATASET_CONTEXT,
    DRIFT_DATASET_FILTER,
    SRC_DATASET_ID,
    SRC_EXPORT_OUT_DIR,
    SRC_MONITORING_DB,
    SRC_PBI_OUT_DIR,
    SRC_QUALITY_HISTORY_DB,
    SRC_SESSION_RUN_ID,
    SRC_SESSIONS_ROOT,
    SRC_WORKSPACE_ROOT,
)


class FakeSt:
    """Records Source Hub render calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.session_state: dict[str, Any] = {}

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def subheader(self, *args: Any, **kwargs: Any) -> None:
        self._record("subheader", *args, **kwargs)

    def caption(self, *args: Any, **kwargs: Any) -> None:
        self._record("caption", *args, **kwargs)

    def write(self, *args: Any, **kwargs: Any) -> None:
        self._record("write", *args, **kwargs)

    def text_input(self, label: str, **kwargs: Any) -> str:
        self._record("text_input", label, **kwargs)
        return ""

    def calls_named(self, name: str) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
        return [(args, kwargs) for kind, args, kwargs in self.calls if kind == name]


def _field_by_key(key: str):
    return next(field for field in get_source_hub_fields() if field.key == key)


def test_source_hub_field_definitions_keep_sources_distinct() -> None:
    fields = get_source_hub_fields()
    keys = {field.key for field in fields}

    assert DATASET_CONTEXT in keys
    assert SRC_WORKSPACE_ROOT not in keys
    assert SRC_MONITORING_DB in keys
    assert SRC_QUALITY_HISTORY_DB in keys
    assert SRC_MONITORING_DB != SRC_QUALITY_HISTORY_DB
    assert SRC_DATASET_ID in keys
    assert DRIFT_DATASET_FILTER not in keys
    assert SRC_EXPORT_OUT_DIR in keys
    assert SRC_PBI_OUT_DIR in keys
    assert all(field.id != "manifest_path" for field in fields)


def test_workspace_defaults_are_pure_source_suggestions(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"

    defaults = derive_workspace_defaults(str(workspace_root))

    assert defaults == {
        SRC_SESSIONS_ROOT: str(workspace_root / "sessions"),
        SRC_EXPORT_OUT_DIR: str(workspace_root / "exports"),
        SRC_PBI_OUT_DIR: str(workspace_root / "powerbi"),
    }
    # Database fields are never derived; they stay blank until they exist.
    assert SRC_MONITORING_DB not in defaults
    assert SRC_QUALITY_HISTORY_DB not in defaults
    assert SRC_SESSION_RUN_ID not in defaults
    assert SRC_DATASET_ID not in defaults
    assert DATASET_CONTEXT not in defaults
    assert DRIFT_DATASET_FILTER not in defaults
    assert not workspace_root.exists()


def test_relative_workspace_defaults_are_normalized_to_absolute(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_root = Path("station-workspace")

    defaults = derive_workspace_defaults(str(workspace_root))

    expected_root = tmp_path / workspace_root
    assert SRC_MONITORING_DB not in defaults
    assert SRC_QUALITY_HISTORY_DB not in defaults
    assert defaults[SRC_SESSIONS_ROOT] == str(expected_root / "sessions")
    assert defaults[SRC_EXPORT_OUT_DIR] == str(expected_root / "exports")
    assert defaults[SRC_PBI_OUT_DIR] == str(expected_root / "powerbi")
    assert Path(defaults[SRC_SESSIONS_ROOT]).is_absolute()
    assert Path(defaults[SRC_EXPORT_OUT_DIR]).is_absolute()
    assert Path(defaults[SRC_PBI_OUT_DIR]).is_absolute()
    assert not expected_root.exists()


def test_workspace_defaults_ignore_blank_roots() -> None:
    assert derive_workspace_defaults("") == {}
    assert derive_workspace_defaults("   ") == {}


def test_seed_workspace_defaults_fills_only_missing_or_blank_values(tmp_path: Path) -> None:
    workspace_root = tmp_path / "workspace"
    state: dict[str, Any] = {
        SRC_WORKSPACE_ROOT: str(workspace_root),
        SRC_MONITORING_DB: "/explicit/monitoring.db",
        SRC_QUALITY_HISTORY_DB: "",
        SRC_SESSIONS_ROOT: "   ",
    }

    seeded = seed_workspace_defaults(state)

    assert seeded == (
        SRC_SESSIONS_ROOT,
        SRC_EXPORT_OUT_DIR,
        SRC_PBI_OUT_DIR,
    )
    # Explicit monitoring DB is preserved; blank quality-history DB stays blank.
    assert state[SRC_MONITORING_DB] == "/explicit/monitoring.db"
    assert state[SRC_QUALITY_HISTORY_DB] == ""
    assert state[SRC_SESSIONS_ROOT] == str(workspace_root / "sessions")
    assert state[SRC_EXPORT_OUT_DIR] == str(workspace_root / "exports")
    assert state[SRC_PBI_OUT_DIR] == str(workspace_root / "powerbi")
    assert SRC_SESSION_RUN_ID not in state
    assert SRC_DATASET_ID not in state
    assert DATASET_CONTEXT not in state
    assert DRIFT_DATASET_FILTER not in state


def test_seed_workspace_defaults_does_not_overwrite_on_workspace_change(tmp_path: Path) -> None:
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    state: dict[str, Any] = {SRC_WORKSPACE_ROOT: str(workspace_a)}
    seed_workspace_defaults(state)
    state[SRC_WORKSPACE_ROOT] = str(workspace_b)

    seeded = seed_workspace_defaults(state)

    assert seeded == ()
    # Database fields are never seeded, so they stay absent across workspace changes.
    assert SRC_MONITORING_DB not in state
    assert SRC_QUALITY_HISTORY_DB not in state
    assert state[SRC_SESSIONS_ROOT] == str(workspace_a / "sessions")
    assert state[SRC_EXPORT_OUT_DIR] == str(workspace_a / "exports")
    assert state[SRC_PBI_OUT_DIR] == str(workspace_a / "powerbi")


def test_workspace_defaults_do_not_create_missing_paths(tmp_path) -> None:
    workspace_root = tmp_path / "station-workspace"

    defaults = derive_workspace_defaults(str(workspace_root))
    state: dict[str, Any] = {}
    seed_workspace_defaults(state, str(workspace_root))

    assert defaults[SRC_SESSIONS_ROOT] == str(workspace_root / "sessions")
    assert SRC_MONITORING_DB not in defaults
    assert not workspace_root.exists()


def test_workspace_root_never_auto_fills_database_fields(tmp_path: Path) -> None:
    """Blank DB fields stay blank and explicit DB paths are preserved after seeding."""
    workspace_root = tmp_path / "workspace"
    state: dict[str, Any] = {
        SRC_WORKSPACE_ROOT: str(workspace_root),
        SRC_MONITORING_DB: "/explicit/monitoring.db",
    }

    seed_workspace_defaults(state)

    # Explicit monitoring DB is kept; blank quality-history DB is never populated.
    assert state[SRC_MONITORING_DB] == "/explicit/monitoring.db"
    assert SRC_QUALITY_HISTORY_DB not in state
    # Folder defaults are still derived.
    assert state[SRC_SESSIONS_ROOT] == str(workspace_root / "sessions")
    assert state[SRC_EXPORT_OUT_DIR] == str(workspace_root / "exports")
    assert state[SRC_PBI_OUT_DIR] == str(workspace_root / "powerbi")
    # No database file (or workspace folder) is created on disk.
    assert not workspace_root.exists()


def test_output_locations_are_directory_advisory_fields() -> None:
    assert _field_by_key(SRC_EXPORT_OUT_DIR).expected_path == "directory"
    assert _field_by_key(SRC_PBI_OUT_DIR).expected_path == "directory"
    assert _field_by_key(SRC_EXPORT_OUT_DIR).advisory_extensions == ()
    assert _field_by_key(SRC_PBI_OUT_DIR).advisory_extensions == ()


def test_output_location_guidance_uses_windows_friendly_examples() -> None:
    export_field = _field_by_key(SRC_EXPORT_OUT_DIR)
    pbi_field = _field_by_key(SRC_PBI_OUT_DIR)

    assert export_field.placeholder == r"e.g., C:\Users\example_user\Documents\dqt_exports"
    assert pbi_field.placeholder == (r"e.g., C:\Users\example_user\Documents\dqt_exports\powerbi")
    assert "./dist" not in export_field.placeholder
    assert "./dist" not in pbi_field.placeholder

    st = FakeSt()
    output_section = next(
        section
        for section in build_source_hub_sections({})
        if section.title == SECTION_OUTPUT_LOCATIONS
    )

    render_source_hub_section(st, output_section)

    placeholders = {args[0]: kwargs["placeholder"] for args, kwargs in st.calls_named("text_input")}
    assert placeholders["Export output directory"] == export_field.placeholder
    assert placeholders["Power BI package output directory"] == pbi_field.placeholder


def test_quality_history_guidance_uses_windows_friendly_export_example() -> None:
    quality_field = _field_by_key(SRC_QUALITY_HISTORY_DB)

    assert quality_field.placeholder == (
        r"e.g., C:\Users\example_user\Documents\dqt_exports\dqt.db"
    )
    assert "./dist" not in quality_field.placeholder

    st = FakeSt()
    monitoring_section = next(
        section
        for section in build_source_hub_sections({})
        if section.title == SECTION_MONITORING_HISTORY
    )

    render_source_hub_section(st, monitoring_section)

    placeholders = {args[0]: kwargs["placeholder"] for args, kwargs in st.calls_named("text_input")}
    assert placeholders["Quality-history database"] == quality_field.placeholder


def test_basename_first_display_hides_absolute_paths() -> None:
    assert basename_first_display(r"C:\Users\example_user\private\monitoring.db") == "monitoring.db"
    assert basename_first_display("/tmp/private/dqt.db") == "dqt.db"
    assert basename_first_display("dist/star") == "star"
    assert basename_first_display("C:\\") == PATH_REDACTED_DISPLAY
    assert basename_first_display("/") == PATH_REDACTED_DISPLAY


def test_path_validation_badges_use_no_write_checks(tmp_path) -> None:
    db_path = tmp_path / "monitoring.db"
    db_path.write_text("", encoding="utf-8")

    labels = [
        badge.label
        for badge in path_validation_badges(
            str(db_path), expected_path="file", advisory_extensions=SQLITE_EXTENSIONS
        )
    ]

    assert labels == ["Path exists", "File path", "Extension looks right"]


def test_missing_output_directory_is_not_created(tmp_path) -> None:
    missing_dir = tmp_path / "missing-output"

    badges = path_validation_badges(str(missing_dir), expected_path="directory")

    assert [badge.status for badge in badges] == ["missing"]
    assert not missing_dir.exists()


def test_path_validation_keeps_extension_and_kind_advisory(tmp_path) -> None:
    wrong_ext = tmp_path / "monitoring.txt"
    wrong_ext.write_text("", encoding="utf-8")

    badges = path_validation_badges(
        str(wrong_ext), expected_path="directory", advisory_extensions=SQLITE_EXTENSIONS
    )

    assert ("Expected folder", "warning") in [(badge.label, badge.status) for badge in badges]
    assert ("Extension advisory", "warning") in [(badge.label, badge.status) for badge in badges]


def test_dataset_id_validation_accepts_any_non_empty_hint() -> None:
    field = _field_by_key(SRC_DATASET_ID)

    badges = source_field_badges(field, "not-a-sha")

    assert badges == identifier_validation_badges("not-a-sha", dataset_id=True)
    assert badges[0].status == "ok"


def test_source_summary_uses_safe_primary_values() -> None:
    context = DatasetContext(
        source_path=r"C:\Users\example_user\private\customers.csv",
        display_name="customers.csv",
        size_bytes=100,
        modified_ns=1,
    )
    state = {
        SRC_MONITORING_DB: r"C:\Users\example_user\private\monitoring.db",
        SRC_QUALITY_HISTORY_DB: "/tmp/private/dqt.db",
        SRC_SESSIONS_ROOT: r"C:\Users\example_user\private\sessions",
        SRC_SESSION_RUN_ID: "run-123",
        SRC_DATASET_ID: "plain dataset id",
        SRC_EXPORT_OUT_DIR: "/tmp/private/dist",
        SRC_PBI_OUT_DIR: "/tmp/private/dist/powerbi",
    }

    items = build_source_summary_items(state, context)
    by_label = {item.label: item for item in items}

    assert by_label["Dataset source"].primary == "customers.csv"
    assert by_label["Local monitoring database"].primary == "monitoring.db"
    assert by_label["Quality-history database"].primary == "dqt.db"
    assert by_label["Sessions Root"].primary == "sessions"
    assert by_label["Manifest source"].primary == "run-123"
    assert by_label["Manifest source"].raw_value.endswith(("/run-123", "\\run-123"))
    assert by_label["Export output directory"].primary == "dist"
    assert by_label["Power BI package output directory"].primary == "powerbi"
    assert by_label["Local monitoring database"].raw_value.startswith("C:")


def test_source_hub_sections_are_grouped_for_later_page_wiring() -> None:
    sections = build_source_hub_sections({})

    assert [section.title for section in sections] == [
        SECTION_MONITORING_HISTORY,
        SECTION_SESSIONS_RUNS,
        SECTION_OUTPUT_LOCATIONS,
        SECTION_SOURCE_SUMMARY,
    ]
    assert [field.key for field in sections[0].fields] == [
        SRC_MONITORING_DB,
        SRC_QUALITY_HISTORY_DB,
    ]
    assert [field.key for field in sections[1].fields] == [
        SRC_SESSIONS_ROOT,
        SRC_SESSION_RUN_ID,
        SRC_DATASET_ID,
    ]
    assert [field.key for field in sections[2].fields] == [
        SRC_EXPORT_OUT_DIR,
        SRC_PBI_OUT_DIR,
    ]
    assert sections[3].summary_items


def test_render_section_uses_shared_source_context_inputs() -> None:
    st = FakeSt()
    output_section = next(
        section
        for section in build_source_hub_sections({})
        if section.title == SECTION_OUTPUT_LOCATIONS
    )

    render_source_hub_section(st, output_section)

    text_inputs = st.calls_named("text_input")
    assert [args[0] for args, _ in text_inputs] == [
        "Export output directory",
        "Power BI package output directory",
    ]
    assert [kwargs["key"] for _, kwargs in text_inputs] == [SRC_EXPORT_OUT_DIR, SRC_PBI_OUT_DIR]
