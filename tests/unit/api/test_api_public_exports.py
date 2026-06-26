"""G8C1: additive public-export surface + StorageError exception-family fix.

Proves the threshold evaluators, the monitoring view-model symbols, and the
public exception family are importable from BOTH the package root
(``data_quality_toolkit``) and the canonical ``data_quality_toolkit.api`` seam,
and that ``StorageError`` is now part of the ``DQTError`` family.
"""

from __future__ import annotations

import importlib

import pytest

_EVALUATORS = ["evaluate_drift_rate_threshold", "evaluate_psi_threshold"]

_VIEW_MODEL = [
    "MonitoringOverview",
    "TrendSummary",
    "RunRow",
    "ColumnDrift",
    "DistributionBin",
    "RunDetail",
    "build_monitoring_overview",
    "list_run_rows",
    "build_column_drift",
    "build_distribution_series",
    "build_run_detail",
]

_EXCEPTIONS = [
    "DQTError",
    "LoaderError",
    "ValidationError",
    "ConfigError",
    "ProfileError",
    "AssessmentError",
    "NotificationError",
    "WebhookSecurityError",
    "StorageError",
]


@pytest.mark.parametrize("name", _EVALUATORS + _VIEW_MODEL + _EXCEPTIONS)
def test_symbol_importable_from_root(name: str) -> None:
    root = importlib.import_module("data_quality_toolkit")
    assert hasattr(root, name), f"{name} missing from data_quality_toolkit"
    assert name in root.__all__, f"{name} missing from data_quality_toolkit.__all__"


@pytest.mark.parametrize("name", _EVALUATORS + _VIEW_MODEL + _EXCEPTIONS)
def test_symbol_importable_from_api_seam(name: str) -> None:
    api = importlib.import_module("data_quality_toolkit.api")
    assert hasattr(api, name), f"{name} missing from data_quality_toolkit.api"
    assert name in api.__all__, f"{name} missing from data_quality_toolkit.api.__all__"


def test_evaluators_are_the_same_object_from_both_paths() -> None:
    import data_quality_toolkit as root
    import data_quality_toolkit.api as api

    assert root.evaluate_drift_rate_threshold is api.evaluate_drift_rate_threshold
    assert root.evaluate_psi_threshold is api.evaluate_psi_threshold


def test_evaluators_callable_and_pure() -> None:
    from data_quality_toolkit import evaluate_drift_rate_threshold, evaluate_psi_threshold

    rate = evaluate_drift_rate_threshold({"drift_rate": 0.4}, max_drift_rate=0.3)
    assert rate == {"breached": True, "drift_rate": 0.4, "threshold": 0.3}

    psi = evaluate_psi_threshold([{"column_name": "amount", "psi": 0.27}], max_psi=0.2)
    assert psi["breached"] is True
    assert psi["offenders"] == [{"column_name": "amount", "psi": 0.27}]


def test_storage_error_is_dqt_error_subclass() -> None:
    from data_quality_toolkit import DQTError, StorageError

    assert issubclass(StorageError, DQTError)


def test_storage_error_caught_by_dqt_error() -> None:
    from data_quality_toolkit import DQTError, StorageError

    with pytest.raises(DQTError):
        raise StorageError("db read failed")


def test_storage_error_still_catchable_directly_and_preserves_message() -> None:
    from data_quality_toolkit import StorageError

    with pytest.raises(StorageError) as excinfo:
        raise StorageError("boom")
    assert "boom" in str(excinfo.value)


def test_storage_error_identity_across_definition_and_seam() -> None:
    from data_quality_toolkit import StorageError as RootStorageError
    from data_quality_toolkit.adapters.storage.connection import StorageError as DefStorageError

    assert RootStorageError is DefStorageError
