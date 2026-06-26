"""Boundary tests: import isolation, API boundary, CLI boundary."""

from __future__ import annotations

import ast
import importlib
import inspect
import sys
import tomllib
from pathlib import Path

_OPTIONAL_AI_MODULES = [
    "transformers",
    "torch",
    "huggingface_hub",
    "tokenizers",
    "safetensors",
    "sentence_transformers",
]


class TestImportIsolation:
    def test_importing_ai_adapter_does_not_load_torch(self) -> None:
        before = set(sys.modules)
        importlib.import_module("data_quality_toolkit.application.explanation.ai_adapter")
        loaded = [m for m in _OPTIONAL_AI_MODULES if m in sys.modules and m not in before]
        assert not loaded, f"Optional AI modules loaded at ai_adapter import time: {loaded}"

    def test_importing_facts_does_not_load_ai_deps(self) -> None:
        before = set(sys.modules)
        importlib.import_module("data_quality_toolkit.application.explanation.ai_adapter.facts")
        loaded = [m for m in _OPTIONAL_AI_MODULES if m in sys.modules and m not in before]
        assert not loaded, f"Optional AI modules loaded by facts: {loaded}"

    def test_importing_validator_does_not_load_ai_deps(self) -> None:
        before = set(sys.modules)
        importlib.import_module("data_quality_toolkit.application.explanation.ai_adapter.validator")
        loaded = [m for m in _OPTIONAL_AI_MODULES if m in sys.modules and m not in before]
        assert not loaded, f"Optional AI modules loaded by validator: {loaded}"

    def test_importing_fallback_does_not_load_ai_deps(self) -> None:
        before = set(sys.modules)
        importlib.import_module("data_quality_toolkit.application.explanation.ai_adapter.fallback")
        loaded = [m for m in _OPTIONAL_AI_MODULES if m in sys.modules and m not in before]
        assert not loaded, f"Optional AI modules loaded by fallback: {loaded}"

    def test_importing_settings_does_not_load_ai_deps(self) -> None:
        before = set(sys.modules)
        importlib.import_module("data_quality_toolkit.application.explanation.ai_adapter.settings")
        loaded = [m for m in _OPTIONAL_AI_MODULES if m in sys.modules and m not in before]
        assert not loaded, f"Optional AI modules loaded by settings: {loaded}"

    def test_importing_prompts_does_not_load_ai_deps(self) -> None:
        before = set(sys.modules)
        importlib.import_module("data_quality_toolkit.application.explanation.ai_adapter.prompts")
        loaded = [m for m in _OPTIONAL_AI_MODULES if m in sys.modules and m not in before]
        assert not loaded, f"Optional AI modules loaded by prompts: {loaded}"


class TestApiBoundary:
    def test_api_module_does_not_export_story_lens_facts(self) -> None:
        import data_quality_toolkit.api as api

        assert not hasattr(api, "StoryLensFacts")

    def test_api_module_does_not_export_try_explain(self) -> None:
        import data_quality_toolkit.api as api

        assert not hasattr(api, "try_explain")

    def test_api_module_does_not_export_ai_adapter_symbols(self) -> None:
        import data_quality_toolkit.api as api

        forbidden = [
            name for name in dir(api) if "ai_adapter" in name.lower() or "StoryLensFacts" in name
        ]
        assert not forbidden, f"API exposes AI adapter symbols: {forbidden}"


class TestCliBoundary:
    def test_cli_module_importable_without_ai_deps(self) -> None:
        before = set(sys.modules)
        importlib.import_module("data_quality_toolkit.adapters.cli.main")
        loaded = [m for m in _OPTIONAL_AI_MODULES if m in sys.modules and m not in before]
        assert not loaded, f"CLI import loaded AI deps: {loaded}"


class TestParentPackageBoundary:
    def test_storylens_facts_not_in_explanation_namespace(self) -> None:
        import data_quality_toolkit.application.explanation as pkg

        assert not hasattr(
            pkg, "StoryLensFacts"
        ), "StoryLensFacts must not be exported from explanation package"

    def test_try_explain_not_in_explanation_namespace(self) -> None:
        import data_quality_toolkit.application.explanation as pkg

        assert not hasattr(
            pkg, "try_explain"
        ), "try_explain must not be exported from explanation package"

    def test_ai_availability_not_in_explanation_namespace(self) -> None:
        import data_quality_toolkit.application.explanation as pkg

        assert not hasattr(
            pkg, "AIAvailability"
        ), "AIAvailability must not be exported from explanation package"


# ── G20B: import-linter contract presence ─────────────────────────────────────

_PYPROJECT = Path(__file__).resolve().parents[4] / "pyproject.toml"

_AI_FORBIDDEN = [
    "data_quality_toolkit.application.explanation.ai_adapter",
    "data_quality_toolkit.application.explanation.ai_narrator",
]
_AI_SOURCES = [
    "data_quality_toolkit.api",
    "data_quality_toolkit.adapters.cli",
]


class TestImportLinterContractG20B:
    def test_ai_isolation_contract_present_in_pyproject(self) -> None:
        data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
        contracts = data.get("tool", {}).get("importlinter", {}).get("contracts", [])
        ai_contract = next(
            (c for c in contracts if "StoryLens optional AI internals" in c.get("name", "")),
            None,
        )
        assert (
            ai_contract is not None
        ), "G20B AI isolation import-linter contract missing from pyproject.toml"
        for mod in _AI_FORBIDDEN:
            assert mod in ai_contract.get(
                "forbidden_modules", []
            ), f"{mod} not in forbidden_modules"
        for mod in _AI_SOURCES:
            assert mod in ai_contract.get("source_modules", []), f"{mod} not in source_modules"

    def test_api_source_does_not_reference_ai_adapter(self) -> None:
        import data_quality_toolkit.api as api_mod

        tree = ast.parse(inspect.getsource(api_mod))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert (
                    "explanation.ai_adapter" not in node.module
                ), f"api.py must not import from ai_adapter (found: {node.module})"
                assert (
                    "explanation.ai_narrator" not in node.module
                ), f"api.py must not import from ai_narrator (found: {node.module})"

    def test_cli_source_does_not_reference_ai_adapter(self) -> None:
        import data_quality_toolkit.adapters.cli.main as cli_mod

        tree = ast.parse(inspect.getsource(cli_mod))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert (
                    "explanation.ai_adapter" not in node.module
                ), f"cli.main must not import from ai_adapter (found: {node.module})"
                assert (
                    "explanation.ai_narrator" not in node.module
                ), f"cli.main must not import from ai_narrator (found: {node.module})"
