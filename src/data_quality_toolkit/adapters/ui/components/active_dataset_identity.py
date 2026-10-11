"""Shared, deterministic presentation of the active dataset's identity.

One presentation model, derived purely from the active ``DatasetContext``, so every
lifecycle-aware page describes the active dataset with identical terminology. The
module imports neither Streamlit nor pandas and performs no IO: it never stats or
opens a file, reads a sidecar, recomputes a hash, or touches session state.

Presentation contracts encoded here:

* A managed lifecycle version and a legacy unmanaged dataset are always visibly
  distinct, and legacy is a normal state — never an error.
* Display is basename-first. Absolute paths, workspace paths, and recipe paths
  never reach a field of the model, so they cannot reach a page.
* Only a *shortened* version id is presented (``v-`` plus the first eight
  hexadecimal characters), formatted by the shared lifecycle formatter so this
  surface and the newly-confirmed surface spell one identity identically. The
  full UUID, ``content_id``, ``family_id``, ``root_content_id``,
  ``parent_version_id``, and the compatibility ``dataset_id`` are deliberately
  absent — they are identity, not page labels.
* Presentation never reinterprets identity: a malformed or missing version id
  degrades to a neutral managed label rather than raising or exposing a path.
* ``confirmed`` and ``active`` stay separate concepts. This model describes only
  the *active* dataset; a newly confirmed version is a different surface.
"""

from __future__ import annotations

from dataclasses import dataclass

from data_quality_toolkit.adapters.ui.components.source_hub import (
    PATH_REDACTED_DISPLAY,
    basename_first_display,
)
from data_quality_toolkit.adapters.ui.services.version_presentation import (
    SHORT_VERSION_PREFIX,
    format_short_version,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext

__all__ = [
    "FULL_ANALYSIS_MODE",
    "LARGE_FILE_MODE",
    "LEGACY_FALLBACK_LABEL",
    "LEGACY_STATUS",
    "MANAGED_FALLBACK_LABEL",
    "MANAGED_STATUS",
    "SHORT_VERSION_PREFIX",
    "ActiveDatasetIdentity",
    "build_active_dataset_identity",
    "short_version_id",
]

# Shared vocabulary. Both rendering surfaces use these exact terms.
MANAGED_STATUS = "Managed version"
LEGACY_STATUS = "Legacy dataset"
MANAGED_FALLBACK_LABEL = "Managed dataset"
LEGACY_FALLBACK_LABEL = "Dataset selected"

# Lowercase canonical mode wording; callers capitalize for block-style surfaces.
FULL_ANALYSIS_MODE = "full analysis mode"
LARGE_FILE_MODE = "large-file profile mode"

# The one shared lifecycle formatter, re-exported under this module's historical
# name. It is the same object, not a copy: this surface and the newly-confirmed
# surface therefore cannot drift apart, and existing callers keep working.
short_version_id = format_short_version


@dataclass(frozen=True, slots=True)
class ActiveDatasetIdentity:
    """Immutable, display-safe identity of the active dataset.

    Every field is safe to render as-is. There is no absolute path, no full hash,
    and no full UUID here by construction, so a renderer cannot leak one.
    """

    managed: bool
    status: str
    label: str
    basename: str
    mode_label: str
    short_version_id: str = ""

    @property
    def show_basename(self) -> bool:
        """True when the basename distinguishes the file from the primary label.

        A legacy dataset is usually labelled by its own basename; repeating it
        would be noise, so it is only offered when it actually adds information.
        """
        return bool(self.basename) and self.basename != self.label

    @property
    def descriptor(self) -> str:
        """Status plus short version, e.g. ``Managed version v-1a2b3c4d``.

        Falls back to the bare status when no usable version id exists, which is
        always true for a legacy dataset and is the safe degradation for a managed
        context whose version id is malformed.
        """
        if self.managed and self.short_version_id:
            return f"{self.status} {self.short_version_id}"
        return self.status


def _safe_display(value: str | None) -> str:
    """Reduce any candidate to a display-safe basename, or ``""`` if unusable.

    Every candidate is reduced, including the operator-typed version label: a label
    is free text, so it could itself contain a path. Privacy wins over fidelity —
    a label containing a separator is shortened to its last segment.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    display = basename_first_display(text, fallback="")
    return "" if display == PATH_REDACTED_DISPLAY else display


def _primary_label(candidates: tuple[str, ...], basename: str, *, managed: bool) -> str:
    """Resolve the operator-facing label from candidates in priority order."""
    for candidate in candidates:
        label = _safe_display(candidate)
        if label:
            return label
    if basename:
        return basename
    return MANAGED_FALLBACK_LABEL if managed else LEGACY_FALLBACK_LABEL


def _flag(context: DatasetContext, name: str) -> bool:
    """Read a boolean context field, defaulting to legacy semantics when absent."""
    return bool(getattr(context, name, False))


def _text(context: DatasetContext, name: str) -> str:
    """Read a string context field as text, treating absent/``None`` as empty."""
    value = getattr(context, name, "")
    return value if isinstance(value, str) else ""


def build_active_dataset_identity(context: DatasetContext) -> ActiveDatasetIdentity:
    """Derive the display-safe identity of the active dataset context.

    Pure and read-only: it reads only fields already present on ``context``.
    A managed context contributes a shortened version id; a legacy context never
    does, because it carries no lifecycle identities to shorten.

    Fields are read defensively because lifecycle attributes are additive on
    ``DatasetContext`` and default to legacy semantics. A minimal context that
    predates them therefore presents as a legacy dataset instead of raising —
    presentation must never be the thing that breaks a page.
    """
    managed = _flag(context, "managed")
    basename = _safe_display(_text(context, "source_path"))
    display_name = _text(context, "display_name")
    candidates = (_text(context, "version_label"), display_name) if managed else (display_name,)
    return ActiveDatasetIdentity(
        managed=managed,
        status=MANAGED_STATUS if managed else LEGACY_STATUS,
        label=_primary_label(candidates, basename, managed=managed),
        basename=basename,
        mode_label=LARGE_FILE_MODE if _flag(context, "large_file_mode") else FULL_ANALYSIS_MODE,
        short_version_id=short_version_id(_text(context, "version_id")) if managed else "",
    )
