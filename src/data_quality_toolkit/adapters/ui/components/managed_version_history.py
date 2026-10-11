"""Framework-thin renderer for the Start-page managed-version history section.

Presentation only: it accepts the ``st`` module (or a lightweight test double) as
its first argument and the single safe projected view type as its second, and it
renders captions, read-only summary lines, and one explicit Set Active control
per displayed valid version. It computes no metrics, performs no I/O, imports no
Streamlit, reads or writes no session state, constructs no ``DatasetContext``,
and never reopens, activates, deletes, relabels, or repairs anything itself.

Reopen contract: the renderer's only output is the privacy-safe action reference
(the collision-safe projected short version id) of the one valid row whose Set
Active control was explicitly clicked, or ``None``. Issue, duplicate, and
omitted rows expose no action. Widget keys are derived only from that same
privacy-safe short id. The renderer never receives, retains, logs, serializes,
or interpolates a discovery object, record, locator, path, filename, full
identifier, hash, or raw exception — resolution and activation live entirely in
the dedicated reopen service invoked by the page.
"""

from __future__ import annotations

from typing import Any

from data_quality_toolkit.adapters.ui.services.managed_version_history import (
    ManagedVersionDuplicateRow,
    ManagedVersionHistoryRow,
    ManagedVersionHistoryView,
    ManagedVersionIssueRow,
)
from data_quality_toolkit.adapters.ui.services.managed_version_lineage import (
    LineageNode,
    LineageView,
)

SECTION_TITLE = "Managed version history"
LINEAGE_TITLE = "Direct lineage"

SET_ACTIVE_HELP = (
    "Explicitly reopens this managed version as the active dataset after fresh "
    "validation. Nothing is activated without this click."
)

_VALID_HEADING = "Recent valid versions"
_ISSUE_HEADING = "Records needing attention"
_DUPLICATE_HEADING = "Quarantined duplicate groups"


def render_managed_version_history(st: Any, view: ManagedVersionHistoryView) -> str | None:
    """Render the history section and emit at most one explicit action reference.

    ``view`` is the only permitted input type: a ``ManagedVersionHistoryView``
    produced by the safe projector. A complete discovery object is never rendered.
    Returns the privacy-safe action reference (the row's collision-safe short
    version id) only when exactly one Set Active control reports an explicit
    click this run; plain rendering, issue/duplicate rows, and any ambiguous
    multi-click state all return ``None``. The renderer itself mutates nothing.
    """
    _heading(st, SECTION_TITLE)
    if view.message:
        st.caption(view.message)
    if not view.scanned:
        return None
    st.caption(
        f"Valid versions: {view.valid_total} · Issues: {view.issue_total} · "
        f"Quarantined duplicate groups: {view.duplicate_total}"
    )
    clicked_reference = _render_valid_rows(st, view)
    _render_issue_rows(st, view)
    _render_duplicate_rows(st, view)
    return clicked_reference


def _render_valid_rows(st: Any, view: ManagedVersionHistoryView) -> str | None:
    if not view.valid_rows:
        return None
    st.caption(_VALID_HEADING)
    clicked: list[str] = []
    for row in view.valid_rows:
        if _render_valid_row(st, row):
            clicked.append(row.short_version_id)
    _render_omitted(st, view.valid_omitted, "versions")
    # Exactly one explicit click resolves to a reference; zero or an ambiguous
    # multi-click state fails closed to None.
    if len(clicked) == 1:
        return clicked[0]
    return None


def _render_valid_row(st: Any, row: ManagedVersionHistoryRow) -> bool:
    _write(st, f"**{row.label}** · `{row.short_version_id}`")
    st.caption(
        f"{row.creation_mechanism} · {row.family_summary} · {row.parent_summary} · "
        f"Confirmed {row.confirmation_timestamp} · {row.csv_availability} · "
        f"{row.recipe_availability}"
    )
    # The widget key embeds only the privacy-safe, collision-safe short id. The
    # renderer reports the click; it never activates or writes state itself.
    return bool(
        st.button(
            row.action_label,
            key=f"mvh_set_active_{row.short_version_id}",
            help=SET_ACTIVE_HELP,
        )
    )


def _render_issue_rows(st: Any, view: ManagedVersionHistoryView) -> None:
    if not view.issue_rows:
        return
    st.caption(_ISSUE_HEADING)
    for row in view.issue_rows:
        _render_issue_row(st, row)
    _render_omitted(st, view.issue_omitted, "records")


def _render_issue_row(st: Any, row: ManagedVersionIssueRow) -> None:
    st.caption(f"{row.reference} · {row.status_label} · {row.label} · {row.reason_code}")


def _render_duplicate_rows(st: Any, view: ManagedVersionHistoryView) -> None:
    if not view.duplicate_rows:
        return
    st.caption(_DUPLICATE_HEADING)
    for row in view.duplicate_rows:
        _render_duplicate_row(st, row)
    _render_omitted(st, view.duplicate_omitted, "duplicate groups")


def _render_duplicate_row(st: Any, row: ManagedVersionDuplicateRow) -> None:
    short = row.short_version_id or "(id unavailable)"
    members = ", ".join(row.member_references)
    st.caption(
        f"{row.kind_label} · {short} · {row.member_count} members · {row.status_label} · {members}"
    )


def _render_omitted(st: Any, omitted: int, noun: str) -> None:
    if omitted > 0:
        st.caption(f"… and {omitted} more {noun} not shown.")


def _heading(st: Any, text: str) -> None:
    subheader = getattr(st, "subheader", None)
    if callable(subheader):
        subheader(text)
        return
    st.caption(text)


def _write(st: Any, text: str) -> None:
    writer = getattr(st, "write", None)
    if callable(writer):
        writer(text)
        return
    st.caption(text)


# --- Direct-lineage section ------------------------------------------------
#
# Presentation only: a compact, textual/structured direct-lineage list for the
# currently selected managed version. It renders the safe ``LineageView`` and
# nothing else — no discovery object, record, path, identifier, hash, or recipe.
# It adds no button, activation, reopen, deletion, relabel, repair, or graph
# mutation: the only explicit action remains the Set Active control above.
# Every relationship is labelled with text (not colour alone) and a complete
# text alternative is always emitted for non-visual users.

_LINEAGE_ROOT_LABEL = "Root"
_LINEAGE_PARENT_LABEL = "Direct parent"
_LINEAGE_SELECTED_LABEL = "Selected version"
_LINEAGE_CHILD_LABEL = "Child"
_LINEAGE_EMPTY_HINT = "Select a managed version to view its direct lineage."


def render_managed_version_lineage(st: Any, lineage: LineageView) -> None:
    """Render the compact, read-only direct-lineage section for the selection.

    ``lineage`` is the only permitted input: a ``LineageView`` produced by the
    safe lineage projector. The renderer computes nothing, performs no I/O,
    reads or writes no session state, and never activates or mutates anything.
    Absent or non-resolvable selections render a safe message plus the complete
    text alternative and stop.
    """
    _heading(st, LINEAGE_TITLE)
    st.caption(lineage.message)
    if lineage.selected is None:
        st.caption(_LINEAGE_EMPTY_HINT)
        st.caption(f"Lineage summary: {lineage.text_alternative}")
        return
    _render_lineage_relations(st, lineage)
    _render_lineage_children(st, lineage)
    _render_lineage_summary(st, lineage)
    # Always emit the full, non-visual text alternative last.
    st.caption(f"Lineage summary: {lineage.text_alternative}")


def _lineage_markers(node: LineageNode) -> str:
    markers: list[str] = []
    if node.is_active:
        markers.append("active")
    if node.is_selected:
        markers.append("selected")
    return f" [{', '.join(markers)}]" if markers else ""


def _lineage_node_line(prefix: str, node: LineageNode) -> str:
    return (
        f"{prefix}: **{node.label}** · `{node.short_version_id}`{_lineage_markers(node)} · "
        f"{node.family_summary} · {node.status_label} · Created {node.created_at}"
    )


def _render_lineage_relations(st: Any, lineage: LineageView) -> None:
    if lineage.root is not None:
        _write(st, _lineage_node_line(_LINEAGE_ROOT_LABEL, lineage.root))
    else:
        st.caption(f"{_LINEAGE_ROOT_LABEL}: unavailable.")
    if lineage.parent is not None:
        _write(st, _lineage_node_line(_LINEAGE_PARENT_LABEL, lineage.parent))
    else:
        st.caption(f"{_LINEAGE_PARENT_LABEL}: none or unavailable.")
    if lineage.selected is not None:
        _write(st, _lineage_node_line(_LINEAGE_SELECTED_LABEL, lineage.selected))


def _render_lineage_children(st: Any, lineage: LineageView) -> None:
    if not lineage.children:
        st.caption("Direct children: none.")
        return
    st.caption(f"Direct children: {len(lineage.children)}")
    for child in lineage.children:
        _write(st, _lineage_node_line(_LINEAGE_CHILD_LABEL, child))
    if lineage.truncated:
        st.caption("… some direct children are not listed.")


def _render_lineage_summary(st: Any, lineage: LineageView) -> None:
    bits: list[str] = []
    if lineage.unavailable_relatives:
        bits.append(f"{lineage.unavailable_relatives} unavailable")
    if lineage.corrupt_relatives:
        bits.append(f"{lineage.corrupt_relatives} could not be verified")
    if lineage.truncated:
        bits.append("children truncated")
    if bits:
        st.caption("Relationship notes: " + " · ".join(bits) + ".")
