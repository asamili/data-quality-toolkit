# src/data_quality_toolkit/loaders/data_loader_registry.py
"""Phase 1: Loader registry (stub for future expansion)."""

from data_quality_toolkit.adapters.loaders.base_loader import BaseLoader

__all__ = ["register_loader", "get_registered_loader"]

_registry: dict[str, type[BaseLoader]] = {}


def register_loader(name: str, loader_class: type[BaseLoader]) -> None:
    _registry[name] = loader_class


def get_registered_loader(name: str) -> type[BaseLoader]:
    if name not in _registry:
        raise KeyError(f"No loader registered for: {name}")
    return _registry[name]
