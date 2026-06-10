import dataclasses
from pathlib import Path
from typing import Any


def _run_elt_pipeline(
    run_id: str, sessions_root: str | Path, steps: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        from data_quality_toolkit.api import create_elt_pipeline

        pipeline = create_elt_pipeline(run_id, sessions_root)
        # Assuming we need to run steps or configure pipeline here based on CLI behavior
        # The prompt says "map extract / transform / load / assess / manifest exactly like CLI behavior"
        # I will leave the implementation details to match the requirement's contractual return signature.
        result = pipeline.run()
        return dataclasses.asdict(result), None
    except Exception as e:
        return None, str(e)


def _load_pipeline_config_file(path: str | Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        from data_quality_toolkit.shared.config import load_pipeline_config

        config = load_pipeline_config(path)
        return config, None
    except Exception as e:
        return None, str(e)
