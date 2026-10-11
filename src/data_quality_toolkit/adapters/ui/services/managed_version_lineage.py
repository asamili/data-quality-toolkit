"""Pure, bounded, direct-only managed-version lineage projection.

This service is a second safe-projection boundary above the Phase-8 discovery
service (:mod:`...services.dataset_discovery`) and beside the Phase-9 history
projector (:mod:`...services.managed_version_history`). It consumes exactly one
already-completed, immutable :class:`...dataset_discovery.DiscoveryResult` and
projects a bounded, privacy-safe view of the *direct* lineage around a single
selected managed version:

* the selected version (resolved by the exact discovery/history selectable short-id and
  duplicate semantics);
* the safely resolved family root (a unique same-family valid record whose
  ``content_id`` matches the selected record's ``root_content_id``);
* the single direct parent (the selected record's one ``ParentRef``);
* the direct children (records whose single ``ParentRef`` points back at the
  selected version);
* normalized summary counts for unavailable or unverifiable relationships and a
  deterministic truncation flag.

It is deliberately *not* a lineage index, graph, or ancestry walker: only direct
relationships are ever exposed. The only non-direct hop performed is a bounded,
internal cycle-safety walk that produces no displayed node — it exists solely to
refuse presenting a parent edge that participates in a cycle. Root is resolved by
content identity, not by traversal.

The projection is pure and deterministic: it performs no filesystem scan, durable
read or write, session-state access, activation, repair, or record mutation; it
preserves the ordering discovery already established; it runs in O(n) time and bounded
memory; and it emits only frozen, slotted result types carrying primitive,
display-safe values. No record, locator, path, filename, full UUID, content hash,
family UUID, recipe value, raw discovery issue, or exception ever crosses this
boundary. Selection and activation are independent: this module reads no active
pointer — ``active_reference`` is supplied by the caller from an existing accepted
accessor — and it never activates, reopens, or restores anything.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC
from enum import StrEnum

from data_quality_toolkit.adapters.ui.services.dataset_discovery import (
    DiscoveredVersion,
    DiscoveryResult,
)
from data_quality_toolkit.adapters.ui.services.dataset_versions import DatasetVersionRecord

__all__ = [
    "MAX_LINEAGE_NODES",
    "LineageNode",
    "LineageRelationship",
    "LineageState",
    "LineageView",
    "empty_lineage",
    "project_lineage",
]

# Accepted absolute ceiling for direct-child bounding. A caller may tighten the
# bound (1..64) but never loosen it; this mirrors the bounded-safety posture of
# the accepted discovery caps.
MAX_LINEAGE_NODES = 64


# --- Public enums -----------------------------------------------------------


class LineageState(StrEnum):
    """Top-level, generic state of a direct-lineage projection."""

    EMPTY = "empty"
    READY = "ready"
    SELECTED_UNAVAILABLE = "selected_unavailable"
    SELECTED_AMBIGUOUS = "selected_ambiguous"
    CORRUPT_RELATION = "corrupt_relation"
    TRUNCATED = "truncated"


class LineageRelationship(StrEnum):
    """Direct relationship of a projected node to the selected version."""

    SELECTED = "selected"
    ROOT = "root"
    PARENT = "parent"
    CHILD = "child"
    UNAVAILABLE = "unavailable"


# --- Frozen, slotted, UI-safe projected value types -------------------------


@dataclass(frozen=True, slots=True)
class LineageNode:
    """One privacy-safe node in the direct-lineage projection.

    Every field is a primitive, display-safe value. There is no record, locator,
    path, filename, full UUID, content hash, or family UUID here by construction.
    ``is_active`` and ``is_selected`` are independent states.
    """

    label: str
    short_version_id: str
    family_summary: str
    relationship: LineageRelationship
    created_at: str
    status_label: str
    is_active: bool
    is_selected: bool


@dataclass(frozen=True, slots=True)
class LineageView:
    """The complete, bounded, privacy-safe direct-lineage surface.

    This is the only type handed to the renderer. It holds a generic state token,
    a fixed generic message, the direct nodes, normalized summary counts, a
    deterministic truncation flag, and a complete text alternative.
    """

    state: LineageState
    message: str
    selected: LineageNode | None
    root: LineageNode | None
    parent: LineageNode | None
    children: tuple[LineageNode, ...]
    unavailable_relatives: int
    corrupt_relatives: int
    truncated: bool
    text_alternative: str


# --- Fixed, generic, privacy-safe messages ----------------------------------

_MESSAGES: dict[LineageState, str] = {
    LineageState.EMPTY: "No managed version is selected for lineage.",
    LineageState.READY: "Direct lineage for the selected managed version.",
    LineageState.SELECTED_UNAVAILABLE: "The selected managed version is no longer available.",
    LineageState.SELECTED_AMBIGUOUS: "The selected reference is ambiguous and cannot be shown.",
    LineageState.CORRUPT_RELATION: (
        "Some direct relationships are unavailable or could not be verified."
    ),
    LineageState.TRUNCATED: "Direct lineage shown; some direct children are not listed.",
}

_STATUS_ACTIVE = "Active"
_STATUS_SELECTED = "Selected"
_STATUS_AVAILABLE = "Available"

# Internal relationship-resolution outcomes (never displayed).
_REL_NODE = "node"
_REL_NONE = "none"
_REL_UNAVAILABLE = "unavailable"
_REL_CORRUPT = "corrupt"


# --- max_nodes contract -----------------------------------------------------


class LineageConfigError(ValueError):
    """Raised when ``max_nodes`` is not a positive, bounded integer."""


def _validate_max_nodes(max_nodes: int) -> None:
    if isinstance(max_nodes, bool) or not isinstance(max_nodes, int):
        raise LineageConfigError("max_nodes must be an integer")
    if max_nodes < 1 or max_nodes > MAX_LINEAGE_NODES:
        raise LineageConfigError(f"max_nodes must be within 1..{MAX_LINEAGE_NODES}")


# --- Short-identifier / summary helpers (never emit a full UUID) ------------


def _short_hex(value: str) -> str:
    try:
        return uuid.UUID(value).hex[:8]
    except (AttributeError, TypeError, ValueError):
        return ""


def _family_summary(family_id: str) -> str:
    short = _short_hex(family_id)
    return f"Family f-{short}" if short else "Family (unavailable)"


def _created_at(record: DatasetVersionRecord) -> str:
    """Normalize the creation time consistently to UTC (no path, no locale)."""
    return record.created_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _status_label(*, is_active: bool, is_selected: bool) -> str:
    if is_active:
        return _STATUS_ACTIVE
    if is_selected:
        return _STATUS_SELECTED
    return _STATUS_AVAILABLE


def _node(
    version: DiscoveredVersion,
    relationship: LineageRelationship,
    *,
    selected_short: str,
    active_reference: str | None,
) -> LineageNode:
    record = version.record
    short = version.display.short_version_id
    is_selected = short == selected_short
    is_active = active_reference is not None and short == active_reference
    return LineageNode(
        label=version.display.label,
        short_version_id=short,
        family_summary=_family_summary(record.family_id),
        relationship=relationship,
        created_at=_created_at(record),
        status_label=_status_label(is_active=is_active, is_selected=is_selected),
        is_active=is_active,
        is_selected=is_selected,
    )


# --- Selected-reference resolution (exact live discovery/history semantics) -


def _resolve_selected(
    result: DiscoveryResult, selected_reference: str
) -> tuple[DiscoveredVersion | None, LineageState | None]:
    """Resolve the short-id reference to exactly one currently-valid version.

    Mirrors the accepted reopen resolution: a reference matching a quarantined
    duplicate group is ambiguous and non-actionable; no unique valid match is
    unavailable; more than one is ambiguous. No record identity escapes.
    """
    if any(group.short_version_id == selected_reference for group in result.duplicates):
        return None, LineageState.SELECTED_AMBIGUOUS
    matches = [
        version
        for version in result.versions
        if version.display.short_version_id == selected_reference
    ]
    if not matches:
        return None, LineageState.SELECTED_UNAVAILABLE
    if len(matches) > 1:
        return None, LineageState.SELECTED_AMBIGUOUS
    return matches[0], None


# --- Bounded, internal cycle-safety walk (produces no displayed node) -------


def _reaches_cycle(
    start: DatasetVersionRecord, by_vid: dict[str, DiscoveredVersion], cap: int
) -> bool:
    """Return ``True`` when the parent chain from ``start`` repeats a version.

    Bounded and internal: it walks single ``ParentRef`` links only to decide
    whether the *direct* parent edge is safe to present, and it never yields a
    node. A managed cycle of any period within the family is detected; a chain
    that reaches a root or an unmanaged parent terminates cleanly.
    """
    seen: set[str] = set()
    current: DatasetVersionRecord | None = start
    steps = 0
    while current is not None:
        if steps > cap:
            return False
        if current.version_id in seen:
            return True
        seen.add(current.version_id)
        parent = current.parent
        if parent is None or parent.version_id is None:
            return False
        nxt = by_vid.get(parent.version_id)
        current = nxt.record if nxt is not None else None
        steps += 1
    return False


# --- Direct parent / root / children resolution -----------------------------


def _resolve_parent(
    selected: DiscoveredVersion, by_vid: dict[str, DiscoveredVersion], cap: int
) -> tuple[DiscoveredVersion | None, str]:
    """Resolve the single direct parent, or a normalized relationship state.

    Uses only the selected record's one ``ParentRef`` and resolves it to a unique
    valid same-family record. Self-parent, cross-family reference, a proven
    parent-content mismatch, or cycle participation drop the edge as corrupt; an
    unmanaged or unresolvable parent is unavailable; no parent is a root.
    """
    record = selected.record
    parent = record.parent
    if parent is None:
        return None, _REL_NONE
    if parent.version_id is None:
        return None, _REL_UNAVAILABLE
    if parent.version_id == record.version_id:
        return None, _REL_CORRUPT
    match = by_vid.get(parent.version_id)
    if match is None:
        return None, _REL_UNAVAILABLE
    prec = match.record
    if prec.family_id != record.family_id:
        return None, _REL_CORRUPT
    if prec.content_id != parent.content_id:
        return None, _REL_CORRUPT
    if _reaches_cycle(record, by_vid, cap):
        return None, _REL_CORRUPT
    return match, _REL_NODE


def _resolve_root(
    selected: DiscoveredVersion, same_family: list[DiscoveredVersion]
) -> tuple[DiscoveredVersion | None, str]:
    """Resolve the family root by content identity, never by traversal.

    The root is the unique same-family valid record whose ``content_id`` equals
    the selected record's ``root_content_id``. Missing or ambiguous evidence is
    unavailable — never inferred corruption. Only a structural root (no parent)
    whose own content contradicts its declared root content is a proven mismatch.
    """
    record = selected.record
    target = record.root_content_id
    candidates = [v for v in same_family if v.record.content_id == target]
    if len(candidates) == 1:
        return candidates[0], _REL_NODE
    if not candidates and record.parent is None and record.content_id != target:
        return None, _REL_CORRUPT
    return None, _REL_UNAVAILABLE


def _resolve_children(
    selected: DiscoveredVersion, versions: tuple[DiscoveredVersion, ...], max_nodes: int
) -> tuple[list[DiscoveredVersion], bool]:
    """Invert direct ``ParentRef`` links, preserving discovery order; truncate bounded.

    Includes only unique valid same-family records that name the selected version
    as their single direct parent (cross-family and self edges are dropped).
    """
    sid = selected.record.version_id
    fam = selected.record.family_id
    children = [
        version
        for version in versions
        if version.record.parent is not None
        and version.record.parent.version_id == sid
        and version.record.family_id == fam
        and version.record.version_id != sid
    ]
    truncated = len(children) > max_nodes
    return children[:max_nodes], truncated


# --- Text alternative (complete, privacy-safe, non-visual) ------------------


def _root_line(root: LineageNode | None, root_state: str) -> str:
    if root is not None:
        return f"Root: {root.label} ({root.short_version_id})."
    if root_state == _REL_CORRUPT:
        return "Root: unavailable (relationship could not be verified)."
    return "Root: unavailable."


def _parent_line(parent: LineageNode | None, parent_state: str) -> str:
    if parent is not None:
        return f"Direct parent: {parent.label} ({parent.short_version_id})."
    if parent_state == _REL_NONE:
        return "Direct parent: none (this is a root version)."
    if parent_state == _REL_CORRUPT:
        return "Direct parent: unavailable (relationship could not be verified)."
    return "Direct parent: unavailable."


def _children_lines(children: tuple[LineageNode, ...], truncated: bool) -> list[str]:
    if not children:
        return ["Direct children: none."]
    lines = [f"Direct children: {len(children)}."]
    lines.extend(f"- {child.label} ({child.short_version_id})." for child in children)
    if truncated:
        lines.append("Some direct children are not listed.")
    return lines


def _text_alternative(
    selected: LineageNode,
    root: LineageNode | None,
    parent: LineageNode | None,
    children: tuple[LineageNode, ...],
    *,
    root_state: str,
    parent_state: str,
    unavailable: int,
    corrupt: int,
    truncated: bool,
) -> str:
    parts = [
        f"Selected: {selected.label} ({selected.short_version_id}), {selected.status_label}.",
        _root_line(root, root_state),
        _parent_line(parent, parent_state),
    ]
    parts.extend(_children_lines(children, truncated))
    if unavailable:
        parts.append(f"{unavailable} related version(s) unavailable.")
    if corrupt:
        parts.append(f"{corrupt} relationship(s) could not be verified.")
    return " ".join(parts)


# --- Public entry points ----------------------------------------------------


def _empty_text_alternative(state: LineageState) -> str:
    return _MESSAGES[state]


def empty_lineage(*, state: LineageState) -> LineageView:
    """Return a non-actionable, node-free lineage view for ``state``.

    Used for a blank selection and for every non-resolvable selected reference.
    It performs no discovery and touches no filesystem or session state.
    """
    return LineageView(
        state=state,
        message=_MESSAGES[state],
        selected=None,
        root=None,
        parent=None,
        children=(),
        unavailable_relatives=0,
        corrupt_relatives=0,
        truncated=False,
        text_alternative=_empty_text_alternative(state),
    )


def _count(state: str, target: str) -> int:
    return 1 if state == target else 0


def _overall_state(*, corrupt: int, truncated: bool) -> LineageState:
    if corrupt > 0:
        return LineageState.CORRUPT_RELATION
    if truncated:
        return LineageState.TRUNCATED
    return LineageState.READY


def project_lineage(
    result: DiscoveryResult,
    selected_reference: str,
    *,
    active_reference: str | None,
    max_nodes: int = MAX_LINEAGE_NODES,
) -> LineageView:
    """Project the bounded, direct-only lineage around one selected version.

    Consumes exactly one already-completed :class:`DiscoveryResult` and returns a
    frozen, privacy-safe :class:`LineageView`. It performs no filesystem, durable,
    or session-state access, preserves discovery ordering, runs in O(n) time and bounded
    memory, and never activates or mutates anything. ``selected_reference`` and
    ``active_reference`` are independent — selection never implies activation.
    """
    _validate_max_nodes(max_nodes)
    if not selected_reference:
        return empty_lineage(state=LineageState.EMPTY)

    selected, terminal = _resolve_selected(result, selected_reference)
    if selected is None:
        return empty_lineage(state=terminal or LineageState.SELECTED_UNAVAILABLE)

    by_vid = {version.record.version_id: version for version in result.versions}
    same_family = [
        version
        for version in result.versions
        if version.record.family_id == selected.record.family_id
    ]
    selected_short = selected.display.short_version_id

    parent_version, parent_state = _resolve_parent(selected, by_vid, len(by_vid) + 1)
    root_version, root_state = _resolve_root(selected, same_family)
    child_versions, truncated = _resolve_children(selected, result.versions, max_nodes)

    selected_node = _node(
        selected,
        LineageRelationship.SELECTED,
        selected_short=selected_short,
        active_reference=active_reference,
    )
    root_node = (
        _node(
            root_version,
            LineageRelationship.ROOT,
            selected_short=selected_short,
            active_reference=active_reference,
        )
        if root_version is not None
        else None
    )
    parent_node = (
        _node(
            parent_version,
            LineageRelationship.PARENT,
            selected_short=selected_short,
            active_reference=active_reference,
        )
        if parent_version is not None
        else None
    )
    child_nodes = tuple(
        _node(
            child,
            LineageRelationship.CHILD,
            selected_short=selected_short,
            active_reference=active_reference,
        )
        for child in child_versions
    )

    unavailable = _count(parent_state, _REL_UNAVAILABLE) + _count(root_state, _REL_UNAVAILABLE)
    corrupt = _count(parent_state, _REL_CORRUPT) + _count(root_state, _REL_CORRUPT)
    state = _overall_state(corrupt=corrupt, truncated=truncated)

    return LineageView(
        state=state,
        message=_MESSAGES[state],
        selected=selected_node,
        root=root_node,
        parent=parent_node,
        children=child_nodes,
        unavailable_relatives=unavailable,
        corrupt_relatives=corrupt,
        truncated=truncated,
        text_alternative=_text_alternative(
            selected_node,
            root_node,
            parent_node,
            child_nodes,
            root_state=root_state,
            parent_state=parent_state,
            unavailable=unavailable,
            corrupt=corrupt,
            truncated=truncated,
        ),
    )
