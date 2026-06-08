"""Verify __version__ is exported and consistent with package metadata."""

from __future__ import annotations

import importlib.metadata


def test_version_exported() -> None:
    import data_quality_toolkit as d

    assert hasattr(d, "__version__"), "__version__ not exported from package"
    assert isinstance(d.__version__, str)
    assert d.__version__ != "NO_VERSION"


def test_version_matches_metadata() -> None:
    import data_quality_toolkit as d

    meta_version = importlib.metadata.version("data-quality-toolkit")
    assert d.__version__ == meta_version


def test_version_is_2_0_0() -> None:
    import data_quality_toolkit as d

    assert d.__version__ == "2.1.0"
