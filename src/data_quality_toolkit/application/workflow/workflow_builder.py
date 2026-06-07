# src/data_quality_toolkit/workflow/workflow_builder.py
"""Phase 1: Workflow builder (stub for future DAG construction)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class WorkflowSpec:
    name: str
    params: dict[str, Any]
    description: str | None = None


class WorkflowBuilder:
    """Build and configure workflows (stub)."""

    def __init__(self) -> None:
        self.steps: list[Any] = []

    def add_step(self, step: Any) -> WorkflowBuilder:
        self.steps.append(step)
        return self

    def build(self) -> list[Any]:
        return self.steps
