"""Shared fixtures for the recipe-reload contracts.

Every fixture builds a *real* confirmed managed version on a pytest ``tmp_path``
by driving the accepted confirmation service, so the reload path is exercised
against genuine sidecars, CSVs, and recipe artifacts rather than synthetic
doubles. No real operator workspace, dataset, recipe, or export is ever read.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from data_quality_toolkit.adapters.ui.services.dataset_confirmation import (
    ConfirmationStatus,
    confirm_processed_version,
)
from data_quality_toolkit.adapters.ui.services.dataset_versions import DatasetVersionRecord
from data_quality_toolkit.adapters.ui.services.managed_recipe_reprocessing import (
    derive_action_reference,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.application.workflow.preprocessing import (
    make_recipe_step,
    recipe_to_json_payload,
)

_PARENT_CSV = b"n,c\n1,a\n2,a\n2,b\n3,b\n"
_CHILD_CSV = b"n,c\n10,a\n20,b\n"


def _default_recipe() -> dict[str, Any]:
    steps = [
        make_recipe_step("scaling", ["n"], {"strategy": "minmax"}),
        make_recipe_step("drop_duplicates", [], {}),
    ]
    return recipe_to_json_payload(steps, None)


@dataclass(frozen=True, slots=True)
class ConfirmedFixture:
    """A confirmed managed version and everything needed to reload it."""

    root: Path
    record: DatasetVersionRecord
    action_reference: str
    csv_path: Path
    recipe_path: Path
    sidecar_path: Path
    recipe_payload: dict[str, Any]

    def recipe_bytes(self) -> bytes:
        return self.recipe_path.read_bytes()


def _confirm_into(
    root: Path,
    *,
    recipe: dict[str, Any],
    csv_bytes: bytes,
    label: str,
    stem: str,
) -> ConfirmedFixture:
    parent_file = root / "source.csv"
    parent_file.write_bytes(_PARENT_CSV)
    parent = DatasetContext(
        source_path=str(parent_file),
        display_name=stem,
        size_bytes=len(_PARENT_CSV),
        modified_ns=1,
    )
    result = confirm_processed_version(
        workspace_root=str(root),
        csv_bytes=csv_bytes,
        recipe=recipe,
        parent=parent,
        label=label,
        filename_stem=stem,
    )
    assert result.status is ConfirmationStatus.CONFIRMED, result.message
    assert result.record is not None
    return ConfirmedFixture(
        root=root,
        record=result.record,
        action_reference=derive_action_reference(version_id=result.record.version_id),
        csv_path=root / Path(result.csv_relative_path),
        recipe_path=root / Path(result.recipe_relative_path),
        sidecar_path=root / Path(result.sidecar_relative_path),
        recipe_payload=recipe,
    )


@pytest.fixture
def confirmed_recipe(tmp_path: Path) -> ConfirmedFixture:
    """A single, fully valid confirmed version ready to reload."""
    root = tmp_path / "ws"
    root.mkdir()
    return _confirm_into(
        root,
        recipe=_default_recipe(),
        csv_bytes=_CHILD_CSV,
        label="cleaned v1",
        stem="orders",
    )


@pytest.fixture
def make_confirmed(tmp_path: Path) -> Any:
    """Factory building a confirmed version with caller-chosen recipe/label/stem."""
    counter = {"n": 0}

    def build(
        *,
        recipe: dict[str, Any] | None = None,
        csv_bytes: bytes = _CHILD_CSV,
        label: str = "cleaned",
        stem: str = "orders",
    ) -> ConfirmedFixture:
        counter["n"] += 1
        root = tmp_path / f"ws{counter['n']}"
        root.mkdir()
        return _confirm_into(
            root,
            recipe=recipe if recipe is not None else _default_recipe(),
            csv_bytes=csv_bytes,
            label=label,
            stem=stem,
        )

    return build
