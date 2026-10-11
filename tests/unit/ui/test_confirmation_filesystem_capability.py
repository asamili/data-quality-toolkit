"""Confirmation on a filesystem that cannot create hard links (lifecycle H3).

``os.link`` is the only publication primitive confirmation may use, because it
is the only one that cannot overwrite, truncate, or replace an existing file.
Some locations — FAT32, exFAT, several network mounts — do not implement it at
all. These tests pin what the operator is told when that happens, and, just as
importantly, what the service refuses to do about it: no copy, no replace, no
delete-first, no registration, no activation, and no silent sweep of the
evidence.

Fault injection replaces ``os.link`` with the exact ``OSError`` shape the real
call raises, so recognition is exercised end to end rather than asserted against
a stub. The generic-failure and success contracts are re-pinned here too: a
permission error must *stay* generic, and nothing about a working confirmation
may shift.
"""

from __future__ import annotations

import errno
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from data_quality_toolkit.adapters.ui.pages.preprocess_studio import (
    _handle_confirmation_result,
)
from data_quality_toolkit.adapters.ui.services import dataset_confirmation
from data_quality_toolkit.adapters.ui.services.confirmation_capability import (
    capability_guidance,
    is_hardlink_unsupported,
    safe_temp_label,
)
from data_quality_toolkit.adapters.ui.services.dataset_confirmation import (
    SIDECAR_SUFFIX,
    ConfirmationStatus,
    ConfirmedVersionHandoff,
    confirm_processed_version,
)
from data_quality_toolkit.adapters.ui.services.dataset_versions import from_mapping
from data_quality_toolkit.adapters.ui.services.version_presentation import format_short_version
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT, PREP_CONFIRMED_VERSION

_CSV_BYTES = b"id,value\n1,10\n2,20\n"
_RECIPE: dict[str, Any] = {
    "schema_version": 1,
    "steps": [{"operation": "drop_duplicates", "columns": [], "parameters": {}}],
    "summary": {"before": {"row_count": 4}, "after": {"row_count": 3}},
}
_LABEL = "cleaned v2"

# A path that must never surface in guidance if it ever reached an exception.
_LEAKY_DETAIL = "C:\\Users\\secret\\workspace\\customers.csv"

# Drive-absolute or UNC prefix. Guidance is scanned for these rather than for a
# bare colon, which legitimately appears in the sentence punctuation.
_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:[\\/])|(?:\\\\)")


# --- fixtures / helpers ---------------------------------------------------


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _parent(tmp_path: Path) -> DatasetContext:
    src = tmp_path / "src" / "customers.csv"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(b"id,value\n1,10\n1,10\n2,20\n")
    stat = src.stat()
    return DatasetContext(
        source_path=str(src),
        display_name="customers.csv",
        size_bytes=int(stat.st_size),
        modified_ns=int(stat.st_mtime_ns),
    )


def _confirm(root: Path, parent: DatasetContext, **kwargs: Any) -> Any:
    return confirm_processed_version(
        workspace_root=str(root),
        csv_bytes=_CSV_BYTES,
        recipe=_RECIPE,
        parent=parent,
        label=_LABEL,
        filename_stem=parent.display_name,
        **kwargs,
    )


def _unsupported_error(detail: str = "hard links are not supported") -> OSError:
    """The error shape ``os.link`` raises where the capability is absent."""
    if sys.platform == "win32":
        # ERROR_INVALID_FUNCTION, as CreateHardLinkW reports FAT/exFAT volumes.
        return OSError(errno.EINVAL, detail, None, 1)
    return OSError(errno.EPERM, detail)


def _denied_error(detail: str = "permission denied") -> OSError:
    """A permission failure: fail-closed, but never a capability diagnosis."""
    if sys.platform == "win32":
        return OSError(errno.EACCES, detail, None, 5)  # ERROR_ACCESS_DENIED
    return OSError(errno.EACCES, detail)


def _patch_link(monkeypatch: pytest.MonkeyPatch, error: OSError) -> list[str]:
    """Make every publish attempt fail with ``error``; record the destinations."""
    calls: list[str] = []

    def fake(src: Any, dst: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(str(os.fspath(dst)))
        raise error

    monkeypatch.setattr(dataset_confirmation.os, "link", fake)
    return calls


def _forbid_fallbacks(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Trip on any overwrite-capable or destructive API the service might reach."""
    used: list[str] = []

    def trap(name: str) -> Any:
        def guard(*args: Any, **kwargs: Any) -> Any:
            used.append(name)
            raise AssertionError(f"forbidden fallback used: {name}")

        return guard

    for attribute in ("replace", "rename", "remove", "unlink", "symlink", "truncate"):
        if hasattr(dataset_confirmation.os, attribute):
            monkeypatch.setattr(dataset_confirmation.os, attribute, trap(f"os.{attribute}"))
    for attribute in ("replace", "rename", "unlink", "hardlink_to", "symlink_to", "write_bytes"):
        if hasattr(Path, attribute):
            monkeypatch.setattr(Path, attribute, trap(f"Path.{attribute}"))
    return used


def _tmp_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and p.name.endswith(".tmp"))


def _final_artifacts(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and not p.name.endswith(".tmp"))


class _FakeSt:
    """Minimal Streamlit recorder: keeps every call name and its arguments."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __getattr__(self, name: str) -> Any:
        def recorder(*args: Any, **kwargs: Any) -> None:
            self.calls.append((name, args))

        return recorder

    def texts(self, name: str) -> str:
        return " ".join(str(a) for call, args in self.calls if call == name for a in args)


# --- classification -------------------------------------------------------


def test_recognized_capability_errors_are_classified_as_unsupported() -> None:
    assert is_hardlink_unsupported(_unsupported_error()) is True
    if sys.platform == "win32":
        assert is_hardlink_unsupported(OSError(errno.EINVAL, "x", None, 50)) is True
    else:
        for code in ("ENOSYS", "ENOTSUP", "EOPNOTSUPP"):
            value = getattr(errno, code, None)
            if value is not None:
                assert is_hardlink_unsupported(OSError(value, "x")) is True


@pytest.mark.parametrize(
    "code",
    ["EACCES", "ENOSPC", "EXDEV", "EROFS", "EIO", "ENOENT", "EINVAL"],
)
def test_permission_and_io_errors_are_not_capability_failures(code: str) -> None:
    """The warning case: an ordinary failure must never be relabelled."""
    value = getattr(errno, code, None)
    if value is None:  # pragma: no cover - platform-dependent constant
        pytest.skip(f"{code} is not defined on this platform")
    assert is_hardlink_unsupported(OSError(value, "x")) is False


@pytest.mark.parametrize(
    "name",
    [
        "",
        "customers.csv",  # not a staging name
        "sub/.customers.csv.ab12.tmp",  # parent directory
        ".customers.csv.ab12.tmp\\extra",  # separator
        "C:/.customers.csv.ab12.tmp",  # drive
        "\\\\host\\share\\.x.tmp",  # UNC
        "file:///tmp/.x.tmp",  # URI
        "~/.customers.csv.ab12.tmp",  # home shorthand
        "." + "a" * 200 + ".tmp",  # unbounded length
    ],
)
def test_unsafe_temp_names_never_become_labels(name: str) -> None:
    assert safe_temp_label(name) == ""


def test_guidance_without_labels_stays_generic() -> None:
    message = capability_guidance(())
    assert "may remain in the workspace" in message
    assert "Nothing was deleted automatically" in message


# --- the capability failure end to end ------------------------------------


def test_unsupported_capability_yields_dedicated_safe_guidance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _patch_link(monkeypatch, _unsupported_error())

    result = _confirm(root, _parent(tmp_path))

    assert result.capability_unsupported is True
    message = result.message
    # Every point of the operator contract, in the operator's own terms.
    assert "Confirmation failed safely" in message
    assert "does not support the atomic hard-link publication" in message
    assert "remains unmanaged" in message
    assert "active managed version did not change" in message
    assert "no copy, overwrite, or replace fallback was attempted" in message
    assert "Nothing was deleted automatically" in message


def test_unsupported_capability_keeps_the_confirmation_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _patch_link(monkeypatch, _unsupported_error())

    result = _confirm(root, _parent(tmp_path))

    assert result.status is ConfirmationStatus.FAILED
    assert result.confirmed is False
    assert result.record is None
    # Nothing that could be mistaken for a durable reference is handed back.
    assert result.csv_relative_path == ""
    assert result.sidecar_relative_path == ""
    assert result.csv_path == ""


def test_unsupported_capability_leaves_the_output_unmanaged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _patch_link(monkeypatch, _unsupported_error())

    _confirm(root, _parent(tmp_path))

    # No CSV, no recipe, no sidecar: nothing was published, so nothing is managed.
    assert not (root / "preprocessed" / "customers.csv").exists()
    assert not (root / "recipes" / "customers.json").exists()
    assert not (root / "preprocessed" / f"customers.csv{SIDECAR_SUFFIX}").exists()
    assert _final_artifacts(root) == []


def test_unsupported_capability_changes_no_session_or_active_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    parent = _parent(tmp_path)
    session: dict[str, Any] = {DATASET_CONTEXT: parent, "unrelated": "kept"}
    before = dict(session)
    _patch_link(monkeypatch, _unsupported_error())

    _confirm(root, parent, session_state=session)

    assert session == before
    assert session[DATASET_CONTEXT] is parent


def test_unsupported_capability_attempts_no_fallback_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    parent = _parent(tmp_path)  # built before the traps: fixtures may write freely
    calls = _patch_link(monkeypatch, _unsupported_error())
    used = _forbid_fallbacks(monkeypatch)

    result = _confirm(root, parent)

    assert result.capability_unsupported is True
    assert used == []
    # Exactly one attempt, on the CSV target, and no retry with other semantics.
    assert len(calls) == 1
    assert calls[0].endswith("customers.csv")


def test_unsupported_capability_names_temp_artifacts_only_by_safe_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _patch_link(monkeypatch, _unsupported_error())

    result = _confirm(root, _parent(tmp_path))

    labels = result.temp_artifact_labels
    assert labels, "the staging files of this attempt must be identifiable"
    remaining = {p.name for p in _tmp_files(root)}
    for label in labels:
        # Proven to belong to this attempt, and safe to print as-is.
        assert label in remaining
        assert safe_temp_label(label) == label
        assert "/" not in label and "\\" not in label and ":" not in label
        assert "~" not in label and len(label) <= 160
        assert label in result.message


def test_unsupported_capability_guidance_exposes_no_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    parent = _parent(tmp_path)
    _patch_link(monkeypatch, _unsupported_error())

    result = _confirm(root, parent)

    assert str(tmp_path) not in result.message
    assert str(root) not in result.message
    assert parent.source_path not in result.message
    assert _ABSOLUTE_PATH.search(result.message) is None


def test_unsupported_capability_never_shows_raw_exception_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _patch_link(monkeypatch, _unsupported_error(f"link failed on {_LEAKY_DETAIL}"))

    result = _confirm(root, _parent(tmp_path))

    assert _LEAKY_DETAIL not in result.message
    assert "link failed" not in result.message
    assert "OSError" not in result.message
    assert "Traceback" not in result.message


def test_unsupported_capability_deletes_nothing_automatically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _patch_link(monkeypatch, _unsupported_error())

    result = _confirm(root, _parent(tmp_path))

    remaining = _tmp_files(root)
    # All three staged payloads survive for review, byte-for-byte.
    assert len(remaining) == 3
    assert (root / "preprocessed").is_dir()
    for path in remaining:
        assert path.stat().st_size > 0
    assert set(result.temp_artifact_labels) <= {p.name for p in remaining}


# --- unknown failures keep the established behavior -----------------------


def test_unknown_oserror_keeps_the_generic_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _patch_link(monkeypatch, _denied_error())

    result = _confirm(root, _parent(tmp_path))

    assert result.status is ConfirmationStatus.FAILED
    assert result.capability_unsupported is False
    assert result.temp_artifact_labels == ()
    assert result.message == "Could not write the processed dataset."
    assert "hard-link" not in result.message


def test_unknown_oserror_still_sweeps_its_staging_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retention is specific to the capability diagnosis, not to failure at large."""
    root = _workspace(tmp_path)
    _patch_link(monkeypatch, _denied_error())

    _confirm(root, _parent(tmp_path))

    assert _tmp_files(root) == []


# --- success and prior-phase regressions ----------------------------------


def test_successful_confirmation_is_unchanged(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    result = _confirm(root, _parent(tmp_path))

    assert result.status is ConfirmationStatus.CONFIRMED
    assert result.capability_unsupported is False
    assert result.temp_artifact_labels == ()
    assert result.csv_relative_path == "preprocessed/customers.csv"
    assert (root / "preprocessed" / "customers.csv").read_bytes() == _CSV_BYTES
    assert (root / "recipes" / "customers.json").is_file()
    assert (root / "preprocessed" / f"customers.csv{SIDECAR_SUFFIX}").is_file()
    assert _tmp_files(root) == []


def test_h1_record_invariants_and_h2_short_version_are_unchanged(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    result = _confirm(root, _parent(tmp_path))

    record = result.record
    assert record is not None
    # H1: the sidecar remains the authoritative, round-trippable record.
    sidecar = (root / "preprocessed" / f"customers.csv{SIDECAR_SUFFIX}").read_text(encoding="utf-8")
    assert from_mapping(json.loads(sidecar)) == record
    # H2: one shared short-version spelling across message and handoff.
    short = format_short_version(record.version_id)
    assert short in result.message
    handoff = ConfirmedVersionHandoff(
        record=record, csv_path=result.csv_path, csv_relative_path=result.csv_relative_path
    )
    assert handoff.short_version_id == short


# --- confirmation UI surface ----------------------------------------------


def test_ui_labels_a_capability_failure_distinctly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _patch_link(monkeypatch, _unsupported_error())
    result = _confirm(root, _parent(tmp_path))
    st = _FakeSt()
    state: dict[str, Any] = {}

    _handle_confirmation_result(st, state, result)

    errors = st.texts("error")
    assert "Confirmation not supported here" in errors
    assert "Confirmation failed safely" in errors
    assert "Nothing was deleted automatically" in errors
    # Failure is never dressed up as a success or a warning.
    assert not st.texts("success")
    assert not st.texts("warning")
    assert _ABSOLUTE_PATH.search(errors) is None


def test_ui_capability_failure_drops_any_earlier_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    confirmed = _confirm(root, _parent(tmp_path))
    assert confirmed.record is not None
    state: dict[str, Any] = {
        PREP_CONFIRMED_VERSION: ConfirmedVersionHandoff(
            record=confirmed.record,
            csv_path=confirmed.csv_path,
            csv_relative_path=confirmed.csv_relative_path,
        )
    }
    _patch_link(monkeypatch, _unsupported_error())
    failure = _confirm(_workspace(tmp_path / "other"), _parent(tmp_path))

    _handle_confirmation_result(_FakeSt(), state, failure)

    # No stale handoff may survive to offer activation after a failure.
    assert PREP_CONFIRMED_VERSION not in state


def test_ui_generic_failure_label_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _patch_link(monkeypatch, _denied_error())
    result = _confirm(root, _parent(tmp_path))
    st = _FakeSt()

    _handle_confirmation_result(st, {}, result)

    errors = st.texts("error")
    assert "Confirmation error" in errors
    assert "Confirmation not supported here" not in errors
