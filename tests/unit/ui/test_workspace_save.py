"""Tests for the Save-to-Workspace foundation helpers.

The helpers only write text/bytes under a normalized Workspace Root, guard against
path traversal, never overwrite by default, and report basename / workspace-relative
paths only. No page wiring, no export/PBI/pipeline/DB/manifest behavior.
"""

from __future__ import annotations

import ast
from pathlib import Path

from data_quality_toolkit.adapters.ui.services import workspace_save
from data_quality_toolkit.adapters.ui.services.workspace_save import (
    WorkspaceSaveResult,
    build_workspace_filename,
    sanitize_filename,
    save_to_workspace,
)

_PRIVATE_ABS = r"C:\Users\example_user\private\secret.csv"


# --- sanitize_filename --------------------------------------------------------


def test_sanitize_filename_strips_path_separators() -> None:
    assert sanitize_filename("a/b/c.csv") == "c.csv"
    assert sanitize_filename(r"a\b\c.csv") == "c.csv"


def test_sanitize_filename_neutralizes_traversal() -> None:
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("..") == "artifact"
    assert sanitize_filename(".") == "artifact"


def test_sanitize_filename_handles_blank_and_custom_default() -> None:
    assert sanitize_filename("") == "artifact"
    assert sanitize_filename("   ") == "artifact"
    assert sanitize_filename("", default="fallback") == "fallback"


def test_sanitize_filename_preserves_safe_extension() -> None:
    assert sanitize_filename("report.csv") == "report.csv"
    assert sanitize_filename("model.tmsl.json") == "model.tmsl.json"


def test_sanitize_filename_replaces_unsafe_and_whitespace() -> None:
    assert sanitize_filename("my report (final).csv") == "my_report_final.csv"


def test_sanitize_filename_does_not_leak_private_absolute_path() -> None:
    result = sanitize_filename(_PRIVATE_ABS)
    assert result == "secret.csv"
    assert "Users" not in result
    assert ":" not in result
    assert "\\" not in result and "/" not in result


def test_sanitize_filename_caps_long_names_preserving_extension() -> None:
    long_name = "x" * 500 + ".csv"
    result = sanitize_filename(long_name)
    assert len(result) <= 100
    assert result.endswith(".csv")


# --- build_workspace_filename -------------------------------------------------


def test_build_filename_dataset_artifact_timestamp_pattern() -> None:
    name = build_workspace_filename(
        dataset="customers.csv",
        artifact="column_analysis",
        extension="csv",
        timestamp="20260703T120000",
    )
    assert name == "customers__column_analysis__20260703T120000.csv"


def test_build_filename_omits_missing_dataset_and_run() -> None:
    name = build_workspace_filename(artifact="recipe", extension=".json")
    assert name == "recipe.json"


def test_build_filename_includes_run_id() -> None:
    name = build_workspace_filename(
        artifact="dry_run_plan",
        extension="json",
        run_id="run-123",
    )
    assert name == "dry_run_plan__run-123.json"


def test_build_filename_sanitizes_dataset_basename_and_avoids_path_leak() -> None:
    name = build_workspace_filename(
        dataset=_PRIVATE_ABS,
        artifact="quality",
        extension="csv",
    )
    assert name == "secret__quality.csv"
    assert "Users" not in name
    assert "\\" not in name and "/" not in name


def test_build_filename_is_deterministic_when_timestamp_passed() -> None:
    kwargs = {
        "dataset": "orders",
        "artifact": "outliers",
        "extension": "csv",
        "timestamp": "20260101T000000",
    }
    assert build_workspace_filename(**kwargs) == build_workspace_filename(**kwargs)


# --- save_to_workspace: writes ------------------------------------------------


def test_save_text_writes_under_workspace(tmp_path: Path) -> None:
    result = save_to_workspace(str(tmp_path), "analysis", "report.csv", "a,b\n1,2\n")

    assert result.status == "saved"
    assert result.filename == "report.csv"
    assert result.relative_path == "analysis/report.csv"
    assert result.bytes_written == len(b"a,b\n1,2\n")
    saved = tmp_path / "analysis" / "report.csv"
    assert saved.read_text(encoding="utf-8") == "a,b\n1,2\n"


def test_save_bytes_writes_under_workspace(tmp_path: Path) -> None:
    payload = b"\x00\x01binary"
    result = save_to_workspace(str(tmp_path), "kpi", "measures.dax", payload)

    assert result.status == "saved"
    assert (tmp_path / "kpi" / "measures.dax").read_bytes() == payload
    assert result.bytes_written == len(payload)


def test_save_creates_only_requested_subfolder(tmp_path: Path) -> None:
    save_to_workspace(str(tmp_path), "recipes", "r.json", "{}")

    children = sorted(child.name for child in tmp_path.iterdir())
    assert children == ["recipes"]
    assert (tmp_path / "recipes").is_dir()


def test_save_blank_subfolder_writes_at_workspace_root(tmp_path: Path) -> None:
    result = save_to_workspace(str(tmp_path), "", "top.txt", "hi")

    assert result.status == "saved"
    assert result.relative_path == "top.txt"
    assert (tmp_path / "top.txt").read_text(encoding="utf-8") == "hi"


# --- save_to_workspace: safety / rejection ------------------------------------


def test_save_blank_workspace_root_is_invalid_noop(tmp_path: Path) -> None:
    result = save_to_workspace("   ", "analysis", "report.csv", "data")

    assert result.status == "invalid"
    assert result.message
    # Nothing was created anywhere.
    assert list(tmp_path.iterdir()) == []


def test_save_rejects_subfolder_traversal(tmp_path: Path) -> None:
    outside = tmp_path.parent / "escape_target"
    result = save_to_workspace(str(tmp_path / "ws"), "../escape_target", "x.txt", "data")

    assert result.status == "invalid"
    assert not outside.exists()


def test_save_rejects_absolute_subfolder(tmp_path: Path) -> None:
    result = save_to_workspace(str(tmp_path), "/etc", "x.txt", "data")
    assert result.status == "invalid"


def test_save_neutralizes_filename_traversal_and_stays_inside(tmp_path: Path) -> None:
    parent_file = tmp_path.parent / "passwd"
    result = save_to_workspace(str(tmp_path / "ws"), "analysis", "../../passwd", "data")

    assert result.status == "saved"
    # Traversal in the filename collapses to a basename inside the workspace.
    assert result.filename == "passwd"
    assert result.relative_path == "analysis/passwd"
    assert (tmp_path / "ws" / "analysis" / "passwd").is_file()
    assert not parent_file.exists()


# --- collision / overwrite ----------------------------------------------------


def test_save_does_not_overwrite_by_default(tmp_path: Path) -> None:
    first = save_to_workspace(str(tmp_path), "analysis", "report.csv", "original")
    second = save_to_workspace(str(tmp_path), "analysis", "report.csv", "new")

    assert first.filename == "report.csv"
    assert second.status == "saved"
    assert second.filename == "report-1.csv"
    assert second.relative_path == "analysis/report-1.csv"
    # Original content untouched.
    assert (tmp_path / "analysis" / "report.csv").read_text(encoding="utf-8") == "original"
    assert (tmp_path / "analysis" / "report-1.csv").read_text(encoding="utf-8") == "new"


def test_save_suffix_increments_on_repeated_collisions(tmp_path: Path) -> None:
    names = [save_to_workspace(str(tmp_path), "a", "f.txt", str(i)).filename for i in range(3)]
    assert names == ["f.txt", "f-1.txt", "f-2.txt"]


def test_save_overwrite_true_replaces_exact_target(tmp_path: Path) -> None:
    save_to_workspace(str(tmp_path), "analysis", "report.csv", "original")
    result = save_to_workspace(str(tmp_path), "analysis", "report.csv", "replaced", overwrite=True)

    assert result.status == "saved"
    assert result.filename == "report.csv"
    assert (tmp_path / "analysis" / "report.csv").read_text(encoding="utf-8") == "replaced"
    # No suffixed sibling was created.
    assert not (tmp_path / "analysis" / "report-1.csv").exists()


# --- result-field safety ------------------------------------------------------


def test_result_fields_are_basename_and_relative_only(tmp_path: Path) -> None:
    result = save_to_workspace(str(tmp_path), "analysis", "report.csv", "data")

    assert isinstance(result, WorkspaceSaveResult)
    absolute = str(tmp_path)
    assert absolute not in result.filename
    assert absolute not in result.relative_path
    assert absolute not in result.message
    # relative_path is workspace-relative (no drive/leading slash).
    assert not result.relative_path.startswith("/")
    assert ":" not in result.relative_path


# --- module safety: no export/PBI/pipeline/DB/manifest coupling ---------------


def test_module_imports_are_stdlib_only() -> None:
    """Guarantee no export/PBI/pipeline/DB/manifest/network coupling via imports.

    Scans import statements only (not prose), so the module cannot call
    ``export_csv``/``generate_package``/``create_manifest`` or open a database/
    socket without importing something outside the allowed stdlib set.
    """
    source = Path(workspace_save.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")

    allowed_top_level = {"__future__", "re", "dataclasses", "pathlib", "typing"}
    for module in modules:
        assert not module.startswith("data_quality_toolkit"), f"unexpected project import: {module}"
        assert module.split(".")[0] in allowed_top_level, f"unexpected import: {module}"
