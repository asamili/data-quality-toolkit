from __future__ import annotations

from data_quality_toolkit.application.workflow.workflow_builder import WorkflowBuilder, WorkflowSpec


def test_workflow_spec_dataclass():
    spec = WorkflowSpec(name="demo", params={"a": 1}, description="test")
    assert spec.name == "demo"
    assert spec.params["a"] == 1
    assert spec.description == "test"


def test_workflow_builder_add_and_build():
    wb = WorkflowBuilder()
    wb.add_step(("load_csv", {"path": "x.csv"})).add_step(("profile", {}))
    steps = wb.build()
    assert steps == [("load_csv", {"path": "x.csv"}), ("profile", {})]
