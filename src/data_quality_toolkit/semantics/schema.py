"""Phase 3: KPI schema definitions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Type aliases
Grain = Literal["global", "dataset", "table", "column", "time"]
Unit = Literal["count", "percent", "ratio", "currency", "score", "days", "hours"]


class KPI(BaseModel):
    """Key Performance Indicator definition."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,  # trims incoming strings
    )

    id: str = Field(..., description="Unique identifier for the KPI")
    title: str = Field(..., description="Display name for the KPI")
    expression: str = Field(..., description="DAX expression text")
    grain: Grain = Field(..., description="Granularity level")
    unit: Unit = Field(..., description="Unit of measurement")
    scale: float = Field(default=1.0, description="Scaling factor")
    depends_on: list[str] = Field(
        default_factory=list, description="KPI dependencies (other KPI IDs)"
    )
    description: str | None = Field(None, description="Optional description")
    format_string: str | None = Field(None, description="DAX format string")
    hidden: bool = Field(default=False, description="Hide from UI")


class Catalog(BaseModel):
    """Collection of KPI definitions."""

    model_config = ConfigDict(extra="forbid")

    kpis: list[KPI] = Field(..., description="List of KPI definitions")
    version: str = Field(default="1.0.0", description="Catalog version")
    description: str | None = Field(None, description="Catalog description")

    def get_kpi(self, kpi_id: str) -> KPI | None:
        """Get KPI by ID (None if missing)."""
        return next((k for k in self.kpis if k.id == kpi_id), None)

    @property
    def kpi_ids(self) -> set[str]:
        """All KPI IDs."""
        return {k.id for k in self.kpis}
