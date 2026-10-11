"""Explicit confirmation of a processed dataset version.

Converts a successfully transformed preview into a durable, registered lifecycle
version: an immutable processed CSV, its deterministic recipe artifact, and one
lifecycle sidecar written **last** as the registration boundary.

Key contracts encoded here:

* ``confirmed`` is reported only after the final sidecar exists. No sidecar means
  the output is not a confirmed lifecycle version.
* Every final path is published by *exclusive creation*: an existing CSV, recipe,
  or sidecar is never replaced, truncated, or deleted, even when it appears after
  the linked-target reservation and before finalization.
* If the CSV (and possibly the recipe) becomes final but registration fails, the
  result is ``saved_unmanaged``: no authoritative record, no final sidecar.
* A location that cannot hard-link at all fails closed like any other error, but
  is reported as such: the operator is told why, that the output stays unmanaged,
  and that nothing was overwritten or deleted on their behalf.
* Durable references are workspace-relative POSIX paths; absolute paths never
  reach the record, display fields, or messages.
* Confirmation never activates: ``DATASET_CONTEXT`` stays the one active pointer
  and activation remains a separate, explicit user action.

The service imports neither Streamlit, UI pages, nor pandas — the caller passes
processed CSV *bytes*. The only file read is the active parent's source file, and
only to compute its exact content identity when that parent is legacy unmanaged.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any

from data_quality_toolkit.adapters.ui.services.confirmation_capability import (
    capability_guidance,
    is_hardlink_unsupported,
    safe_temp_label,
)
from data_quality_toolkit.adapters.ui.services.dataset_activation import (
    DatasetActivationError,
    validate_dataset_context,
)
from data_quality_toolkit.adapters.ui.services.dataset_versions import (
    SCHEMA_VERSION,
    CreationMechanism,
    DatasetFormat,
    DatasetVersionError,
    DatasetVersionRecord,
    ParentRef,
    RecipeRef,
    content_id_from_bytes,
    content_id_from_file,
    new_family_id,
    new_version_id,
    recipe_digest,
    to_mapping,
)
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    ManagedTrustRoot,
    TrustAuthority,
    resolve_trust_authority,
)
from data_quality_toolkit.adapters.ui.services.version_presentation import format_short_version
from data_quality_toolkit.adapters.ui.services.workspace_save import sanitize_filename
from data_quality_toolkit.adapters.ui.state.context import DatasetContext

__all__ = [
    "ConfirmationStatus",
    "ConfirmedVersionHandoff",
    "DatasetConfirmationResult",
    "confirm_processed_version",
    "resolve_confirmation_parent",
]

PREPROCESSED_SUBFOLDER = "preprocessed"
RECIPES_SUBFOLDER = "recipes"
SIDECAR_SUFFIX = ".dqtv.json"

_DEFAULT_STEM = "preprocessed_dataset"
_MAX_COLLISION_SUFFIX = 1000
# Mirrors the legacy compatibility identity: SHA-1 over the first megabyte only.
_DATASET_ID_CHUNK_BYTES = 1024 * 1024


# --- Result / handoff contracts -------------------------------------------


class ConfirmationStatus(Enum):
    """Outcome of a confirmation attempt."""

    CONFIRMED = "confirmed"
    SAVED_UNMANAGED = "saved_unmanaged"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class DatasetConfirmationResult:
    """Outcome of a confirmation, using display-safe path fields only.

    ``record`` is authoritative only when ``status`` is ``CONFIRMED``. ``csv_path``
    is a session-only absolute path kept for a later stat/activation; it is never
    displayed and never stored durably.

    ``capability_unsupported`` marks the one failure this service can diagnose
    precisely: the location cannot create hard links, so publication is
    impossible rather than merely unlucky. It never softens the outcome —
    ``status`` is still ``FAILED``. ``temp_artifact_labels`` then carries the
    display-safe basenames of staging files this attempt left behind for review;
    it is empty whenever ownership or safe labelling could not be proven.
    """

    status: ConfirmationStatus
    record: DatasetVersionRecord | None = None
    csv_relative_path: str = ""
    recipe_relative_path: str = ""
    sidecar_relative_path: str = ""
    csv_path: str = ""
    message: str = ""
    capability_unsupported: bool = False
    temp_artifact_labels: tuple[str, ...] = ()

    @property
    def confirmed(self) -> bool:
        """True only when a lifecycle version was fully registered."""
        return self.status is ConfirmationStatus.CONFIRMED


@dataclass(frozen=True, slots=True)
class ConfirmedVersionHandoff:
    """Session-only handoff for the most recently confirmed version.

    Carries just enough to display the confirmed identity and build a managed
    context for the explicit Set-active action. It is not an active pointer.
    """

    record: DatasetVersionRecord
    csv_path: str
    csv_relative_path: str

    @property
    def label(self) -> str:
        return self.record.label

    @property
    def version_id(self) -> str:
        return self.record.version_id

    @property
    def short_version_id(self) -> str:
        """The shared lifecycle short label, identical to the active surface's."""
        return format_short_version(self.record.version_id)


class _ConfirmationInputError(Exception):
    """Internal: a pre-write validation failure carrying a display-safe message."""


@dataclass(frozen=True, slots=True)
class _ConfirmationPlan:
    """Everything resolved before the first byte is written."""

    record: DatasetVersionRecord
    root_abs: Path
    csv_final: Path
    recipe_final: Path
    sidecar_final: Path
    csv_bytes: bytes
    recipe_bytes: bytes
    sidecar_bytes: bytes


# --- Identity helpers -----------------------------------------------------


def _dataset_id_from_bytes(data: bytes) -> str:
    """Return the legacy first-1-MB SHA-1 compatibility identity of ``data``.

    Mirrors ``adapters.loaders.file.csv_loader.dataset_id_from_file`` exactly
    (same algorithm, same 1 MB bound) while keeping this service pandas-free.
    """
    digest = hashlib.sha1(usedforsecurity=False)
    chunk = data[:_DATASET_ID_CHUNK_BYTES]
    if chunk:
        digest.update(chunk)
    return f"sha1:{digest.hexdigest()}"


def _canonical_json(payload: Any) -> bytes:
    """Serialize deterministically (key-sorted) as UTF-8 bytes."""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8")


def _is_within(target: Path, root_abs: Path) -> bool:
    try:
        target.resolve(strict=False).relative_to(root_abs)
        return True
    except ValueError:
        return False


def _relative_display(path: Path, root_abs: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(root_abs).as_posix()
    except ValueError:
        return path.name


def _safe_stem(raw: str | None) -> str:
    """Reduce any name to a safe, extension-free single filename segment."""
    text = str(raw or "").strip()
    stem = PurePosixPath(text.replace("\\", "/")).stem if text else ""
    return sanitize_filename(stem or _DEFAULT_STEM, default=_DEFAULT_STEM)


# --- Planning (validate + construct identities; writes nothing) -----------


def _build_lineage(parent: DatasetContext) -> tuple[str, str, ParentRef]:
    """Return ``(family_id, root_content_id, parent_ref)`` for the new version.

    A managed parent passes its family and root identities down and is referenced
    by version. An unmanaged parent starts a new family whose root is that
    parent's exact full-file content identity, and is referenced by content only.
    """
    if parent.managed:
        family_id, root_content_id = parent.family_id, parent.root_content_id
        version_id, content_id = parent.version_id, parent.content_id
        if not (family_id and root_content_id and version_id and content_id):
            raise _ConfirmationInputError("Active managed dataset is missing lifecycle identities.")
        return family_id, root_content_id, ParentRef(version_id=version_id, content_id=content_id)

    try:
        parent_content = content_id_from_file(Path(parent.source_path))
    except (OSError, RuntimeError) as exc:
        raise _ConfirmationInputError(
            "Active dataset file could not be read to identify the parent."
        ) from exc
    return new_family_id(), parent_content, ParentRef(version_id=None, content_id=parent_content)


# --- Root-first confirmation parent ---------------------------------------
#
# Confirmation lineage must descend from the *authoritative* active dataset. A
# valid managed trust root outranks whatever DatasetContext the caller passes
# in: a stale mirror or a manually entered path can never become the parent of
# a new lifecycle version. A managed-looking context with no valid trust fails
# closed rather than silently confirming against unverified lineage.

_MANAGED_TRUST_REQUIRED_MESSAGE = (
    "The managed dataset context is not backed by a valid managed trust root. "
    "Reopen the managed version explicitly before confirming."
)


def _context_from_trust_root(root: ManagedTrustRoot) -> DatasetContext:
    """Build the authoritative managed parent context from a valid trust root.

    Uses only the root's verified identities and its privacy-safe locator; no
    caller-supplied path, size, or lifecycle field participates.
    """
    return DatasetContext(
        source_path=root.locator.absolute_path,
        display_name=root.locator.display_name,
        size_bytes=root.size_bytes,
        modified_ns=root.modified_ns,
        large_file_mode=root.large_file_mode,
        managed=True,
        version_id=root.version_id,
        family_id=root.family_id,
        content_id=root.content_id,
        root_content_id=root.root_content_id,
        parent_version_id=root.parent_version_id,
        version_label=root.version_label,
    )


def resolve_confirmation_parent(
    session_state: Mapping[str, Any] | None,
    fallback_parent: DatasetContext | None,
) -> DatasetContext | None:
    """Resolve the confirmation parent root-first, failing closed on bad trust.

    Returns the trust-root-derived managed context when managed trust is valid,
    the caller's ``fallback_parent`` when no managed authority exists, and
    raises :class:`_ConfirmationInputError` when a managed-looking context has
    no valid trust behind it.
    """
    if session_state is None:
        return fallback_parent
    decision = resolve_trust_authority(dict(session_state))
    if decision.authority is TrustAuthority.FAIL_CLOSED:
        raise _ConfirmationInputError(_MANAGED_TRUST_REQUIRED_MESSAGE)
    if decision.managed and decision.root is not None:
        return _context_from_trust_root(decision.root)
    return fallback_parent


def _validate_inputs(
    workspace_root: str,
    csv_bytes: bytes,
    recipe: Mapping[str, Any],
    parent: DatasetContext | None,
    label: str,
) -> tuple[Path, str, DatasetContext]:
    """Validate every input before any write. Returns ``(root_abs, label, parent)``."""
    if not str(workspace_root or "").strip():
        raise _ConfirmationInputError("Enter a Workspace Root before confirming a version.")
    clean_label = str(label or "").strip()
    if not clean_label:
        raise _ConfirmationInputError("Enter a version label before confirming.")
    if not csv_bytes:
        raise _ConfirmationInputError("There is no processed data to confirm.")
    if not recipe:
        raise _ConfirmationInputError("Confirmation requires a non-empty recipe.")
    if parent is None:
        raise _ConfirmationInputError("Select an active dataset before confirming a version.")
    try:
        validate_dataset_context(parent)
    except DatasetActivationError as exc:
        raise _ConfirmationInputError(
            "The active dataset context is not valid for confirmation."
        ) from exc
    root_abs = Path(str(workspace_root).strip()).expanduser().resolve(strict=False)
    return root_abs, clean_label, parent


def _reserve_linked_targets(root_abs: Path, stem: str) -> tuple[Path, Path, Path]:
    """Reserve collision-free CSV/recipe/sidecar targets that share one stem.

    All three names stay linked: a suffix is only accepted when every target is
    simultaneously free, so an existing file is never overwritten and the trio can
    never drift apart.
    """
    for index in range(_MAX_COLLISION_SUFFIX + 1):
        candidate = stem if index == 0 else f"{stem}-{index}"
        csv_name = f"{candidate}.csv"
        targets = (
            root_abs / PREPROCESSED_SUBFOLDER / csv_name,
            root_abs / RECIPES_SUBFOLDER / f"{candidate}.json",
            root_abs / PREPROCESSED_SUBFOLDER / f"{csv_name}{SIDECAR_SUFFIX}",
        )
        if any(not _is_within(target, root_abs) for target in targets):
            raise _ConfirmationInputError("Resolved target is outside the Workspace Root.")
        if not any(target.exists() for target in targets):
            return targets
    raise _ConfirmationInputError("Too many existing versions with this name to confirm safely.")


def _plan_confirmation(
    *,
    workspace_root: str,
    csv_bytes: bytes,
    recipe: Mapping[str, Any],
    parent: DatasetContext | None,
    label: str,
    filename_stem: str | None,
    session_state: Mapping[str, Any] | None = None,
) -> _ConfirmationPlan:
    """Validate inputs and build every identity, path, and payload. Writes nothing."""
    effective_parent = resolve_confirmation_parent(session_state, parent)
    root_abs, clean_label, parent_ctx = _validate_inputs(
        workspace_root, csv_bytes, recipe, effective_parent, label
    )
    family_id, root_content_id, parent_ref = _build_lineage(parent_ctx)
    stem = _safe_stem(filename_stem or parent_ctx.display_name)
    csv_final, recipe_final, sidecar_final = _reserve_linked_targets(root_abs, stem)

    try:
        digest = recipe_digest(recipe)
    except (TypeError, ValueError) as exc:
        raise _ConfirmationInputError(
            "The recipe could not be serialized for confirmation."
        ) from exc

    try:
        record = DatasetVersionRecord(
            schema_version=SCHEMA_VERSION,
            version_id=new_version_id(),
            family_id=family_id,
            root_content_id=root_content_id,
            content_id=content_id_from_bytes(csv_bytes),
            dataset_id=_dataset_id_from_bytes(csv_bytes),
            label=clean_label,
            file_relative_path=_relative_display(csv_final, root_abs),
            format=DatasetFormat.CSV,
            size_bytes=len(csv_bytes),
            created_at=datetime.now(UTC),
            created_by=CreationMechanism.PREPROCESS_RECIPE,
            parent=parent_ref,
            recipe=RecipeRef(
                digest=digest, relative_path=_relative_display(recipe_final, root_abs)
            ),
        )
    except DatasetVersionError as exc:
        raise _ConfirmationInputError("The processed version failed lifecycle validation.") from exc

    return _ConfirmationPlan(
        record=record,
        root_abs=root_abs,
        csv_final=csv_final,
        recipe_final=recipe_final,
        sidecar_final=sidecar_final,
        csv_bytes=csv_bytes,
        recipe_bytes=_canonical_json(recipe),
        sidecar_bytes=_canonical_json(to_mapping(record)),
    )


# --- Durable write + registration -----------------------------------------


def _write_temp(final: Path, payload: bytes) -> Path:
    """Write ``payload`` to a flushed temp file beside its final destination."""
    final.parent.mkdir(parents=True, exist_ok=True)
    handle, raw = tempfile.mkstemp(dir=str(final.parent), prefix=f".{final.name}.", suffix=".tmp")
    tmp = Path(raw)
    with os.fdopen(handle, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return tmp


def _publish_exclusive(tmp: Path, final: Path) -> None:
    """Publish ``tmp``'s content at ``final``, but only if ``final`` is still free.

    ``os.link`` is the exclusive-creation primitive: the kernel either creates the
    new name atomically or fails with ``FileExistsError``. It cannot replace or
    truncate an existing file, which closes the reservation-to-finalization race —
    a competitor that claims the path after reservation keeps it, untouched.

    Both names address one inode, so the content is complete the instant the link
    exists; the temp name is swept later by the caller's cleanup. A filesystem
    without hard-link support raises ``OSError`` and is handled by the caller as a
    finalization failure — there is deliberately no overwrite-capable fallback.
    """
    os.link(tmp, final)


def _cleanup(paths: Iterable[Path]) -> None:
    """Remove leftover temp files best-effort, never masking the original failure."""
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            continue


def _failed(message: str) -> DatasetConfirmationResult:
    return DatasetConfirmationResult(status=ConfirmationStatus.FAILED, message=message)


def _retained_temp_labels(staged: Iterable[Path]) -> tuple[str, ...]:
    """Return display-safe basenames for the staging files still on disk.

    Ownership is already proven by construction: these are the exact paths this
    attempt created. Existence is re-checked so only artifacts that genuinely
    remain are named, and each name must still pass the display guard — an
    unexpected one is dropped rather than shown. Never raises and never touches
    the files.
    """
    labels: list[str] = []
    for path in staged:
        try:
            present = path.is_file()
        except OSError:
            continue
        if not present:
            continue
        label = safe_temp_label(path.name)
        if label and label not in labels:
            labels.append(label)
    return tuple(labels)


def _capability_unsupported(staged: Iterable[Path]) -> DatasetConfirmationResult:
    """Report a location that cannot hard-link, leaving every staging file alone.

    This is still a failure: no artifact was published, no record exists, and the
    processed output stays unmanaged. The one difference from a generic failure
    is that the cause is known exactly, so the operator gets actionable guidance
    — and the staging files survive for explicit review instead of being swept,
    because a swept artifact cannot be inspected.
    """
    labels = _retained_temp_labels(staged)
    return DatasetConfirmationResult(
        status=ConfirmationStatus.FAILED,
        message=capability_guidance(labels),
        capability_unsupported=True,
        temp_artifact_labels=labels,
    )


def _saved_unmanaged(plan: _ConfirmationPlan) -> DatasetConfirmationResult:
    """Report a durable but unregistered save: never authoritative, never active."""
    return DatasetConfirmationResult(
        status=ConfirmationStatus.SAVED_UNMANAGED,
        record=None,
        csv_relative_path=_relative_display(plan.csv_final, plan.root_abs),
        message=(
            "Files were saved, but lifecycle confirmation did not complete. "
            "This output is not a confirmed version."
        ),
    )


def _finalize(
    plan: _ConfirmationPlan, staged: tuple[Path, Path, Path]
) -> DatasetConfirmationResult:
    """Publish staged files, sidecar last as the registration boundary.

    Each step creates its final name exclusively, so a collision aborts the
    confirmation instead of overwriting the competing file.

    The first publish is also the only place a missing hard-link capability can
    be diagnosed honestly: nothing is durable yet, so "this location cannot
    publish" is the whole truth. Once the CSV exists the capability is proven to
    work, and any later failure keeps the established unmanaged-save contract.
    """
    csv_tmp, recipe_tmp, sidecar_tmp = staged
    try:
        _publish_exclusive(csv_tmp, plan.csv_final)
    except FileExistsError:
        return _failed("Another file already occupies the processed dataset target.")
    except OSError as exc:
        if is_hardlink_unsupported(exc):
            return _capability_unsupported(staged)
        return _failed("Could not write the processed dataset.")

    # The CSV is durable from here on: a later failure — a collision included — is
    # an unmanaged save, never a confirmation. Nothing is cleaned up here: exclusive
    # creation means no final sidecar of ours can exist, so any file at these paths
    # belongs to a competitor and must survive untouched.
    try:
        _publish_exclusive(recipe_tmp, plan.recipe_final)
        _publish_exclusive(sidecar_tmp, plan.sidecar_final)
    except OSError:
        return _saved_unmanaged(plan)

    return DatasetConfirmationResult(
        status=ConfirmationStatus.CONFIRMED,
        record=plan.record,
        csv_relative_path=_relative_display(plan.csv_final, plan.root_abs),
        recipe_relative_path=_relative_display(plan.recipe_final, plan.root_abs),
        sidecar_relative_path=_relative_display(plan.sidecar_final, plan.root_abs),
        csv_path=str(plan.csv_final),
        message=(
            f"Confirmed version {plan.record.label} "
            f"({format_short_version(plan.record.version_id)})."
        ),
    )


def _execute_plan(plan: _ConfirmationPlan) -> DatasetConfirmationResult:
    staged: list[Path] = []
    try:
        staged.append(_write_temp(plan.csv_final, plan.csv_bytes))
        staged.append(_write_temp(plan.recipe_final, plan.recipe_bytes))
        staged.append(_write_temp(plan.sidecar_final, plan.sidecar_bytes))
    except (OSError, RuntimeError):
        _cleanup(staged)
        return _failed("Could not stage the processed version for confirmation.")

    outcome: DatasetConfirmationResult | None = None
    try:
        outcome = _finalize(plan, (staged[0], staged[1], staged[2]))
        return outcome
    finally:
        # Publishing links rather than moves, so every temp still exists here —
        # after success and after failure alike. The single exception is a proven
        # missing hard-link capability: those staging files are the only evidence
        # of the attempt, and the operator was just told they were left behind.
        if outcome is None or not outcome.capability_unsupported:
            _cleanup(staged)


def confirm_processed_version(
    *,
    workspace_root: str,
    csv_bytes: bytes,
    recipe: Mapping[str, Any],
    parent: DatasetContext | None,
    label: str,
    filename_stem: str | None = None,
    session_state: Mapping[str, Any] | None = None,
) -> DatasetConfirmationResult:
    """Confirm a processed dataset version: immutable CSV + recipe + sidecar.

    Validates every input and constructs all identities before writing. Stages all
    three payloads to flushed temp files, then publishes the CSV, the recipe, and
    the sidecar — the sidecar last, as the registration boundary. Each publish is
    an exclusive create, so an existing file is never overwritten, truncated, or
    deleted, even if it appears after target reservation. Only a successful sidecar
    publish yields ``CONFIRMED``; a durable CSV without registration yields
    ``SAVED_UNMANAGED`` with no authoritative record and no final sidecar.
    Confirmation never changes the active dataset.

    When the location cannot create hard links at all, the result is ``FAILED``
    with ``capability_unsupported`` set: no fallback is attempted, and the
    staging files named by ``temp_artifact_labels`` are left in place for the
    operator to review rather than removed automatically.

    When ``session_state`` is supplied, the confirmation parent is resolved
    root-first: a valid managed trust root is authoritative over ``parent``, and
    a managed-looking context without valid trust fails closed. Omitting it
    preserves the legacy caller contract exactly.
    """
    try:
        plan = _plan_confirmation(
            workspace_root=workspace_root,
            csv_bytes=csv_bytes,
            recipe=recipe,
            parent=parent,
            label=label,
            filename_stem=filename_stem,
            session_state=session_state,
        )
    except _ConfirmationInputError as exc:
        return _failed(str(exc))
    return _execute_plan(plan)
