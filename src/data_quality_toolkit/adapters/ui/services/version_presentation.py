"""One shared, pure presentation of a shortened managed-version identity.

Every lifecycle surface that shows a *shortened* managed version reads its label
from here, so two surfaces describing the same version can never disagree about
its spelling. The module is deliberately dependency-free — standard library only,
no IO, no session state, no Streamlit, no pandas — which lets the service layer
and the component layer share one function without inverting the established
``components -> services`` import direction.

Presentation contracts encoded here:

* A short label is presentation, never identity. Nothing here is persisted,
  compared against a stored value, or written to a sidecar, and no argument is
  mutated: the input string is read and a new string is returned.
* The canonical short token is the first eight hexadecimal characters of the
  UUID-normalized version id, and the ``v-`` prefix is added exactly once — by
  this module, never by a caller.
* An absent, malformed, or otherwise unusable version id yields ``""`` so a
  caller degrades to its own neutral label rather than echoing an unexpected
  value or raising from a render path.
"""

from __future__ import annotations

import uuid

__all__ = [
    "SHORT_VERSION_HEX_CHARS",
    "SHORT_VERSION_PREFIX",
    "format_short_version",
]

SHORT_VERSION_PREFIX = "v-"
SHORT_VERSION_HEX_CHARS = 8


def format_short_version(version_id: str | None) -> str:
    """Return ``v-<first 8 hex chars>`` for a UUID, or ``""`` when unusable.

    Pure and deterministic: the id is normalized through :class:`uuid.UUID`,
    which strips hyphens and lowercases, before shortening — so every spelling of
    one identity produces one byte-identical label. Anything that is not a
    parsable UUID yields an empty string; presentation degrades rather than
    leaking an unexpected value into a page.
    """
    raw = str(version_id or "").strip()
    if not raw:
        return ""
    try:
        normalized = uuid.UUID(raw).hex
    except (AttributeError, TypeError, ValueError):
        return ""
    return f"{SHORT_VERSION_PREFIX}{normalized[:SHORT_VERSION_HEX_CHARS]}"
