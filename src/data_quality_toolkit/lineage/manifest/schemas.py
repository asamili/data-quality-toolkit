"""Manifest schemas for Phase 10 artifact tracking."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DatasetKind = Literal["bronze", "silver", "gold", "sanity", "reprocess"]
ArtifactKind = Literal[
    "star",
    "pbi_package",
    "report",  # ← include report so manifest matches lineage/verifier
    "dax",
    "roles",
    "parameters",
    "sanity_report",
    "manifest",
]


class Schema(BaseModel):
    """Dataset schema information."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    columns: list[str] = Field(default_factory=list)
    dtypes: dict[str, str] = Field(default_factory=dict)


class Dataset(BaseModel):
    """Dataset metadata in manifest."""

    # populate_by_name lets callers still pass `schema=` in kwargs if they want.
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)
    kind: DatasetKind
    path: str
    content_hash: str = Field("", description="sha256:… or empty if unknown")
    bytes: int = 0
    rows: int = 0
    # Avoid clashing with BaseModel.schema()
    schema_: Schema = Field(
        default_factory=Schema,
        serialization_alias="schema",
        validation_alias="schema",
    )
    exists: bool = True


class Artifact(BaseModel):
    """Artifact metadata in manifest."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    kind: ArtifactKind
    path: str
    media_type: str = "application/octet-stream"
    bytes: int = 0
    meta: dict[str, object] = Field(default_factory=dict)
    exists: bool = True


class StepSummary(BaseModel):
    """Summary of step execution."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0


class Summary(BaseModel):
    """Run summary statistics."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    steps: StepSummary = Field(default_factory=StepSummary)
    rows_in: int = 0
    rows_out: int = 0
    bytes_total: int = 0
    health: float | None = None


class GateFailure(BaseModel):
    """Gate failure details."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    phase: Literal["pre", "post", "publish"]
    code: str
    severity: Literal["warn", "error"]
    details: dict[str, object] = Field(default_factory=dict)
    timestamp: datetime


class Gates(BaseModel):
    """Gate execution results."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    status: Literal["passed", "failed", "skipped"] = "skipped"
    failures: list[GateFailure] = Field(default_factory=list)


class Manifest(BaseModel):
    """Complete manifest for a pipeline run."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    schema_version: str
    run_id: str
    created_at: datetime
    datasets: list[Dataset] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    summary: Summary = Field(default_factory=Summary)
    gates: Gates = Field(default_factory=Gates)
