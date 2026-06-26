"""Package entry point and import surface smoke tests.

Validates that the installed package exposes the ``dqt`` console-script entry
point correctly and that the public Python API is importable.
"""

from __future__ import annotations

import importlib.metadata


def test_dqt_console_script_registered() -> None:
    eps = importlib.metadata.entry_points(group="console_scripts")
    names = [ep.name for ep in eps]
    assert "dqt" in names


def test_dqt_entry_point_value() -> None:
    eps = importlib.metadata.entry_points(group="console_scripts")
    dqt_ep = next(ep for ep in eps if ep.name == "dqt")
    assert dqt_ep.value == "data_quality_toolkit.adapters.cli.main:main"


def test_dqt_entry_point_loads_callable() -> None:
    eps = importlib.metadata.entry_points(group="console_scripts")
    dqt_ep = next(ep for ep in eps if ep.name == "dqt")
    func = dqt_ep.load()
    assert callable(func)


def test_package_version_readable() -> None:
    version = importlib.metadata.version("data-quality-toolkit")
    assert version


def test_public_api_importable() -> None:
    import data_quality_toolkit.api as api_mod

    assert callable(api_mod.profile_csv)
    assert callable(api_mod.assess_csv)
    assert callable(api_mod.export_csv)
    assert callable(api_mod.detect_drift)
    assert callable(api_mod.create_manifest)
