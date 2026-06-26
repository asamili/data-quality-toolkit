"""StoryLens AI adapter — default-OFF AI safety wrapper sub-package.

Exports typed facts contract, validator, settings, and fallback wrapper.
No AI dependencies (transformers / torch / huggingface_hub) are imported
at module level. AI backend is lazy-loaded only inside ``try_explain``.
"""

from data_quality_toolkit.application.explanation.ai_adapter.facts import (
    StoryLensFacts,
    StoryLensMetric,
)
from data_quality_toolkit.application.explanation.ai_adapter.fallback import (
    get_fallback,
    try_explain,
)
from data_quality_toolkit.application.explanation.ai_adapter.settings import (
    AIAvailability,
    compute_availability,
    read_ai_enabled,
    resolve_model_dir,
)
from data_quality_toolkit.application.explanation.ai_adapter.validator import (
    ValidationResult,
    validate_output,
)

__all__ = [
    "AIAvailability",
    "StoryLensFacts",
    "StoryLensMetric",
    "ValidationResult",
    "compute_availability",
    "get_fallback",
    "read_ai_enabled",
    "resolve_model_dir",
    "try_explain",
    "validate_output",
]
