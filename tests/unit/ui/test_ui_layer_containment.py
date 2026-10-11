"""Static and import-level proof of managed activation containment.

The managed Export/API siblings accept only the shared
``VerifiedManagedExportSource``. The public API and application-workflow layers
must never import the UI layer to obtain a trust or provenance type, so managed
trust stays contained inside ``adapters.ui`` and cannot leak downstream.

These checks are deliberately independent of the Import Linter contract in
``pyproject.toml``: the contract is the enforcement gate, and these tests prove
the same boundary holds at module-import time and in the source itself.
"""

from __future__ import annotations

import ast
import inspect
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from data_quality_toolkit import api
from data_quality_toolkit.application.workflow import pipeline
from data_quality_toolkit.shared import managed_export_source

_UI_PREFIX = "data_quality_toolkit.adapters.ui"
_CONTAINED_MODULES = (api, pipeline)

# UI-private types that must never appear in a downstream module's namespace.
_UI_PRIVATE_TYPE_NAMES = (
    "SessionCapability",
    "ManagedTrustRoot",
    "ManagedSourceLocator",
    "TrustDecision",
    "TrustAuthority",
    "CanonicalFrameKey",
    "AssessmentKey",
)


def _imported_modules(module: Any) -> set[str]:
    """Return every module name imported anywhere in ``module``'s source."""
    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


# --- A. Static source proof ---------------------------------------------------


@pytest.mark.parametrize("module", _CONTAINED_MODULES, ids=lambda m: m.__name__)
def test_module_source_imports_no_ui_module(module: Any) -> None:
    """No import statement anywhere in the module names the UI layer.

    Covers function-local (deferred) imports too, because the whole source is
    parsed rather than only the module-level import block.
    """
    offenders = {name for name in _imported_modules(module) if name.startswith(_UI_PREFIX)}
    assert offenders == set()


@pytest.mark.parametrize("module", _CONTAINED_MODULES, ids=lambda m: m.__name__)
def test_module_source_never_names_a_ui_trust_type(module: Any) -> None:
    source = inspect.getsource(module)
    for type_name in _UI_PRIVATE_TYPE_NAMES:
        assert type_name not in source


@pytest.mark.parametrize("module", _CONTAINED_MODULES, ids=lambda m: m.__name__)
def test_module_namespace_holds_no_ui_trust_type(module: Any) -> None:
    for type_name in _UI_PRIVATE_TYPE_NAMES:
        assert type_name not in vars(module)


# --- B. Provenance comes from the shared kernel ---------------------------------


def test_provenance_contract_lives_in_the_shared_kernel() -> None:
    assert managed_export_source.__name__ == "data_quality_toolkit.shared.managed_export_source"
    assert not managed_export_source.__name__.startswith(_UI_PREFIX)


@pytest.mark.parametrize("module", _CONTAINED_MODULES, ids=lambda m: m.__name__)
def test_managed_sibling_provenance_type_is_the_shared_one(module: Any) -> None:
    imported = _imported_modules(module)
    assert "data_quality_toolkit.shared.managed_export_source" in imported


def test_shared_contract_imports_no_ui_pandas_or_streamlit() -> None:
    imported = _imported_modules(managed_export_source)
    assert not any(name.startswith(_UI_PREFIX) for name in imported)
    assert not any(name.split(".")[0] in {"pandas", "streamlit"} for name in imported)


# --- C. Import-level proof (fresh interpreter state) -------------------------------


_LEAK_PROBE = """
import importlib, json, sys
importlib.import_module({target!r})
print(json.dumps(sorted(n for n in sys.modules if n.startswith({prefix!r}))))
"""


def _ui_modules_after_importing(target: str) -> list[str]:
    """Import ``target`` in a clean subprocess and report any UI modules loaded.

    A subprocess is used deliberately: mutating ``sys.modules`` in-process would
    invalidate module objects other tests already hold, so the isolation has to
    be real rather than simulated.
    """
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
        [sys.executable, "-c", _LEAK_PROBE.format(target=target, prefix=_UI_PREFIX)],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return list(json.loads(completed.stdout.strip()))


def test_importing_the_api_pulls_in_no_ui_module() -> None:
    """Importing the public API alone must not drag the UI layer into memory."""
    assert _ui_modules_after_importing("data_quality_toolkit.api") == []


def test_importing_the_workflow_pipeline_pulls_in_no_ui_module() -> None:
    assert _ui_modules_after_importing("data_quality_toolkit.application.workflow.pipeline") == []


# --- D. The Import Linter contract is declared and exact ---------------------------


def _pyproject_text() -> str:
    root = Path(__file__).resolve().parents[3]
    return (root / "pyproject.toml").read_text(encoding="utf-8")


def test_containment_contract_is_declared() -> None:
    text = _pyproject_text()
    assert (
        'name = "Managed activation containment: '
        'API and workflow must not import the UI layer"' in text
    )


def test_containment_contract_names_both_source_layers() -> None:
    text = _pyproject_text()
    marker = "Managed activation containment"
    block = text[text.index(marker) :]
    assert '"data_quality_toolkit.api"' in block
    assert '"data_quality_toolkit.application.workflow"' in block
    assert '"data_quality_toolkit.adapters.ui"' in block
    assert 'type = "forbidden"' in block


# --- E. UI-side gateway is the only boundary crossing ---------------------------------


def test_only_the_gateway_mints_verified_provenance() -> None:
    """The UI mints provenance in exactly one module: the managed export gateway."""
    package_root = Path(inspect.getfile(managed_export_source)).resolve().parents[1]
    ui_services = package_root / "adapters" / "ui" / "services"
    assert ui_services.is_dir()
    minting: list[str] = []
    for path in ui_services.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "VerifiedManagedExportSource(" in source:
            minting.append(path.name)
    assert minting == ["managed_export_gateway.py"]
