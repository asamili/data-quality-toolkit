from __future__ import annotations

from typing import Protocol

from data_quality_toolkit.lineage.manifest.schemas import Manifest

# ↓ use the instance so monkeypatching works
from data_quality_toolkit.shared.settings import settings as DQT_SETTINGS  # noqa: N812


class _Serializer(Protocol):
    def serialize(self, manifest: Manifest) -> bytes: ...

    def deserialize(self, data: bytes) -> Manifest: ...


class ManifestSerializer:
    def __init__(self) -> None:
        if DQT_SETTINGS.serde_impl == "msgspec":
            from .msgspec_impl import MsgspecSerializer

            self._impl: _Serializer = MsgspecSerializer()
        else:
            from .pydantic_impl import PydanticSerializer

            self._impl = PydanticSerializer(use_orjson=(DQT_SETTINGS.json_writer == "orjson"))

    def to_json(self, manifest: Manifest) -> bytes:
        return self._impl.serialize(manifest)

    def from_json(self, data: bytes) -> Manifest:
        return self._impl.deserialize(data)
