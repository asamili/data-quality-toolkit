from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import Field, field_validator
    from pydantic_settings import BaseSettings, SettingsConfigDict

    V2: bool
else:
    try:
        from pydantic import Field, field_validator  # type: ignore
        from pydantic_settings import BaseSettings, SettingsConfigDict  # type: ignore

        V2 = True
    except Exception:  # pragma: no cover
        from pydantic import BaseSettings, Field  # type: ignore
        from pydantic import validator as field_validator  # type: ignore

        SettingsConfigDict = dict  # type: ignore[assignment]
        V2 = False

__all__ = ["BaseSettings", "SettingsConfigDict", "Field", "field_validator", "V2"]
