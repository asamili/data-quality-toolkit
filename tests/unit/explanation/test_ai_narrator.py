"""Unit tests for ai_narrator backend-only module.

All tests pass without transformers/torch installed.
No real model loading or inference. No HF cache touched.
"""

from __future__ import annotations

import importlib
import re
import sys
from unittest.mock import MagicMock

import pytest

_OPTIONAL_AI_MODULES = [
    "transformers",
    "torch",
    "huggingface_hub",
    "tokenizers",
    "safetensors",
    "sentence_transformers",
]

_CATEGORY_C_MODULES = [
    "sentence_transformers",
    "cross_encoder",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_backend(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Inject fake torch + transformers into sys.modules. Returns (torch, tokenizer, model)."""
    fake_tokenizer = MagicMock(name="tokenizer_instance")
    fake_tokenizer.decode.return_value = "AI-generated narrative text."

    fake_model = MagicMock(name="model_instance")
    fake_output = MagicMock()
    fake_output.__getitem__ = MagicMock(return_value=MagicMock())
    fake_model.generate.return_value = fake_output

    fake_auto_tokenizer = MagicMock(name="AutoTokenizer")
    fake_auto_tokenizer.from_pretrained.return_value = fake_tokenizer

    fake_auto_model = MagicMock(name="AutoModelForCausalLM")
    fake_auto_model.from_pretrained.return_value = fake_model

    fake_transformers = MagicMock(name="transformers")
    fake_transformers.AutoTokenizer = fake_auto_tokenizer
    fake_transformers.AutoModelForCausalLM = fake_auto_model

    fake_torch = MagicMock(name="torch")

    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    return fake_torch, fake_tokenizer, fake_model


# ---------------------------------------------------------------------------
# Import isolation
# ---------------------------------------------------------------------------


class TestImportIsolation:
    def test_module_import_does_not_load_optional_ai(self) -> None:
        before = set(sys.modules)
        importlib.import_module("data_quality_toolkit.application.explanation.ai_narrator")
        loaded = [m for m in _OPTIONAL_AI_MODULES if m in sys.modules and m not in before]
        assert not loaded, f"Optional AI modules loaded at import time: {loaded}"

    def test_module_import_does_not_load_category_c(self) -> None:
        before = set(sys.modules)
        importlib.import_module("data_quality_toolkit.application.explanation.ai_narrator")
        loaded = [m for m in _CATEGORY_C_MODULES if m in sys.modules and m not in before]
        assert not loaded, f"Category C modules loaded at import time: {loaded}"


# ---------------------------------------------------------------------------
# Constants and config
# ---------------------------------------------------------------------------


class TestConstantsAndConfig:
    def test_default_model_id_constant(self) -> None:
        from data_quality_toolkit.application.explanation.ai_narrator import (
            DEFAULT_STORYLENS_AI_MODEL_ID,
        )

        assert DEFAULT_STORYLENS_AI_MODEL_ID == "HuggingFaceTB/SmolLM2-135M-Instruct"

    def test_config_default_model_id(self) -> None:
        from data_quality_toolkit.application.explanation.ai_narrator import (
            DEFAULT_STORYLENS_AI_MODEL_ID,
            LocalAINarratorConfig,
        )

        assert LocalAINarratorConfig().model_id == DEFAULT_STORYLENS_AI_MODEL_ID

    def test_default_revision_constant(self) -> None:
        from data_quality_toolkit.application.explanation.ai_narrator import (
            DEFAULT_STORYLENS_AI_REVISION,
        )

        assert DEFAULT_STORYLENS_AI_REVISION == "12fd25f77366fa6b3b4b768ec3050bf629380bac"

    def test_revision_is_40_char_lowercase_hex(self) -> None:
        from data_quality_toolkit.application.explanation.ai_narrator import (
            DEFAULT_STORYLENS_AI_REVISION,
        )

        assert len(DEFAULT_STORYLENS_AI_REVISION) == 40
        assert re.fullmatch(r"[0-9a-f]{40}", DEFAULT_STORYLENS_AI_REVISION)

    def test_config_default_revision(self) -> None:
        from data_quality_toolkit.application.explanation.ai_narrator import (
            DEFAULT_STORYLENS_AI_REVISION,
            LocalAINarratorConfig,
        )

        assert LocalAINarratorConfig().revision == DEFAULT_STORYLENS_AI_REVISION

    def test_config_is_frozen(self) -> None:
        from data_quality_toolkit.application.explanation.ai_narrator import LocalAINarratorConfig

        config = LocalAINarratorConfig()
        with pytest.raises((AttributeError, TypeError)):
            config.model_id = "other-model"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Missing optional dependencies
# ---------------------------------------------------------------------------


class TestMissingOptionalDependencies:
    def test_missing_transformers_raises_local_ai_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "transformers", None)
        monkeypatch.setitem(sys.modules, "torch", None)
        from data_quality_toolkit.application.explanation.ai_narrator import (
            LocalAINarratorConfig,
            LocalAIUnavailableError,
            _load_transformers_backend,
        )

        with pytest.raises(LocalAIUnavailableError):
            _load_transformers_backend(LocalAINarratorConfig())

    def test_missing_torch_raises_local_ai_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "torch", None)
        from data_quality_toolkit.application.explanation.ai_narrator import (
            LocalAINarratorConfig,
            LocalAIUnavailableError,
            _load_transformers_backend,
        )

        with pytest.raises(LocalAIUnavailableError):
            _load_transformers_backend(LocalAINarratorConfig())

    def test_missing_deps_error_mentions_storylens_ai_extra(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "transformers", None)
        monkeypatch.setitem(sys.modules, "torch", None)
        from data_quality_toolkit.application.explanation.ai_narrator import (
            LocalAINarratorConfig,
            LocalAIUnavailableError,
            _load_transformers_backend,
        )

        with pytest.raises(LocalAIUnavailableError, match="storylens-ai"):
            _load_transformers_backend(LocalAINarratorConfig())


# ---------------------------------------------------------------------------
# Missing local model files
# ---------------------------------------------------------------------------


class TestMissingLocalModelFiles:
    def test_missing_local_model_raises_local_ai_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_auto_tokenizer = MagicMock(name="AutoTokenizer")
        fake_auto_tokenizer.from_pretrained.side_effect = OSError("No local model files.")

        fake_transformers = MagicMock(name="transformers")
        fake_transformers.AutoTokenizer = fake_auto_tokenizer

        monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
        monkeypatch.setitem(sys.modules, "torch", MagicMock(name="torch"))

        from data_quality_toolkit.application.explanation.ai_narrator import (
            LocalAINarratorConfig,
            LocalAIUnavailableError,
            _load_transformers_backend,
        )

        with pytest.raises(LocalAIUnavailableError):
            _load_transformers_backend(LocalAINarratorConfig())

    def test_missing_local_model_error_does_not_mention_download(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_auto_tokenizer = MagicMock(name="AutoTokenizer")
        fake_auto_tokenizer.from_pretrained.side_effect = OSError("Offline.")

        fake_transformers = MagicMock(name="transformers")
        fake_transformers.AutoTokenizer = fake_auto_tokenizer

        monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
        monkeypatch.setitem(sys.modules, "torch", MagicMock(name="torch"))

        from data_quality_toolkit.application.explanation.ai_narrator import (
            LocalAINarratorConfig,
            LocalAIUnavailableError,
            _load_transformers_backend,
        )

        with pytest.raises(LocalAIUnavailableError) as exc_info:
            _load_transformers_backend(LocalAINarratorConfig())

        assert "download" not in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# local_files_only=True and use_safetensors=True enforcement
# ---------------------------------------------------------------------------


class TestLoadingFlags:
    def test_tokenizer_loaded_with_local_files_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, _ = _make_fake_backend(monkeypatch)

        fake_transformers = sys.modules["transformers"]

        from data_quality_toolkit.application.explanation.ai_narrator import (
            LocalAINarratorConfig,
            _load_transformers_backend,
        )

        _load_transformers_backend(LocalAINarratorConfig())

        _, kwargs = fake_transformers.AutoTokenizer.from_pretrained.call_args
        assert kwargs.get("local_files_only") is True

    def test_tokenizer_loaded_with_pinned_revision(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, _ = _make_fake_backend(monkeypatch)

        fake_transformers = sys.modules["transformers"]

        from data_quality_toolkit.application.explanation.ai_narrator import (
            LocalAINarratorConfig,
            _load_transformers_backend,
        )

        config = LocalAINarratorConfig()
        _load_transformers_backend(config)

        _, kwargs = fake_transformers.AutoTokenizer.from_pretrained.call_args
        assert kwargs.get("revision") == config.revision

    def test_model_loaded_with_pinned_revision(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, _ = _make_fake_backend(monkeypatch)

        fake_transformers = sys.modules["transformers"]

        from data_quality_toolkit.application.explanation.ai_narrator import (
            LocalAINarratorConfig,
            _load_transformers_backend,
        )

        config = LocalAINarratorConfig()
        _load_transformers_backend(config)

        _, kwargs = fake_transformers.AutoModelForCausalLM.from_pretrained.call_args
        assert kwargs.get("revision") == config.revision

    def test_model_loaded_with_local_files_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, _ = _make_fake_backend(monkeypatch)

        fake_transformers = sys.modules["transformers"]

        from data_quality_toolkit.application.explanation.ai_narrator import (
            LocalAINarratorConfig,
            _load_transformers_backend,
        )

        _load_transformers_backend(LocalAINarratorConfig())

        _, kwargs = fake_transformers.AutoModelForCausalLM.from_pretrained.call_args
        assert kwargs.get("local_files_only") is True

    def test_model_loaded_with_use_safetensors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _, _, _ = _make_fake_backend(monkeypatch)

        fake_transformers = sys.modules["transformers"]

        from data_quality_toolkit.application.explanation.ai_narrator import (
            LocalAINarratorConfig,
            _load_transformers_backend,
        )

        _load_transformers_backend(LocalAINarratorConfig())

        _, kwargs = fake_transformers.AutoModelForCausalLM.from_pretrained.call_args
        assert kwargs.get("use_safetensors") is True

    def test_no_trust_remote_code_in_any_from_pretrained_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, _, _ = _make_fake_backend(monkeypatch)

        fake_transformers = sys.modules["transformers"]

        from data_quality_toolkit.application.explanation.ai_narrator import (
            LocalAINarratorConfig,
            _load_transformers_backend,
        )

        _load_transformers_backend(LocalAINarratorConfig())

        for mock_class in (
            fake_transformers.AutoTokenizer,
            fake_transformers.AutoModelForCausalLM,
        ):
            _, kwargs = mock_class.from_pretrained.call_args
            assert kwargs.get("trust_remote_code") is not True


# ---------------------------------------------------------------------------
# generate_narrative happy path
# ---------------------------------------------------------------------------


class TestGenerateNarrative:
    def test_generate_narrative_returns_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_fake_backend(monkeypatch)

        from data_quality_toolkit.application.explanation.ai_narrator import generate_narrative

        result = generate_narrative(prompt="Explain data quality.")
        assert isinstance(result, str)

    def test_generate_narrative_missing_deps_raises_local_ai_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "transformers", None)
        monkeypatch.setitem(sys.modules, "torch", None)
        from data_quality_toolkit.application.explanation.ai_narrator import (
            LocalAIUnavailableError,
            generate_narrative,
        )

        with pytest.raises(LocalAIUnavailableError):
            generate_narrative(prompt="Test.")
