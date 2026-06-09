from __future__ import annotations

from typing import Any

import msgspec

from data_quality_toolkit.lineage.manifest.schemas import Manifest


class MsgspecSerializer:
    """Serialize/deserialize Manifest using msgspec json for speed."""

    def __init__(self) -> None:
        self._enc = msgspec.json.Encoder()
        self._dec = msgspec.json.Decoder(Any)

    def serialize(self, manifest: Manifest) -> bytes:
        # Use Pydantic to produce a JSON-compatible dict, then msgspec for fast encoding.
        payload = manifest.model_dump(mode="json")
        result: bytes = self._enc.encode(payload)
        return result

    def deserialize(self, data: bytes) -> Manifest:
        obj = self._dec.decode(data)
        result: Manifest = Manifest.model_validate(obj)
        return result
