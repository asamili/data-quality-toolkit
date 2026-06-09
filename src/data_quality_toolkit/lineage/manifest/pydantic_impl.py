from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import orjson
else:
    try:
        import orjson
    except Exception:  # pragma: no cover
        orjson = None

from data_quality_toolkit.lineage.manifest.schemas import Manifest


class PydanticSerializer:
    """Serialize/deserialize Manifest using Pydantic + json/orjson."""

    def __init__(self, use_orjson: bool = False) -> None:
        self._use_orjson = bool(use_orjson and orjson is not None)

    def serialize(self, manifest: Manifest) -> bytes:
        # Convert to builtins first so both backends share the same payload.
        payload = json.loads(manifest.model_dump_json())
        if self._use_orjson and orjson:
            result: bytes = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
            return result
        return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")

    def deserialize(self, data: bytes) -> Manifest:
        obj: Any
        if self._use_orjson and orjson:
            obj = orjson.loads(data)
        else:
            obj = json.loads(data)
        result: Manifest = Manifest.model_validate(obj)
        return result
