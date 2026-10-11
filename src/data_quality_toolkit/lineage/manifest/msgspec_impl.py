from __future__ import annotations

from typing import Any

from data_quality_toolkit.lineage.manifest.schemas import Manifest
from data_quality_toolkit.shared.exceptions import DQTError

__all__ = ["MsgspecSerdeError", "MsgspecSerializer"]

_MSGSPEC_HINT = (
    "msgspec is not installed; install the serde extra: pip install data-quality-toolkit[serde]"
)


class MsgspecSerdeError(DQTError):
    """Raised when the msgspec manifest serializer cannot be used."""


def _import_msgspec() -> Any:
    """Return the msgspec module, or raise MsgspecSerdeError with an install hint.

    Isolated so callers and tests can simulate the missing-dependency path
    without installing or uninstalling msgspec. Only msgspec's *own* absence is
    converted: a ModuleNotFoundError naming a different module -- a dependency
    missing inside an installed msgspec -- is re-raised unchanged, as is every
    other error raised while importing it, so genuine breakage stays visible
    instead of being reported as a missing optional dependency.
    """
    try:
        import msgspec
    except ModuleNotFoundError as exc:
        if exc.name != "msgspec":
            raise
        raise MsgspecSerdeError(_MSGSPEC_HINT, hint=_MSGSPEC_HINT) from exc
    return msgspec


class MsgspecSerializer:
    """Serialize/deserialize Manifest using msgspec json for speed."""

    def __init__(self) -> None:
        msgspec = _import_msgspec()
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
