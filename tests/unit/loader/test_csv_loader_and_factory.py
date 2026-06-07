# tests/unit/loaders/test_csv_loader_and_factory.py
from __future__ import annotations

import pytest

from data_quality_toolkit.adapters.loaders.data_loader_registry import (
    get_registered_loader,
    register_loader,
)
from data_quality_toolkit.adapters.loaders.file.csv_loader import CsvLoader
from data_quality_toolkit.adapters.loaders.loader_factory import get_loader


def test_loader_factory_returns_csv():
    loader = get_loader("csv")
    assert isinstance(loader, CsvLoader)
    with pytest.raises(ValueError):
        get_loader("unknown")


def test_registry_register_and_get():
    class DummyLoader(CsvLoader): ...

    register_loader("dummy", DummyLoader)
    assert get_registered_loader("dummy") is DummyLoader
    with pytest.raises(KeyError):
        get_registered_loader("nope")
    assert get_registered_loader("dummy") is DummyLoader
    with pytest.raises(KeyError):
        get_registered_loader("nope")
