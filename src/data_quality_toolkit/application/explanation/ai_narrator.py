"""StoryLens Level 1 — optional local AI narrator backend (backend-only).

Not wired to public API, UI, CLI, or runtime flows.
Requires the ``storylens-ai`` optional extra.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_STORYLENS_AI_MODEL_ID = "HuggingFaceTB/SmolLM2-135M-Instruct"
DEFAULT_STORYLENS_AI_REVISION = "12fd25f77366fa6b3b4b768ec3050bf629380bac"

_MISSING_EXTRA_MSG = (
    "StoryLens local AI requires the optional 'storylens-ai' extra. "
    "Install it with: pip install 'data-quality-toolkit[storylens-ai]'"
)

_MODEL_UNAVAILABLE_MSG = (
    "Local model files for '{model_id}' are not available. "
    "The model must be staged locally before use."
)


class LocalAIUnavailableError(Exception):
    """Raised when the local AI backend cannot be activated."""


@dataclass(frozen=True, slots=True)
class LocalAINarratorConfig:
    """Configuration for the local AI narrator backend."""

    model_id: str = DEFAULT_STORYLENS_AI_MODEL_ID
    revision: str = DEFAULT_STORYLENS_AI_REVISION
    max_new_tokens: int = 128


def _load_transformers_backend(
    config: LocalAINarratorConfig,
) -> tuple[Any, Any, Any]:
    """Lazy-import transformers + torch, then load tokenizer and model from local files only.

    All optional AI imports are confined here; module-level scope stays import-clean.
    Returns (torch_module, tokenizer, model).

    Raises:
        LocalAIUnavailableError: optional deps absent, or local model files not found.
    """
    try:
        import torch  # type: ignore[import-not-found, unused-ignore]  # noqa: PLC0415
        from transformers import (  # type: ignore[import-not-found, unused-ignore]  # noqa: PLC0415
            AutoModelForCausalLM,
            AutoTokenizer,
        )
    except ImportError as exc:
        raise LocalAIUnavailableError(_MISSING_EXTRA_MSG) from exc

    try:
        # Revision is pinned via LocalAINarratorConfig.revision (default =
        # DEFAULT_STORYLENS_AI_REVISION, the verified Hugging Face commit hash).
        # Bandit B615 cannot statically resolve the config variable, so it
        # false-positives on the variable revision= argument; suppression is
        # scoped to B615 on these two call sites only.
        tokenizer = AutoTokenizer.from_pretrained(  # nosec B615
            config.model_id,
            revision=config.revision,
            local_files_only=True,
        )
        model = AutoModelForCausalLM.from_pretrained(  # nosec B615
            config.model_id,
            revision=config.revision,
            local_files_only=True,
            use_safetensors=True,
        )
    except OSError as exc:
        raise LocalAIUnavailableError(
            _MODEL_UNAVAILABLE_MSG.format(model_id=config.model_id)
        ) from exc

    return torch, tokenizer, model


def generate_narrative(
    *,
    prompt: str,
    config: LocalAINarratorConfig | None = None,
) -> str:
    """Generate a narrative using the local AI backend.

    Explicit invocation only — not called by deterministic narrator or any public path.
    Requires storylens-ai extra and locally available model files.
    Does not download models.

    Raises:
        LocalAIUnavailableError: deps missing or model not locally available.
    """
    if config is None:
        config = LocalAINarratorConfig()

    torch, tokenizer, model = _load_transformers_backend(config)

    inputs = tokenizer(prompt, return_tensors="pt")
    with torch.no_grad():
        output_ids = model.generate(**inputs, max_new_tokens=config.max_new_tokens)

    return str(tokenizer.decode(output_ids[0], skip_special_tokens=True))
