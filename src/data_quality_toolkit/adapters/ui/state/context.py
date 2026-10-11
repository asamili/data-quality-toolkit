"""Lightweight shared dataset context backed by Streamlit session state."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT


@dataclass(frozen=True, slots=True)
class DatasetContext:
    """Safe metadata identifying the dataset selected for the UI journey.

    The context intentionally contains no DataFrame, profile, assessment, raw
    rows, or derived statistics. Those remain owned by existing page services.

    Lifecycle fields are additive and default to legacy/unmanaged semantics so
    every existing constructor and legacy workflow stays compatible. A managed
    context sets ``managed=True`` and carries the version/family/content
    identities of a processed dataset version (see
    ``adapters.ui.services.dataset_versions``). ``fingerprint`` is deliberately
    left path-only (the legacy contract); version-aware change detection uses
    the separate :attr:`binding_identity`. Validated construction and atomic
    activation/invalidation live in ``adapters.ui.services.dataset_activation``.
    """

    source_path: str
    display_name: str
    size_bytes: int
    modified_ns: int
    large_file_mode: bool = False
    managed: bool = False
    version_id: str | None = None
    family_id: str | None = None
    content_id: str | None = None
    root_content_id: str | None = None
    parent_version_id: str | None = None
    version_label: str | None = None

    @property
    def fingerprint(self) -> tuple[str, int, int, bool]:
        """Return the legacy path-identity used to detect context changes.

        Deliberately identity-by-path and unchanged from the legacy contract;
        lifecycle fields do not participate. Version-aware comparison uses
        :attr:`binding_identity`.
        """
        return (self.source_path, self.size_bytes, self.modified_ns, self.large_file_mode)

    @property
    def binding_identity(self) -> tuple[bool, str | None, str | None, str, int, int, bool]:
        """Return the version-aware binding used for transition comparison.

        Extends the path fingerprint with lifecycle-distinguishing fields so a
        transition recognizes legacy-versus-managed contexts, different managed
        version IDs, and different content IDs as distinct datasets, in addition
        to a changed path, size, modification time, or large-file mode. A
        transition is unchanged only when the complete binding matches.
        """
        return (
            self.managed,
            self.version_id,
            self.content_id,
            self.source_path,
            self.size_bytes,
            self.modified_ns,
            self.large_file_mode,
        )


def get_dataset_context(state: Mapping[str, Any]) -> DatasetContext | None:
    """Return the active typed context, ignoring malformed session values."""
    value = state.get(DATASET_CONTEXT)
    return value if isinstance(value, DatasetContext) else None


def set_dataset_context(state: MutableMapping[str, Any], context: DatasetContext) -> bool:
    """Set the active context via the atomic dataset-transition service.

    Thin compatibility wrapper over
    :func:`...services.dataset_activation.activate_dataset_context` so there is a
    single transition algorithm. Returns ``True`` when the version-aware dataset
    binding changed and dataset-derived state was invalidated. Imported locally
    to avoid an import cycle (the service imports this module).
    """
    from data_quality_toolkit.adapters.ui.services.dataset_activation import (
        activate_dataset_context,
    )

    return activate_dataset_context(state, context).changed


def clear_dataset_context(state: MutableMapping[str, Any]) -> bool:
    """Clear the active context and all dataset-derived state (atomic).

    Thin compatibility wrapper over the shared transition service; unrelated
    session keys are preserved and a mutation failure rolls back. Returns
    ``True`` when an active typed context existed. Imported locally to avoid an
    import cycle.
    """
    from data_quality_toolkit.adapters.ui.services.dataset_activation import (
        clear_dataset_context as _clear_dataset_context,
    )

    return _clear_dataset_context(state)
