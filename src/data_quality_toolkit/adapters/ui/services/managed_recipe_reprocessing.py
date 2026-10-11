"""Trusted reload and reprocessing of a confirmed managed recipe.

This UI-private service is the one place a durable, confirmed recipe may be
reloaded, revalidated, edited as a detached draft, and reprocessed into a new
immutable child version. It owns four explicit keyword-only entry points:

* :func:`load_confirmed_recipe` — one fresh bounded managed-version discovery,
  unique-reference resolution, independent sidecar/CSV/recipe revalidation,
  bounded UTF-8 JSON parsing, envelope and digest verification, and a deeply
  immutable step view. It writes nothing and activates nothing.
* :func:`create_recipe_draft` — a deeply detached mutable copy of the loaded
  steps; editing the draft can never reach the immutable load or the durable
  recipe bytes.
* :func:`revalidate_durable_recipe` — strict admission of exactly twelve
  supported durable operations, with no durable read, no write, and no session
  mutation.
* :func:`confirm_reprocessed_child` — revalidation and replay-evidence
  verification before any durable work, then one immutable child published
  through the accepted confirmation boundary. Every reachable durable failure
  restores the exact pre-call workspace state and never reports an unmanaged
  save. Authored steps alone are never enough to confirm a child: this service,
  not any page, is what refuses a failed or incomplete replay.

None of the four mutates session state, activates a dataset, or propagates an
exception: hostile input yields a typed failure with a fixed, privacy-safe
reason code and message. Activation of a confirmed child remains a separate,
explicit operator action owned by the accepted reopen path.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat as stat_module
import uuid
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from data_quality_toolkit.adapters.ui.services.dataset_confirmation import (
    ConfirmationStatus,
    _safe_stem,
    confirm_processed_version,
)
from data_quality_toolkit.adapters.ui.services.dataset_discovery import (
    DiscoveredVersion,
    DiscoveryResult,
    RootStatus,
    discover_managed_versions,
)
from data_quality_toolkit.adapters.ui.services.dataset_versions import (
    DatasetVersionRecord,
    content_id_from_file,
    recipe_digest,
)
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    TrustAuthority,
    resolve_trust_authority,
)

# The replay-success predicate and the generated-destination naming rules are
# imported from the one engine that produces them, so the normal and reprocessed
# confirmation paths - and admission and execution - cannot drift apart.
from data_quality_toolkit.adapters.ui.services.preprocessing import (
    deterministic_output_names,
    replay_refusal_code,
)

# The operator-facing operation vocabularies below are imported from their one
# owning engine module rather than restated here: admission must reject exactly
# what the engine would clamp, normalize, ignore, or skip, so a second copy of
# these values would be a correctness defect the moment the engine changed.
from data_quality_toolkit.adapters.ui.services.preprocessing_calculations import (
    _ARITHMETIC_OPS,
    _COMPARATORS,
    _ORDERED_COMPARATORS,
    _POWER_CONSTANT_ROLES,
    _SCALAR_OPS,
    _STRING_OPS,
    MAX_BINS,
    MIN_BINS,
    OP_CALC_ARITHMETIC,
    OP_CALC_BINNING,
    OP_CALC_CONDITIONAL,
    OP_CALC_SCALAR,
    OP_CALC_STRING,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.application.workflow.preprocessing import (
    OP_DERIVED,
    OP_DROP_DUPLICATES,
    OP_ENCODING,
    OP_MISSING,
    OP_OUTLIER,
    OP_SCALING,
    OP_TYPE_CAST,
    OUTPUT_COLLISION,
    RECIPE_SCHEMA_VERSION,
    STATUS_APPLIED,
    STATUS_PENDING,
    STATUS_SKIPPED,
    output_collisions,
    recipe_to_json_payload,
)
from data_quality_toolkit.shared.managed_export_source import MANAGED_FULL_MAX_SOURCE_BYTES

__all__ = [
    "ADMITTED_OPERATIONS",
    "STATUS_ADMITTED",
    "STATUS_CONFIRMED",
    "STATUS_DRAFTED",
    "STATUS_FAILED",
    "STATUS_LOADED",
    "STATUS_REJECTED",
    "LoadedRecipe",
    "RecipeAdmission",
    "RecipeDraft",
    "ReprocessedChild",
    "confirm_reprocessed_child",
    "create_recipe_draft",
    "derive_action_reference",
    "load_confirmed_recipe",
    "revalidate_durable_recipe",
]

# --- Fixed statuses and generic, privacy-safe messages ----------------------

STATUS_LOADED = "loaded"
STATUS_DRAFTED = "drafted"
STATUS_ADMITTED = "admitted"
STATUS_CONFIRMED = "confirmed"
STATUS_REJECTED = "rejected"
STATUS_FAILED = "failed"

# Every message is a literal chosen at authoring time. No message interpolates a
# path, filename, identifier, hash, column name, or parameter value.
_STATUS_MESSAGES: dict[str, str] = {
    STATUS_LOADED: "The confirmed recipe was loaded and revalidated.",
    STATUS_DRAFTED: "An editable draft of the confirmed recipe was created.",
    STATUS_ADMITTED: "Every recipe step was admitted.",
    STATUS_CONFIRMED: "A new child version was confirmed. It is not active.",
    STATUS_REJECTED: "A recipe step was refused and nothing was reprocessed.",
    STATUS_FAILED: "The confirmed recipe could not be reused.",
}

# --- Bounds ----------------------------------------------------------------

_MAX_RECIPE_BYTES = 1_048_576
_MAX_SOURCE_BYTES = MANAGED_FULL_MAX_SOURCE_BYTES
_MAX_STEPS = 200
_MAX_COLUMNS_PER_STEP = 512
_MAX_PARAMETERS_PER_STEP = 32
_MAX_LABEL_CHARS = 200
_MAX_CARDINALITY_CEILING = 10_000

# Accepted collision-safe short-id shape produced by discovery: ``v-`` + 8 hex,
# prefix-expanded to 12 hex, with an optional ordinal suffix. Anything else —
# including anything path-like — fails closed before any filesystem access.
_REFERENCE_RE = re.compile(r"^v-[0-9a-f]{8}(?:[0-9a-f]{4})?(?:-[0-9]{1,6})?$")

_ARTIFACT_OK = "ARTIFACT_OK"
_ENVELOPE_KEYS = frozenset({"schema_version", "steps", "summary"})


# --- Deep freezing / detaching ----------------------------------------------


def _freeze(value: Any) -> Any:
    """Return a deeply immutable view of a JSON-shaped value.

    A frozen array and a frozen object stay distinct types at every depth,
    including empty containers: a list becomes a ``tuple`` and a mapping becomes
    a ``MappingProxyType`` over a private dict that no caller can reach.
    """
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    """Return a deeply detached mutable copy of a frozen or plain value."""
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_thaw(item) for item in value]
    return value


# --- Public result contracts -------------------------------------------------


@dataclass(frozen=True, slots=True)
class LoadedRecipe:
    """Outcome of loading one confirmed, revalidated durable recipe.

    ``steps`` and ``envelope`` are deeply immutable; ``record`` is the durable
    version record the recipe is registered against and is machine-side only.
    """

    status: str
    reason_code: str
    message: str
    action_reference: str
    steps: tuple[Any, ...]
    envelope: Mapping[str, Any] | None
    record: DatasetVersionRecord | None

    @property
    def loaded(self) -> bool:
        """True only when a confirmed recipe was fully revalidated."""
        return self.status == STATUS_LOADED


@dataclass(frozen=True, slots=True)
class RecipeDraft:
    """A mutable, deeply detached draft of a loaded recipe."""

    status: str
    reason_code: str
    message: str
    steps: list[dict[str, Any]]
    record: DatasetVersionRecord | None

    @property
    def drafted(self) -> bool:
        """True only when a detached editable draft was produced."""
        return self.status == STATUS_DRAFTED


@dataclass(frozen=True, slots=True)
class RecipeAdmission:
    """Outcome of strict durable-recipe admission.

    ``step_index`` is the zero-based index of the refused step, or ``-1`` when
    the refusal is not step-specific.
    """

    status: str
    reason_code: str
    message: str
    step_index: int
    operations: tuple[str, ...]

    @property
    def admitted(self) -> bool:
        """True only when every step was admitted."""
        return self.status == STATUS_ADMITTED


@dataclass(frozen=True, slots=True)
class ReprocessedChild:
    """Outcome of confirming one immutable reprocessed child version."""

    status: str
    reason_code: str
    message: str
    record: DatasetVersionRecord | None
    recipe: Mapping[str, Any] | None
    csv_relative_path: str
    recipe_relative_path: str
    sidecar_relative_path: str

    @property
    def confirmed(self) -> bool:
        """True only when exactly one immutable child was registered."""
        return self.status == STATUS_CONFIRMED


def _load_failure(reason_code: str) -> LoadedRecipe:
    return LoadedRecipe(
        status=STATUS_FAILED,
        reason_code=reason_code,
        message=_STATUS_MESSAGES[STATUS_FAILED],
        action_reference="",
        steps=(),
        envelope=None,
        record=None,
    )


def _draft_failure(reason_code: str) -> RecipeDraft:
    return RecipeDraft(
        status=STATUS_FAILED,
        reason_code=reason_code,
        message=_STATUS_MESSAGES[STATUS_FAILED],
        steps=[],
        record=None,
    )


def _admission_failure(reason_code: str, step_index: int) -> RecipeAdmission:
    return RecipeAdmission(
        status=STATUS_REJECTED,
        reason_code=reason_code,
        message=_STATUS_MESSAGES[STATUS_REJECTED],
        step_index=step_index,
        operations=(),
    )


def _child_failure(reason_code: str) -> ReprocessedChild:
    return ReprocessedChild(
        status=STATUS_FAILED,
        reason_code=reason_code,
        message=_STATUS_MESSAGES[STATUS_FAILED],
        record=None,
        recipe=None,
        csv_relative_path="",
        recipe_relative_path="",
        sidecar_relative_path="",
    )


# --- Shared input guards ------------------------------------------------------


def _guard_common(session_state: Any, workspace_root: Any) -> str:
    """Reject hostile session-state / workspace-root inputs before any work."""
    if not isinstance(session_state, Mapping):
        return "SESSION_STATE_INVALID"
    if not isinstance(workspace_root, str):
        return "WORKSPACE_ROOT_INVALID"
    if not workspace_root.strip():
        return "WORKSPACE_ROOT_BLANK"
    return ""


def derive_action_reference(*, version_id: str) -> str:
    """Return the privacy-safe action reference discovery projects for a version.

    Mirrors the accepted short-id projection (``v-`` plus the first eight hex
    digits). A collision-expanded reference simply will not resolve, which fails
    closed rather than selecting a different version.
    """
    try:
        return "v-" + uuid.UUID(str(version_id)).hex[:8]
    except (AttributeError, TypeError, ValueError):
        return ""


# --- Path confinement helpers -------------------------------------------------


def _is_confined(target: Path, root: Path) -> bool:
    target_norm = os.path.normcase(str(target))
    root_norm = os.path.normcase(str(root))
    try:
        return os.path.commonpath([target_norm, root_norm]) == root_norm
    except ValueError:
        return False


def _resolve_root_dir(root_raw: str) -> Path | None:
    try:
        resolved = Path(root_raw).expanduser().resolve(strict=True)
        st = resolved.stat()
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved if stat_module.S_ISDIR(st.st_mode) else None


def _resolve_confined(root_abs: Path, relative_posix: str) -> tuple[Path | None, str]:
    """Strictly resolve a workspace-relative artifact and prove it is a file."""
    try:
        lexical = root_abs.joinpath(*PurePosixPath(relative_posix).parts)
        resolved = lexical.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None, "MISSING"
    if not _is_confined(resolved, root_abs):
        return None, "ESCAPES_ROOT"
    try:
        st = resolved.stat()
    except OSError:
        return None, "UNREADABLE"
    if not stat_module.S_ISREG(st.st_mode):
        return None, "NOT_REGULAR"
    return resolved, ""


def _confined_regular(
    root_abs: Path, relative_posix: str, expected_resolved: str | None
) -> tuple[Path | None, str]:
    """Resolve an artifact and prove it is still the canonical target discovery saw."""
    resolved, code = _resolve_confined(root_abs, relative_posix)
    if resolved is None:
        return None, code
    if expected_resolved is None:
        return None, "REPLACED"
    if os.path.normcase(str(resolved)) != os.path.normcase(expected_resolved):
        return None, "REPLACED"
    return resolved, ""


# --- Fresh discovery + unique resolution --------------------------------------


def _fresh_discovery(root_raw: str) -> tuple[DiscoveryResult | None, str]:
    """Run exactly one fresh bounded discovery for this load; fail closed."""
    try:
        result = discover_managed_versions(root_raw)
    except Exception:
        return None, "DISCOVERY_FAILED"
    if result.root_status is not RootStatus.OK:
        return None, "DISCOVERY_NOT_SAFE"
    if not result.result_complete:
        return None, "DISCOVERY_NOT_SAFE"
    if not result.reopen_safe:
        return None, "DISCOVERY_NOT_SAFE"
    return result, ""


def _resolve_unique(
    result: DiscoveryResult, reference: str
) -> tuple[DiscoveredVersion | None, str]:
    """Resolve the reference to exactly one valid, non-duplicate record."""
    for group in result.duplicates:
        if group.short_version_id == reference:
            return None, "REFERENCE_AMBIGUOUS"
    matches = [
        version for version in result.versions if version.display.short_version_id == reference
    ]
    if not matches:
        return None, "REFERENCE_NOT_FOUND"
    if len(matches) > 1:
        return None, "REFERENCE_AMBIGUOUS"
    version = matches[0]
    if version.csv_status != _ARTIFACT_OK:
        return None, "RECORD_NOT_VALID"
    if version.record.recipe is None:
        return None, "RECIPE_ABSENT"
    if version.recipe_status != _ARTIFACT_OK:
        return None, "RECIPE_UNAVAILABLE"
    return version, ""


# --- Independent artifact revalidation ----------------------------------------


def _verify_source_identity(root_abs: Path, version: DiscoveredVersion) -> str:
    """Prove the registered source bytes are still exactly the recorded ones."""
    record = version.record
    resolved, code = _confined_regular(
        root_abs, record.file_relative_path, version.locator.csv_resolved_path
    )
    if resolved is None:
        return "SOURCE_" + code
    try:
        st = resolved.stat()
    except OSError:
        return "SOURCE_UNREADABLE"
    if int(st.st_size) > _MAX_SOURCE_BYTES:
        return "SOURCE_TOO_LARGE"
    if int(st.st_size) != record.size_bytes:
        return "SOURCE_MISMATCH"
    if record.mtime_ns is not None and int(st.st_mtime_ns) != record.mtime_ns:
        return "SOURCE_MISMATCH"
    try:
        actual = content_id_from_file(resolved)
    except (OSError, RuntimeError):
        return "SOURCE_UNREADABLE"
    return "" if actual == record.content_id else "SOURCE_MISMATCH"


def _revalidate_artifacts(root_abs: Path, version: DiscoveredVersion) -> tuple[Path | None, str]:
    """Revalidate sidecar, source, and recipe confinement and regular-file status."""
    locator = version.locator
    sidecar, code = _confined_regular(
        root_abs, locator.sidecar_relative_posix, locator.sidecar_resolved_path
    )
    if sidecar is None:
        return None, "SIDECAR_" + code
    source_code = _verify_source_identity(root_abs, version)
    if source_code:
        return None, source_code
    recipe_ref = version.record.recipe
    if recipe_ref is None:
        return None, "RECIPE_ABSENT"
    recipe, code = _confined_regular(
        root_abs, recipe_ref.relative_path, locator.recipe_resolved_path
    )
    if recipe is None:
        return None, "RECIPE_" + code
    return recipe, ""


# --- Bounded recipe reading, envelope, and digest ------------------------------


def _read_recipe_bytes(recipe_path: Path) -> tuple[bytes | None, str]:
    try:
        st = recipe_path.stat()
    except OSError:
        return None, "RECIPE_UNREADABLE"
    if int(st.st_size) > _MAX_RECIPE_BYTES:
        return None, "RECIPE_OVERSIZE"
    try:
        with open(recipe_path, "rb") as handle:
            data = handle.read(_MAX_RECIPE_BYTES + 1)
    except OSError:
        return None, "RECIPE_UNREADABLE"
    if len(data) > _MAX_RECIPE_BYTES:
        return None, "RECIPE_OVERSIZE"
    if not data:
        return None, "RECIPE_EMPTY"
    return data, ""


def _parse_recipe(data: bytes) -> tuple[dict[str, Any] | None, str]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, "RECIPE_ENCODING_INVALID"
    try:
        payload = json.loads(text)
    except (RecursionError, ValueError):
        return None, "RECIPE_JSON_INVALID"
    if not isinstance(payload, dict):
        return None, "RECIPE_ENVELOPE_UNSUPPORTED"
    return payload, ""


def _verify_envelope(payload: Mapping[str, Any], record: DatasetVersionRecord) -> str:
    """Check the envelope first, then the registered digest, independently.

    An unsupported envelope is refused on its own terms even when its digest
    matches, and a supported envelope with a foreign digest is refused as a
    digest mismatch — the two failures never stand in for one another.
    """
    if payload.get("schema_version") != RECIPE_SCHEMA_VERSION:
        return "RECIPE_ENVELOPE_UNSUPPORTED"
    if not isinstance(payload.get("steps"), list):
        return "RECIPE_ENVELOPE_UNSUPPORTED"
    if not set(map(str, payload)).issubset(_ENVELOPE_KEYS):
        return "RECIPE_ENVELOPE_UNSUPPORTED"
    recipe_ref = record.recipe
    if recipe_ref is None:
        return "RECIPE_ABSENT"
    try:
        digest = recipe_digest(payload)
    except (TypeError, ValueError):
        return "RECIPE_DIGEST_UNCOMPUTABLE"
    return "" if digest == recipe_ref.digest else "RECIPE_DIGEST_MISMATCH"


def _load_envelope(
    recipe_path: Path, record: DatasetVersionRecord
) -> tuple[dict[str, Any] | None, str]:
    data, code = _read_recipe_bytes(recipe_path)
    if data is None:
        return None, code
    payload, code = _parse_recipe(data)
    if payload is None:
        return None, code
    code = _verify_envelope(payload, record)
    if code:
        return None, code
    return payload, ""


# --- load_confirmed_recipe ----------------------------------------------------


def _loaded(
    record: DatasetVersionRecord, payload: Mapping[str, Any], reference: str
) -> LoadedRecipe:
    frozen = _freeze(payload)
    return LoadedRecipe(
        status=STATUS_LOADED,
        reason_code="LOADED",
        message=_STATUS_MESSAGES[STATUS_LOADED],
        action_reference=reference,
        steps=tuple(frozen["steps"]),
        envelope=frozen,
        record=record,
    )


def _guard_load_inputs(session_state: Any, workspace_root: Any, action_reference: Any) -> str:
    code = _guard_common(session_state, workspace_root)
    if code:
        return code
    if not isinstance(action_reference, str):
        return "REFERENCE_INVALID"
    if _REFERENCE_RE.match(action_reference) is None:
        return "REFERENCE_MALFORMED"
    return ""


def _run_load(session_state: Any, workspace_root: Any, action_reference: Any) -> LoadedRecipe:
    code = _guard_load_inputs(session_state, workspace_root, action_reference)
    if code:
        return _load_failure(code)
    root_raw = str(workspace_root).strip()
    result, code = _fresh_discovery(root_raw)
    if result is None:
        return _load_failure(code)
    version, code = _resolve_unique(result, str(action_reference))
    if version is None:
        return _load_failure(code)
    root_abs = _resolve_root_dir(root_raw)
    if root_abs is None:
        return _load_failure("WORKSPACE_ROOT_UNAVAILABLE")
    recipe_path, code = _revalidate_artifacts(root_abs, version)
    if recipe_path is None:
        return _load_failure(code)
    payload, code = _load_envelope(recipe_path, version.record)
    if payload is None:
        return _load_failure(code)
    return _loaded(version.record, payload, str(action_reference))


def load_confirmed_recipe(
    *,
    session_state: Mapping[str, Any],
    workspace_root: str,
    action_reference: str,
) -> LoadedRecipe:
    """Load and independently revalidate one confirmed managed recipe.

    Performs exactly one fresh bounded managed-version discovery, resolves the
    action reference to a single valid non-duplicate record, revalidates the
    sidecar, source, and recipe artifacts (confinement, regular-file status,
    bounded size, recorded source identity), parses bounded UTF-8 JSON, and
    accepts only ``schema_version`` exactly ``"1"`` whose registered digest
    matches. An unsupported envelope and a digest mismatch are distinct,
    independent refusals. Returns deeply immutable steps in which frozen arrays
    and frozen objects stay distinct, including empty containers. Writes
    nothing, mutates no session state, and activates nothing.
    """
    try:
        return _run_load(session_state, workspace_root, action_reference)
    except Exception:
        return _load_failure("LOAD_FAILED")


# --- create_recipe_draft ------------------------------------------------------


def _run_draft(session_state: Any, workspace_root: Any, loaded_recipe: Any) -> RecipeDraft:
    code = _guard_common(session_state, workspace_root)
    if code:
        return _draft_failure(code)
    if not isinstance(loaded_recipe, LoadedRecipe):
        return _draft_failure("LOADED_RECIPE_INVALID")
    if not loaded_recipe.loaded:
        return _draft_failure("LOADED_RECIPE_NOT_LOADED")
    steps = [_thaw(step) for step in loaded_recipe.steps]
    if any(not isinstance(step, dict) for step in steps):
        return _draft_failure("LOADED_RECIPE_INVALID")
    return RecipeDraft(
        status=STATUS_DRAFTED,
        reason_code="DRAFTED",
        message=_STATUS_MESSAGES[STATUS_DRAFTED],
        steps=steps,
        record=loaded_recipe.record,
    )


def create_recipe_draft(
    *,
    session_state: Mapping[str, Any],
    workspace_root: str,
    loaded_recipe: LoadedRecipe,
) -> RecipeDraft:
    """Create a mutable, deeply detached draft of a loaded confirmed recipe.

    Every nested mutable value is rebuilt, so editing the draft — at any depth —
    can never reach the immutable loaded steps or the durable recipe bytes.
    Mutates no session state and touches no durable artifact.
    """
    try:
        return _run_draft(session_state, workspace_root, loaded_recipe)
    except Exception:
        return _draft_failure("DRAFT_FAILED")


# --- Durable-recipe admission -------------------------------------------------

_STEP_KEYS = frozenset(
    {"step_id", "operation", "columns", "parameters", "before", "after", "status", "warning"}
)
_ADMITTED_STEP_STATUSES = frozenset({STATUS_PENDING, STATUS_APPLIED, STATUS_SKIPPED})

# Historical spellings that no longer name a supported operation. They are
# refused as their own family so a stale recipe is never silently reinterpreted.
_LEGACY_ALIASES = frozenset(
    {
        "cast",
        "derived",
        "drop_duplicate",
        "duplicates",
        "missing",
        "outlier",
        "string_op",
        "type-cast",
    }
)

_TYPE_CAST_TARGETS = frozenset({"numeric", "string", "datetime", "boolean"})
_MISSING_STRATEGIES = frozenset({"drop", "mean", "median", "mode", "constant"})
_OUTLIER_STRATEGIES = frozenset({"flag", "clip", "remove"})
_ENCODING_STRATEGIES = frozenset({"one_hot", "frequency", "label"})
_SCALING_STRATEGIES = frozenset({"minmax", "zscore"})
_DERIVED_KINDS = frozenset({"year", "month", "day", "day_of_week", "text_length"})
_OUTPUT_MODES = frozenset({"new", "existing"})
_CALC_OUTPUT_KEYS = frozenset({"output_mode", "output_column"})
# Values the engine resolves to "no column at all"; admitting them would store a
# parameter the engine silently ignores.
_IGNORED_COLUMN_SENTINELS = frozenset({"(none)"})


@dataclass(frozen=True, slots=True)
class _OpSpec:
    """Admission rules for one supported durable operation."""

    allowed: frozenset[str]
    columns: str
    calculated: bool
    check: Callable[[tuple[str, ...], Mapping[str, Any]], str]


def _optional_text(value: Any, *, allow_blank: bool = False) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    return allow_blank or bool(value.strip())


def _optional_mapping(value: Any) -> bool:
    return value is None or isinstance(value, Mapping)


def _column_error(value: Any, seen: list[str]) -> str:
    if not isinstance(value, str):
        return "COLUMN_TYPE_INVALID"
    if not value.strip():
        return "COLUMN_BLANK"
    if value != value.strip():
        return "COLUMN_UNTRIMMED"
    if value in seen:
        return "COLUMN_DUPLICATE"
    return ""


def _admit_scalar_value(value: Any) -> str:
    if isinstance(value, bool):
        return "PARAMETER_BOOL_AS_NUMBER"
    if isinstance(value, float) and not math.isfinite(value):
        return "PARAMETER_NOT_FINITE"
    if value is None or isinstance(value, str | int | float):
        return ""
    return "PARAMETER_TYPE_INVALID"


def _require_enum(params: Mapping[str, Any], key: str, allowed: frozenset[str]) -> str:
    value = params.get(key)
    if not isinstance(value, str):
        return "PARAMETER_TYPE_INVALID"
    if value not in allowed:
        return "PARAMETER_ENUM_INVALID"
    return ""


def _require_normalized_enum(params: Mapping[str, Any], key: str, allowed: frozenset[str]) -> str:
    """Admit only the canonical form of a value the engine strips and lowercases."""
    value = params.get(key)
    if not isinstance(value, str):
        return "PARAMETER_TYPE_INVALID"
    if value != value.strip().lower():
        return "PARAMETER_WOULD_NORMALIZE"
    if value not in allowed:
        return "PARAMETER_ENUM_INVALID"
    return ""


def _require_int(
    params: Mapping[str, Any], key: str, low: int, high: int, out_of_range: str
) -> str:
    value = params.get(key)
    if isinstance(value, bool):
        return "PARAMETER_BOOL_AS_NUMBER"
    if not isinstance(value, int):
        return "PARAMETER_TYPE_INVALID"
    if value < low or value > high:
        return out_of_range
    return ""


def _require_number(params: Mapping[str, Any], key: str) -> str:
    value = params.get(key)
    if isinstance(value, bool):
        return "PARAMETER_BOOL_AS_NUMBER"
    if not isinstance(value, int | float):
        return "PARAMETER_TYPE_INVALID"
    if not math.isfinite(float(value)):
        return "PARAMETER_NOT_FINITE"
    return ""


def _require_column_name(params: Mapping[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str):
        return "PARAMETER_TYPE_INVALID"
    if not value.strip():
        return "COLUMN_BLANK"
    if value != value.strip():
        return "COLUMN_UNTRIMMED"
    return ""


# --- Per-operation admission checks -------------------------------------------


def _check_type_cast(_columns: tuple[str, ...], params: Mapping[str, Any]) -> str:
    code = _require_enum(params, "target_type", _TYPE_CAST_TARGETS)
    if code:
        return code
    if "errors" not in params:
        return ""
    # The engine accepts an ``errors`` argument but never consults it.
    return "" if params["errors"] == "coerce" else "PARAMETER_WOULD_IGNORE"


def _check_missing_value(_columns: tuple[str, ...], params: Mapping[str, Any]) -> str:
    code = _require_enum(params, "strategy", _MISSING_STRATEGIES)
    if code:
        return code
    has_fill = "fill_value" in params
    if params["strategy"] != "constant":
        return "PARAMETER_WOULD_IGNORE" if has_fill else ""
    if not has_fill:
        return "PARAMETER_REQUIRED"
    return _admit_scalar_value(params["fill_value"])


def _check_drop_duplicates(_columns: tuple[str, ...], _params: Mapping[str, Any]) -> str:
    return ""


def _check_iqr_outlier(_columns: tuple[str, ...], params: Mapping[str, Any]) -> str:
    return _require_enum(params, "strategy", _OUTLIER_STRATEGIES)


def _check_encoding(_columns: tuple[str, ...], params: Mapping[str, Any]) -> str:
    code = _require_enum(params, "strategy", _ENCODING_STRATEGIES)
    if code:
        return code
    if "max_cardinality" not in params:
        return ""
    if params["strategy"] != "one_hot":
        return "PARAMETER_WOULD_IGNORE"
    return _require_int(
        params, "max_cardinality", 1, _MAX_CARDINALITY_CEILING, "PARAMETER_OUT_OF_RANGE"
    )


def _check_scaling(_columns: tuple[str, ...], params: Mapping[str, Any]) -> str:
    return _require_enum(params, "strategy", _SCALING_STRATEGIES)


def _check_derived_column(_columns: tuple[str, ...], params: Mapping[str, Any]) -> str:
    code = _require_column_name(params, "source_column")
    if code:
        return code
    return _require_enum(params, "derived_kind", _DERIVED_KINDS)


def _check_calc_arithmetic(_columns: tuple[str, ...], params: Mapping[str, Any]) -> str:
    for key in ("left_column", "right_column"):
        code = _require_column_name(params, key)
        if code:
            return code
    return _require_enum(params, "operator", _ARITHMETIC_OPS)


def _check_scalar_operator(params: Mapping[str, Any]) -> str:
    operator = params["operator"]
    has_role = "constant_role" in params
    if operator == "power":
        if not has_role:
            return ""
        return _require_normalized_enum(params, "constant_role", _POWER_CONSTANT_ROLES)
    if has_role:
        return "PARAMETER_WOULD_IGNORE"
    if operator != "round":
        return ""
    scalar = float(params["scalar"])
    # The engine truncates the operand through ``int()`` before rounding.
    return "" if scalar == int(scalar) else "PARAMETER_WOULD_NORMALIZE"


def _check_calc_scalar(_columns: tuple[str, ...], params: Mapping[str, Any]) -> str:
    code = _require_column_name(params, "source_column")
    if code:
        return code
    code = _require_enum(params, "operator", _SCALAR_OPS)
    if code:
        return code
    code = _require_number(params, "scalar")
    if code:
        return code
    return _check_scalar_operator(params)


def _check_conditional_comparison(params: Mapping[str, Any]) -> str:
    if params["comparator"] not in _ORDERED_COMPARATORS:
        return ""
    value = params["compare_value"]
    if isinstance(value, int | float):
        return ""
    try:
        float(str(value))
    except (TypeError, ValueError):
        return "CONDITIONAL_FIELD_ILLEGAL"
    return ""


def _check_calc_conditional(_columns: tuple[str, ...], params: Mapping[str, Any]) -> str:
    code = _require_column_name(params, "source_column")
    if code:
        return code
    code = _require_enum(params, "comparator", _COMPARATORS)
    if code:
        return code
    for key in ("compare_value", "result_value", "fallback_value"):
        if key not in params:
            return "PARAMETER_REQUIRED"
        code = _admit_scalar_value(params[key])
        if code:
            return code
    return _check_conditional_comparison(params)


def _check_calc_binning(_columns: tuple[str, ...], params: Mapping[str, Any]) -> str:
    code = _require_column_name(params, "source_column")
    if code:
        return code
    if "num_bins" not in params:
        return "PARAMETER_REQUIRED"
    return _require_int(params, "num_bins", MIN_BINS, MAX_BINS, "PARAMETER_WOULD_CLAMP")


def _check_string_replace(params: Mapping[str, Any]) -> str:
    find = params.get("find")
    if not isinstance(find, str):
        return "PARAMETER_TYPE_INVALID"
    if not find:
        return "PARAMETER_WOULD_SKIP"
    replacement = params.get("replace")
    if replacement is None:
        return ""
    return "" if isinstance(replacement, str) else "PARAMETER_TYPE_INVALID"


def _check_string_concat(params: Mapping[str, Any]) -> str:
    if "other_column" in params:
        code = _require_column_name(params, "other_column")
        if code:
            return code
        if params["other_column"] in _IGNORED_COLUMN_SENTINELS:
            return "PARAMETER_WOULD_IGNORE"
    if "literal" not in params:
        return ""
    literal = params["literal"]
    if not isinstance(literal, str):
        return "PARAMETER_TYPE_INVALID"
    return "" if literal else "PARAMETER_WOULD_IGNORE"


def _check_string_fields(params: Mapping[str, Any]) -> str:
    operation = params["operation"]
    replace_keys = {"find", "replace"} & set(params)
    concat_keys = {"other_column", "literal"} & set(params)
    if operation == "replace":
        return "PARAMETER_WOULD_IGNORE" if concat_keys else _check_string_replace(params)
    if operation == "concat":
        return "PARAMETER_WOULD_IGNORE" if replace_keys else _check_string_concat(params)
    if replace_keys or concat_keys:
        return "PARAMETER_WOULD_IGNORE"
    return ""


def _check_calc_string(_columns: tuple[str, ...], params: Mapping[str, Any]) -> str:
    code = _require_column_name(params, "source_column")
    if code:
        return code
    code = _require_enum(params, "operation", _STRING_OPS)
    if code:
        return code
    return _check_string_fields(params)


_OPERATION_SPECS: dict[str, _OpSpec] = {
    OP_TYPE_CAST: _OpSpec(
        frozenset({"target_type", "errors"}), "required", False, _check_type_cast
    ),
    OP_MISSING: _OpSpec(
        frozenset({"strategy", "fill_value"}), "required", False, _check_missing_value
    ),
    OP_DROP_DUPLICATES: _OpSpec(frozenset({"subset"}), "subset", False, _check_drop_duplicates),
    OP_OUTLIER: _OpSpec(frozenset({"strategy"}), "required", False, _check_iqr_outlier),
    OP_ENCODING: _OpSpec(
        frozenset({"strategy", "max_cardinality"}), "required", False, _check_encoding
    ),
    OP_SCALING: _OpSpec(frozenset({"strategy"}), "required", False, _check_scaling),
    OP_DERIVED: _OpSpec(
        frozenset({"source_column", "derived_kind"}), "derived", False, _check_derived_column
    ),
    OP_CALC_ARITHMETIC: _OpSpec(
        _CALC_OUTPUT_KEYS | {"left_column", "right_column", "operator"},
        "forbidden",
        True,
        _check_calc_arithmetic,
    ),
    OP_CALC_SCALAR: _OpSpec(
        _CALC_OUTPUT_KEYS | {"source_column", "operator", "scalar", "constant_role"},
        "forbidden",
        True,
        _check_calc_scalar,
    ),
    OP_CALC_CONDITIONAL: _OpSpec(
        _CALC_OUTPUT_KEYS
        | {"source_column", "comparator", "compare_value", "result_value", "fallback_value"},
        "forbidden",
        True,
        _check_calc_conditional,
    ),
    OP_CALC_BINNING: _OpSpec(
        _CALC_OUTPUT_KEYS | {"source_column", "num_bins"},
        "forbidden",
        True,
        _check_calc_binning,
    ),
    OP_CALC_STRING: _OpSpec(
        _CALC_OUTPUT_KEYS
        | {"source_column", "operation", "find", "replace", "other_column", "literal"},
        "forbidden",
        True,
        _check_calc_string,
    ),
}

#: The exactly twelve durable operations this service will reprocess.
ADMITTED_OPERATIONS: tuple[str, ...] = tuple(_OPERATION_SPECS)


# --- Step-level admission ------------------------------------------------------


def _admit_step_metadata(step: Mapping[str, Any]) -> str:
    if not _optional_text(step.get("step_id")):
        return "STEP_ID_INVALID"
    status = step.get("status")
    if status is not None and status not in _ADMITTED_STEP_STATUSES:
        return "STEP_STATUS_INVALID"
    if not _optional_text(step.get("warning"), allow_blank=True):
        return "STEP_WARNING_INVALID"
    if not _optional_mapping(step.get("before")):
        return "STEP_FACTS_INVALID"
    if not _optional_mapping(step.get("after")):
        return "STEP_FACTS_INVALID"
    return ""


def _admit_step_shape(step: Any) -> tuple[_OpSpec | None, str]:
    if not isinstance(step, Mapping):
        return None, "STEP_NOT_A_MAPPING"
    if not set(map(str, step)).issubset(_STEP_KEYS):
        return None, "STEP_UNKNOWN_KEY"
    operation = step.get("operation")
    if not isinstance(operation, str):
        return None, "OPERATION_TYPE_INVALID"
    if operation in _LEGACY_ALIASES:
        return None, "OPERATION_LEGACY_ALIAS"
    spec = _OPERATION_SPECS.get(operation)
    if spec is None:
        return None, "OPERATION_UNSUPPORTED"
    code = _admit_step_metadata(step)
    if code:
        return None, code
    return spec, ""


def _admit_columns(step: Mapping[str, Any]) -> tuple[tuple[str, ...] | None, str]:
    raw = step.get("columns")
    if raw is None:
        return (), ""
    if not isinstance(raw, list | tuple):
        return None, "COLUMNS_TYPE_INVALID"
    if len(raw) > _MAX_COLUMNS_PER_STEP:
        return None, "COLUMNS_TOO_MANY"
    names: list[str] = []
    for value in raw:
        code = _column_error(value, names)
        if code:
            return None, code
        names.append(value)
    return tuple(names), ""


def _admit_parameters(step: Mapping[str, Any]) -> tuple[Mapping[str, Any] | None, str]:
    raw = step.get("parameters")
    if raw is None:
        return {}, ""
    if not isinstance(raw, Mapping):
        return None, "PARAMETERS_TYPE_INVALID"
    if len(raw) > _MAX_PARAMETERS_PER_STEP:
        return None, "PARAMETERS_TOO_MANY"
    if any(not isinstance(key, str) for key in raw):
        return None, "PARAMETER_KEY_INVALID"
    return raw, ""


def _admit_subset_columns(columns: tuple[str, ...], params: Mapping[str, Any]) -> str:
    subset = params.get("subset")
    if subset is None:
        return ""
    if not isinstance(subset, list | tuple):
        return "PARAMETER_TYPE_INVALID"
    if columns:
        # ``subset`` wins in the engine, so the target columns would be ignored.
        return "PARAMETER_WOULD_IGNORE"
    if not subset:
        return "PARAMETER_WOULD_IGNORE"
    names: list[str] = []
    for value in subset:
        code = _column_error(value, names)
        if code:
            return code
        names.append(value)
    return ""


def _admit_derived_columns(columns: tuple[str, ...], params: Mapping[str, Any]) -> str:
    if not columns:
        return ""
    if len(columns) != 1:
        return "COLUMNS_WOULD_BE_IGNORED"
    return "" if columns[0] == params.get("source_column") else "COLUMNS_WOULD_BE_IGNORED"


def _admit_columns_policy(
    spec: _OpSpec, columns: tuple[str, ...], params: Mapping[str, Any]
) -> str:
    if spec.columns == "required":
        return "" if columns else "COLUMNS_REQUIRED"
    if spec.columns == "forbidden":
        return "" if not columns else "COLUMNS_NOT_APPLICABLE"
    if spec.columns == "subset":
        return _admit_subset_columns(columns, params)
    return _admit_derived_columns(columns, params)


def _admit_output_name(mode: str, name: Any) -> str:
    if name is None:
        return "OUTPUT_DESTINATION_UNSAFE" if mode == "existing" else ""
    if not isinstance(name, str):
        return "PARAMETER_TYPE_INVALID"
    if name != name.strip():
        return "OUTPUT_DESTINATION_UNSAFE"
    if not name:
        return "OUTPUT_DESTINATION_UNSAFE" if mode == "existing" else ""
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        return "OUTPUT_DESTINATION_UNSAFE"
    return ""


def _admit_generated_outputs(
    operation: str, columns: tuple[str, ...], params: Mapping[str, Any], outputs: set[str]
) -> str:
    """Reserve the create-only destinations a non-calculated step can prove it writes.

    Only deterministic names participate. A one-hot expansion is named after the
    values actually present, so admission reserves nothing for it and never
    claims to have validated it - execution against the real frame is what
    proves that. No source schema reaches this boundary either, so what is
    proven here is intra-recipe uniqueness.
    """
    generated = deterministic_output_names(operation, columns, params)
    if not generated:
        return ""
    if output_collisions(outputs, generated):
        return OUTPUT_COLLISION
    outputs.update(generated)
    return ""


def _admit_output(
    spec: _OpSpec,
    operation: str,
    columns: tuple[str, ...],
    params: Mapping[str, Any],
    outputs: set[str],
) -> str:
    if not spec.calculated:
        return _admit_generated_outputs(operation, columns, params, outputs)
    if "output_mode" in params:
        code = _require_normalized_enum(params, "output_mode", _OUTPUT_MODES)
        if code:
            return code
    mode = str(params.get("output_mode") or "new")
    name = params.get("output_column")
    code = _admit_output_name(mode, name)
    if code:
        return code
    if not isinstance(name, str) or not name:
        return ""
    if output_collisions(outputs, [name]):
        return OUTPUT_COLLISION
    outputs.add(name)
    return ""


def _admit_operation(
    spec: _OpSpec,
    operation: str,
    columns: tuple[str, ...],
    params: Mapping[str, Any],
    outputs: set[str],
) -> str:
    if not set(params).issubset(spec.allowed):
        return "PARAMETER_UNKNOWN_KEY"
    code = _admit_columns_policy(spec, columns, params)
    if code:
        return code
    code = spec.check(columns, params)
    if code:
        return code
    return _admit_output(spec, operation, columns, params, outputs)


def _admit_step(step: Any, outputs: set[str]) -> str:
    spec, code = _admit_step_shape(step)
    if spec is None:
        return code
    columns, code = _admit_columns(step)
    if columns is None:
        return code
    params, code = _admit_parameters(step)
    if params is None:
        return code
    return _admit_operation(spec, str(step["operation"]), columns, params, outputs)


def _run_admission(session_state: Any, workspace_root: Any, steps: Any) -> RecipeAdmission:
    code = _guard_common(session_state, workspace_root)
    if code:
        return _admission_failure(code, -1)
    if not isinstance(steps, list | tuple):
        return _admission_failure("STEPS_NOT_A_SEQUENCE", -1)
    if not steps:
        return _admission_failure("STEPS_EMPTY", -1)
    if len(steps) > _MAX_STEPS:
        return _admission_failure("STEPS_TOO_MANY", -1)
    outputs: set[str] = set()
    operations: list[str] = []
    for index, step in enumerate(steps):
        code = _admit_step(step, outputs)
        if code:
            return _admission_failure(code, index)
        operations.append(str(step["operation"]))
    return RecipeAdmission(
        status=STATUS_ADMITTED,
        reason_code="ADMITTED",
        message=_STATUS_MESSAGES[STATUS_ADMITTED],
        step_index=-1,
        operations=tuple(operations),
    )


def revalidate_durable_recipe(
    *,
    session_state: Mapping[str, Any],
    workspace_root: str,
    steps: Any,
) -> RecipeAdmission:
    """Strictly admit only the twelve supported durable operations.

    Performs no durable read, no durable write, and no session mutation. Every
    legacy alias, unknown key, wrong type, boolean-as-number, blank, untrimmed
    or duplicate column, invalid enum, illegal conditional field, unsafe
    destination, output collision, and every value the engine would clamp,
    normalize, ignore, or skip is refused with its own reason code and the
    index of the offending step. Output collision covers both an explicit
    calculated destination and the deterministic generated destination of a
    create-only family; a value-dependent one-hot expansion is proven at
    execution, never here.
    """
    try:
        return _run_admission(session_state, workspace_root, steps)
    except Exception:
        return _admission_failure("ADMISSION_FAILED", -1)


# --- Workspace snapshot and exact restoration ---------------------------------

_PREPROCESSED_SUBFOLDER = "preprocessed"
_RECIPES_SUBFOLDER = "recipes"
_MANAGED_SUBFOLDERS = (_PREPROCESSED_SUBFOLDER, _RECIPES_SUBFOLDER)


@dataclass(frozen=True, slots=True)
class _WorkspaceSnapshot:
    """Pre-call state of the two managed subfolders for exact restoration."""

    root: Path
    existing_dirs: frozenset[str]
    entries: Mapping[str, frozenset[str]]
    pattern: re.Pattern[str]


def _reserved_name_pattern(stem: str) -> re.Pattern[str]:
    """Match exactly the final and temporary names confirmation may create."""
    quoted = re.escape(stem)
    suffixes = r"(?:\.csv|\.json|\.csv\.dqtv\.json)"
    final = rf"{quoted}(?:-\d{{1,4}})?{suffixes}"
    return re.compile(rf"^(?:{final}|\.{final}\..+\.tmp)$")


def _snapshot_workspace(root_abs: Path, stem: str) -> _WorkspaceSnapshot:
    existing: set[str] = set()
    entries: dict[str, frozenset[str]] = {}
    for folder in _MANAGED_SUBFOLDERS:
        directory = root_abs / folder
        if directory.is_dir():
            existing.add(folder)
            entries[folder] = frozenset(os.listdir(directory))
        else:
            entries[folder] = frozenset()
    return _WorkspaceSnapshot(
        root=root_abs,
        existing_dirs=frozenset(existing),
        entries=entries,
        pattern=_reserved_name_pattern(stem),
    )


def _remove_path(path: Path) -> bool:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False
    return True


def _remove_empty_dir(path: Path) -> bool:
    try:
        if path.is_dir() and not os.listdir(path):
            path.rmdir()
    except OSError:
        return False
    return True


def _restore_workspace(snapshot: _WorkspaceSnapshot) -> bool:
    """Delete only what this call could have created; restore missing folders.

    Confinement to the reserved-name pattern is what makes the sweep safe: a
    competitor's file can never match a name this call reserved, so an unrelated
    artifact is never removed.
    """
    restored = True
    for folder, before in snapshot.entries.items():
        directory = snapshot.root / folder
        if not directory.is_dir():
            continue
        for name in sorted(os.listdir(directory)):
            if name in before or snapshot.pattern.match(name) is None:
                continue
            restored = _remove_path(directory / name) and restored
    for folder in snapshot.entries:
        if folder not in snapshot.existing_dirs:
            restored = _remove_empty_dir(snapshot.root / folder) and restored
    return restored


# --- confirm_reprocessed_child -------------------------------------------------


def _guard_csv_bytes(csv_bytes: Any) -> str:
    if not isinstance(csv_bytes, bytes | bytearray):
        return "CSV_BYTES_INVALID"
    if not csv_bytes:
        return "CSV_BYTES_EMPTY"
    if len(csv_bytes) > _MAX_SOURCE_BYTES:
        return "CSV_BYTES_TOO_LARGE"
    return ""


def _guard_label(label: Any) -> str:
    if not isinstance(label, str):
        return "LABEL_INVALID"
    if not label.strip():
        return "LABEL_BLANK"
    if len(label) > _MAX_LABEL_CHARS:
        return "LABEL_TOO_LONG"
    return ""


def _guard_child_inputs(parent_record: Any, csv_bytes: Any, label: Any) -> str:
    if not isinstance(parent_record, DatasetVersionRecord):
        return "PARENT_RECORD_INVALID"
    code = _guard_csv_bytes(csv_bytes)
    if code:
        return code
    return _guard_label(label)


def _parent_trust_error(session_state: Mapping[str, Any], parent_record: Any) -> str:
    """Fail closed when managed trust exists but does not back this parent."""
    decision = resolve_trust_authority(dict(session_state))
    if decision.authority is TrustAuthority.FAIL_CLOSED:
        return "MANAGED_TRUST_REQUIRED"
    root = decision.root
    if not decision.managed or root is None:
        return ""
    if root.version_id != parent_record.version_id:
        return "PARENT_NOT_TRUSTED"
    if root.content_id != parent_record.content_id:
        return "PARENT_NOT_TRUSTED"
    return ""


def _parent_context(
    session_state: Mapping[str, Any], root_abs: Path, parent_record: DatasetVersionRecord
) -> tuple[DatasetContext | None, str]:
    code = _parent_trust_error(session_state, parent_record)
    if code:
        return None, code
    resolved, code = _resolve_confined(root_abs, parent_record.file_relative_path)
    if resolved is None:
        return None, "PARENT_SOURCE_" + code
    try:
        st = resolved.stat()
    except OSError:
        return None, "PARENT_SOURCE_UNREADABLE"
    return (
        DatasetContext(
            source_path=str(resolved),
            display_name=resolved.name,
            size_bytes=int(st.st_size),
            modified_ns=int(st.st_mtime_ns),
            managed=True,
            version_id=parent_record.version_id,
            family_id=parent_record.family_id,
            content_id=parent_record.content_id,
            root_content_id=parent_record.root_content_id,
            parent_version_id=(
                parent_record.parent.version_id if parent_record.parent is not None else None
            ),
            version_label=parent_record.label,
        ),
        "",
    )


def _child_payload(executed_steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the durable child recipe from execution evidence, in replay order.

    The child records what the replay actually did — including a step the engine
    skipped and the warning that says why — never the authored intent alone. No
    summary is invented: this path observes no before/after frames of its own.
    """
    return recipe_to_json_payload(executed_steps, None)


def _finish_child(
    result: Any, snapshot: _WorkspaceSnapshot, payload: Mapping[str, Any]
) -> ReprocessedChild:
    if result.status is ConfirmationStatus.CONFIRMED and result.record is not None:
        return ReprocessedChild(
            status=STATUS_CONFIRMED,
            reason_code="CONFIRMED",
            message=_STATUS_MESSAGES[STATUS_CONFIRMED],
            record=result.record,
            recipe=_freeze(payload),
            csv_relative_path=result.csv_relative_path,
            recipe_relative_path=result.recipe_relative_path,
            sidecar_relative_path=result.sidecar_relative_path,
        )
    # Anything short of a registered child is rolled back to the exact pre-call
    # workspace state; an unmanaged save is never reported as an outcome.
    restored = _restore_workspace(snapshot)
    return _child_failure("CHILD_NOT_CONFIRMED" if restored else "CLEANUP_INCOMPLETE")


def _admitted_evidence(
    session_state: Any, workspace_root: Any, steps: Any, executed_steps: Any
) -> tuple[list[dict[str, Any]] | None, str]:
    """Prove the replay completed successfully and that its record is admissible.

    Runs before any durable read or write. The evidence is admitted in its own
    right because it — not the authored draft — is what becomes the durable
    child recipe, so nothing is persisted that admission would have refused.
    """
    code = replay_refusal_code(steps, executed_steps)
    if code:
        return None, code
    evidence = [_thaw(step) for step in executed_steps]
    admission = revalidate_durable_recipe(
        session_state=session_state, workspace_root=workspace_root, steps=evidence
    )
    if not admission.admitted:
        return None, admission.reason_code
    return evidence, ""


def _run_child(
    session_state: Any,
    workspace_root: Any,
    parent_record: Any,
    steps: Any,
    executed_steps: Any,
    csv_bytes: Any,
    label: Any,
) -> ReprocessedChild:
    admission = revalidate_durable_recipe(
        session_state=session_state, workspace_root=workspace_root, steps=steps
    )
    if not admission.admitted:
        return _child_failure(admission.reason_code)
    evidence, code = _admitted_evidence(session_state, workspace_root, steps, executed_steps)
    if evidence is None:
        return _child_failure(code)
    code = _guard_child_inputs(parent_record, csv_bytes, label)
    if code:
        return _child_failure(code)
    root_abs = _resolve_root_dir(str(workspace_root).strip())
    if root_abs is None:
        return _child_failure("WORKSPACE_ROOT_UNAVAILABLE")
    parent, code = _parent_context(session_state, root_abs, parent_record)
    if parent is None:
        return _child_failure(code)
    payload = _child_payload(evidence)
    snapshot = _snapshot_workspace(root_abs, _safe_stem(parent.display_name))
    result = confirm_processed_version(
        workspace_root=str(workspace_root).strip(),
        csv_bytes=bytes(csv_bytes),
        recipe=payload,
        parent=parent,
        label=str(label).strip(),
        filename_stem=parent.display_name,
    )
    return _finish_child(result, snapshot, payload)


def confirm_reprocessed_child(
    *,
    session_state: Mapping[str, Any] | MutableMapping[str, Any],
    workspace_root: str,
    parent_record: DatasetVersionRecord,
    steps: Any,
    executed_steps: Any,
    csv_bytes: bytes,
    label: str,
) -> ReprocessedChild:
    """Confirm exactly one immutable child of ``parent_record``.

    ``executed_steps`` is the execution evidence ``apply_recipe`` returned for
    ``steps``, and it is required: a caller reaching this service directly still
    cannot confirm a replay that errored, ran short, ran out of order, or was
    substituted. Evidence is verified and re-admitted before any durable read or
    write, so a failed replay leaves no CSV, recipe, or sidecar behind and no
    child is registered.

    Revalidates every step before any durable work, preserves operation, column,
    and parameter ordering, and publishes the CSV, recipe, and sidecar through
    the accepted confirmation boundary so the sidecar remains the single
    registration point. The durable recipe is the executed evidence, so a
    confirmed child never claims an operation that did not happen. The child
    carries exactly one parent — ``parent_record`` — inherits its ``family_id``
    and ``root_content_id``, and receives a new ``version_id`` and
    ``content_id``. Every reachable durable failure restores the exact pre-call
    workspace state, leaving no CSV, recipe, sidecar, temporary file, or orphan
    directory behind, and is never reported as an unmanaged save. Session state
    is not mutated, ``DATASET_CONTEXT`` stays on the parent, and activating the
    child requires a later explicit reopen.
    """
    try:
        return _run_child(
            session_state, workspace_root, parent_record, steps, executed_steps, csv_bytes, label
        )
    except Exception:
        return _child_failure("CONFIRMATION_FAILED")
