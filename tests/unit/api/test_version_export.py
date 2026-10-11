"""Verify __version__ is exported and consistent with package metadata."""

from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path


def test_version_exported() -> None:
    import data_quality_toolkit as d

    assert hasattr(d, "__version__"), "__version__ not exported from package"
    assert isinstance(d.__version__, str)
    assert d.__version__ != "NO_VERSION"


def test_version_matches_metadata() -> None:
    import data_quality_toolkit as d

    meta_version = importlib.metadata.version("data-quality-toolkit")
    assert d.__version__ == meta_version


def test_pyproject_version_aligned_to_release() -> None:
    """Source package metadata is aligned to the v2.10.0 release."""
    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    with pyproject.open("rb") as f:
        data = tomllib.load(f)

    assert data["project"]["version"] == "2.10.0"
