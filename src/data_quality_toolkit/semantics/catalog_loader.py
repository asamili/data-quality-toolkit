# Phase 3: KPI catalog loader.
from __future__ import annotations

from pathlib import Path

import yaml

from data_quality_toolkit.utils.logging import get_logger

from .schema import Catalog

logger = get_logger(__name__)


def load_catalog(path: str | Path) -> Catalog:
    """
    Load KPI catalog from YAML file.

    Args:
        path: Path to catalog YAML file

    Returns:
        Parsed Catalog object

    Raises:
        FileNotFoundError: If catalog file doesn't exist
        ValueError: If catalog is invalid (YAML or schema)
    """
    catalog_path = Path(path)

    if not catalog_path.exists():
        raise FileNotFoundError(f"Catalog not found: {catalog_path}")

    logger.info(f"Loading KPI catalog from {catalog_path}")

    try:
        # text mode is default; keep explicit encoding
        with open(catalog_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        catalog = Catalog(**data)
        logger.info(f"Loaded {len(catalog.kpis)} KPIs from catalog")
        return catalog

    except yaml.YAMLError as err:
        raise ValueError(f"Invalid YAML in catalog: {err}") from err
    except Exception as err:  # pydantic validation, type errors, etc.
        raise ValueError(f"Failed to parse catalog: {err}") from err


def save_catalog(catalog: Catalog, path: str | Path) -> None:
    """
    Save KPI catalog to YAML file.

    Args:
        catalog: Catalog to save
        path: Output path
    """
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = catalog.model_dump(exclude_none=True)

    with open(output_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

    logger.info(f"Saved catalog to {output_path}")
    logger.info(f"Saved catalog to {output_path}")
