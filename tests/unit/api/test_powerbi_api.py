"""G8C3B: public Power BI package API wrapper + result contract.

Proves PowerBIPackageResult and build_powerbi_package are importable from the
shared result-types module, the api seam, and the package root; that the
contract has the exact source-truth keys/types; and that build_powerbi_package
is a behavior-preserving pass-through to the internal exporter. No real Power BI
package is generated (the exporter is monkeypatched).
"""

from __future__ import annotations

import importlib
from typing import Any, get_type_hints

import pytest


def test_contract_importable_from_shared() -> None:
    mod = importlib.import_module("data_quality_toolkit.shared.result_types")
    assert hasattr(mod, "PowerBIPackageResult")
    assert "PowerBIPackageResult" in mod.__all__


def test_contract_importable_from_api() -> None:
    api = importlib.import_module("data_quality_toolkit.api")
    assert hasattr(api, "PowerBIPackageResult")
    assert "PowerBIPackageResult" in api.__all__


def test_contract_importable_from_root() -> None:
    root = importlib.import_module("data_quality_toolkit")
    assert hasattr(root, "PowerBIPackageResult")
    assert "PowerBIPackageResult" in root.__all__


def test_wrapper_importable_from_api() -> None:
    api = importlib.import_module("data_quality_toolkit.api")
    assert hasattr(api, "build_powerbi_package")
    assert "build_powerbi_package" in api.__all__


def test_wrapper_importable_from_root() -> None:
    root = importlib.import_module("data_quality_toolkit")
    assert hasattr(root, "build_powerbi_package")
    assert "build_powerbi_package" in root.__all__


def test_contract_required_keys_and_types() -> None:
    from data_quality_toolkit.shared.result_types import PowerBIPackageResult

    hints = get_type_hints(PowerBIPackageResult)
    assert hints == {
        "package_dir": str,
        "files": dict[str, str],
        "validation": dict[str, Any],
        "time_range": str,
        "base_folder": str,
        "dim_time_path": str,
    }
    # All keys are Required (no NotRequired / optional keys).
    assert PowerBIPackageResult.__required_keys__ == frozenset(hints)
    assert PowerBIPackageResult.__optional_keys__ == frozenset()


def test_wrapper_return_annotation_resolves_to_contract() -> None:
    from data_quality_toolkit.api import build_powerbi_package
    from data_quality_toolkit.shared.result_types import PowerBIPackageResult

    hints = get_type_hints(build_powerbi_package)
    assert hints["return"] is PowerBIPackageResult


def test_wrapper_is_api_level_not_cli() -> None:
    # The public wrapper lives on the api seam, independent of any CLI command.
    from data_quality_toolkit.api import build_powerbi_package

    assert build_powerbi_package.__module__ == "data_quality_toolkit.api"


def test_wrapper_delegates_without_changing_args_or_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import data_quality_toolkit.adapters.exporters.bi.powerbi_exporter as exporter
    from data_quality_toolkit.api import build_powerbi_package

    sentinel: dict[str, Any] = {
        "package_dir": "pkg",
        "files": {"model": "pkg/model.pbit"},
        "validation": {"valid": True, "errors": [], "warnings": []},
        "time_range": "2024-01-01 to 2024-01-31",
        "base_folder": "./dist",
        "dim_time_path": "pkg/time/dim_time.csv",
    }
    captured: dict[str, Any] = {}

    def _fake(
        star_dir: object,
        output_dir: object,
        *,
        time_start: str = "2018-01-01",
        time_end: str = "2030-12-31",
        base_folder: str = "./dist",
        fiscal_year_start: int | None = None,
    ) -> dict[str, Any]:
        captured["args"] = (star_dir, output_dir)
        captured["kwargs"] = {
            "time_start": time_start,
            "time_end": time_end,
            "base_folder": base_folder,
            "fiscal_year_start": fiscal_year_start,
        }
        return sentinel

    monkeypatch.setattr(exporter, "export_powerbi_package", _fake)

    result = build_powerbi_package(
        "star",
        "out",
        time_start="2024-01-01",
        time_end="2024-01-31",
        base_folder="./dist",
        fiscal_year_start=7,
    )

    # Pass-through identity: result shape is unchanged by the wrapper.
    assert result is sentinel
    assert captured["args"] == ("star", "out")
    assert captured["kwargs"] == {
        "time_start": "2024-01-01",
        "time_end": "2024-01-31",
        "base_folder": "./dist",
        "fiscal_year_start": 7,
    }


def test_wrapper_defaults_match_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    import data_quality_toolkit.adapters.exporters.bi.powerbi_exporter as exporter
    from data_quality_toolkit.api import build_powerbi_package

    captured: dict[str, Any] = {}

    def _fake(star_dir: object, output_dir: object, **kw: Any) -> dict[str, Any]:
        captured.update(kw)
        return {
            "package_dir": "p",
            "files": {},
            "validation": {"valid": True},
            "time_range": "x",
            "base_folder": "./dist",
            "dim_time_path": "d",
        }

    monkeypatch.setattr(exporter, "export_powerbi_package", _fake)
    build_powerbi_package("star", "out")
    assert captured == {
        "time_start": "2018-01-01",
        "time_end": "2030-12-31",
        "base_folder": "./dist",
        "fiscal_year_start": None,
    }
