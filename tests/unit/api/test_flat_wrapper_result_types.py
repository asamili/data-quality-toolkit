"""DQT-UX-G8C2E: flat result contracts for BI-export and notification wrappers.

Proves the four flat TypedDicts (DriftHistoryXlsxExportResult,
MonitoringDuckdbExportResult, DriftPlotsExportResult, DriftNotificationSendResult)
are importable from the package root, the ``data_quality_toolkit.api`` seam, and
``shared.result_types``; are listed in each public ``__all__``; carry exactly the
required keys with no ``NotRequired`` (all flat, single-shape); and that
DriftNotificationSendResult pins ``status`` as ``int | None`` and ``payload`` as
``dict[str, Any]``.

These are export-only static contracts: the wrapper functions still return plain
dicts at runtime — no behavior change.
"""

from __future__ import annotations

import importlib
import typing
from typing import Any, get_type_hints

import pytest

_FLAT_RESULT_TYPES = [
    "DriftHistoryXlsxExportResult",
    "MonitoringDuckdbExportResult",
    "DriftPlotsExportResult",
    "DriftNotificationSendResult",
]

_EXPECTED_KEYS = {
    "DriftHistoryXlsxExportResult": {"output_path", "sheets", "row_counts"},
    "MonitoringDuckdbExportResult": {
        "input_db_path",
        "output_path",
        "tables",
        "row_counts",
        "overwritten",
    },
    "DriftPlotsExportResult": {"output_dir", "charts", "row_counts"},
    "DriftNotificationSendResult": {
        "payload",
        "sent",
        "status",
        "breached",
        "redacted_url",
    },
}


# --------------------------------------------------------------------------
# Export-surface checks: importable + in __all__ from all three paths.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", _FLAT_RESULT_TYPES)
def test_flat_type_importable_from_root(name: str) -> None:
    root = importlib.import_module("data_quality_toolkit")
    assert hasattr(root, name), f"{name} missing from data_quality_toolkit"
    assert name in root.__all__, f"{name} missing from data_quality_toolkit.__all__"


@pytest.mark.parametrize("name", _FLAT_RESULT_TYPES)
def test_flat_type_importable_from_api_seam(name: str) -> None:
    api = importlib.import_module("data_quality_toolkit.api")
    assert hasattr(api, name), f"{name} missing from data_quality_toolkit.api"
    assert name in api.__all__, f"{name} missing from data_quality_toolkit.api.__all__"


@pytest.mark.parametrize("name", _FLAT_RESULT_TYPES)
def test_flat_type_importable_from_shared(name: str) -> None:
    mod = importlib.import_module("data_quality_toolkit.shared.result_types")
    assert hasattr(mod, name), f"{name} missing from shared.result_types"
    assert name in mod.__all__, f"{name} missing from shared.result_types.__all__"


@pytest.mark.parametrize("name", _FLAT_RESULT_TYPES)
def test_flat_type_same_object_from_all_paths(name: str) -> None:
    root = importlib.import_module("data_quality_toolkit")
    api = importlib.import_module("data_quality_toolkit.api")
    shared = importlib.import_module("data_quality_toolkit.shared.result_types")
    assert getattr(root, name) is getattr(api, name) is getattr(shared, name)


# --------------------------------------------------------------------------
# Exact key-set contracts: TypedDict annotations == required keys.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", _FLAT_RESULT_TYPES)
def test_flat_type_exact_keys(name: str) -> None:
    mod = importlib.import_module("data_quality_toolkit.shared.result_types")
    cls = getattr(mod, name)
    assert set(cls.__annotations__) == _EXPECTED_KEYS[name]


@pytest.mark.parametrize("name", _FLAT_RESULT_TYPES)
def test_flat_type_all_keys_required(name: str) -> None:
    # Flat contracts use no NotRequired — every key is required.
    mod = importlib.import_module("data_quality_toolkit.shared.result_types")
    cls = getattr(mod, name)
    assert cls.__required_keys__ == frozenset(_EXPECTED_KEYS[name])
    assert cls.__optional_keys__ == frozenset()


# --------------------------------------------------------------------------
# DriftNotificationSendResult type pins.
# --------------------------------------------------------------------------
def test_notification_status_is_int_or_none() -> None:
    from data_quality_toolkit.shared.result_types import DriftNotificationSendResult

    hints = get_type_hints(DriftNotificationSendResult)
    status = hints["status"]
    assert typing.get_origin(status) in (
        typing.Union,
        getattr(__import__("types"), "UnionType", None),
    )
    assert set(typing.get_args(status)) == {int, type(None)}


def test_notification_payload_is_dict_str_any() -> None:
    from data_quality_toolkit.shared.result_types import DriftNotificationSendResult

    hints = get_type_hints(DriftNotificationSendResult)
    payload = hints["payload"]
    assert typing.get_origin(payload) is dict
    assert typing.get_args(payload) == (str, Any)
