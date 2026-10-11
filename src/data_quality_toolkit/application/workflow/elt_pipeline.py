"""Declarative ELT step scaffold — it records a plan, it does not run one.

This is a scaffold, not an ELT engine. ``extract``, ``transform``, ``load`` and
``assess`` only append an :class:`ELTStep` describing what was asked for: no file
is read, no data is transformed, and nothing is written for those step types.
``manifest`` is the one step that performs real work — :func:`ELTPipeline.run`
calls ``create_manifest`` for it.

Read the :class:`ELTResult` fields accordingly: ``steps_executed`` is the list of
*declared* steps, and ``status`` is ``"success"`` whenever the scaffold itself
completed without raising. Neither field reports that extract/transform/load work
happened, because none does. Both names and the status value are pinned by
``tests/integration/test_elt_pipeline.py``.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ELTStep:
    type: str
    name: str
    args: dict


@dataclass
class ELTResult:
    run_id: str
    status: str
    steps_executed: list[ELTStep]
    manifest: dict | None = None


class ELTPipeline:
    def __init__(self, run_id: str, sessions_root: str | Path):
        self.run_id = run_id
        self.sessions_root = Path(sessions_root)
        self.steps: list[ELTStep] = []

    def extract(
        self, source: Any, *, name: str | None = None, kind: str = "bronze"
    ) -> "ELTPipeline":
        self.steps.append(ELTStep("extract", name or "extract", {"source": source, "kind": kind}))
        return self

    def transform(self, name: str | None = None, description: str | None = None) -> "ELTPipeline":
        self.steps.append(ELTStep("transform", name or "transform", {"description": description}))
        return self

    def load(self, output: Any, *, name: str | None = None, kind: str = "silver") -> "ELTPipeline":
        self.steps.append(ELTStep("load", name or "load", {"output": output, "kind": kind}))
        return self

    def assess(self, name: str | None = None, description: str | None = None) -> "ELTPipeline":
        self.steps.append(ELTStep("assess", name or "assess", {"description": description}))
        return self

    def manifest(self) -> "ELTPipeline":
        self.steps.append(ELTStep("manifest", "manifest", {}))
        return self

    def run(self) -> ELTResult:
        from data_quality_toolkit.api import create_manifest

        manifest_data = None
        if any(step.type == "manifest" for step in self.steps):
            manifest_data = create_manifest(self.run_id, str(self.sessions_root))

        return ELTResult(self.run_id, "success", self.steps, manifest=manifest_data)


def create_elt_pipeline(run_id: str, sessions_root: str | Path) -> ELTPipeline:
    return ELTPipeline(run_id, sessions_root)
