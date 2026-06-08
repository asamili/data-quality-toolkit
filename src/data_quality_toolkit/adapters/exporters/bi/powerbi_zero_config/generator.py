# cspell:ignore pbit rels
"""Phase 2: Power BI package generator (refactored, lint-clean)."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any, Final, cast

import pandas as pd  # for timestamp in README
from jinja2 import Template, TemplateSyntaxError

from data_quality_toolkit.utils.helpers import ensure_dir
from data_quality_toolkit.utils.logging import get_logger

__all__ = ["render_template", "generate_powerbi_package"]

logger = get_logger("dqt.exporters.bi.powerbi_zero_config.generator")

DEFAULT_BASE: Final[str] = "./dist"

# ------------------------ small helpers ------------------------ #


def _get_template_dir() -> Path:
    """Where templated assets live. Split out for test monkey-patching."""
    return Path(__file__).parent.parent / "templates"


def _csv_has_column(csv_path: Path, col: str) -> bool:
    try:
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            headers_row: list[str] | None = next(reader, None)
            if headers_row is None:
                return False
            headers: list[str] = [str(h) for h in headers_row]
            return col in headers
    except Exception:
        return False


def render_template(template_path: Path, context: dict[str, Any]) -> str:
    """Render a Jinja2 template file with UTF-8 decoding."""
    text = template_path.read_text(encoding="utf-8")

    out: str
    try:
        out = Template(text).render(**context)  # returns str; cast not needed
    except TemplateSyntaxError:
        # If the template itself is malformed, use raw text
        out = text

    # Best-effort substitution for any unresolved tokens
    for k, v in context.items():
        out = out.replace(f"{{{{ {k} }}}}", str(v))
        out = out.replace(f"{{{{{k}}}}}", str(v))

    s = out.strip()
    if s.startswith("{{") and s.endswith("}}"):
        inner = s[2:-2].strip()
        if inner.startswith("{") or inner.startswith("["):
            return inner
        return "{ " + inner + " }"

    return out


def _copy_model(template_dir: Path, output_dir: Path, files_created: list[str]) -> Path:
    """Copy model.pbit if present; otherwise write guidance file (no fake .pbit)."""
    src = template_dir / "model.pbit"
    if src.exists():
        dst = output_dir / "model.pbit"
        shutil.copy2(src, dst)
        files_created.append(str(dst))
        logger.info("Copied model.pbit")
        return dst

    # No template: provide guidance instead of creating a bogus .pbit
    readme = output_dir / "model.pbit.README"
    readme.write_text(
        "No model.pbit template was found.\n\n"
        "Power BI expects .pbit to be a ZIP package exported from Power BI Desktop.\n"
        "Create one with a BaseFolder parameter and drop it at:\n"
        "  src/data_quality_toolkit/adapters/exporters/bi/templates/model.pbit\n",
        encoding="utf-8",
    )
    files_created.append(str(readme))
    logger.warning("model.pbit not found in templates; wrote model.pbit.README with instructions.")
    return readme


def _write_parameters(
    template_dir: Path, output_dir: Path, base_folder: str, files_created: list[str]
) -> Path:
    """Write parameters.json from template or default."""
    import json as _json  # local alias

    tpl = template_dir / "parameters.json.j2"
    out = output_dir / "parameters.json"
    if tpl.exists():
        content = render_template(
            tpl,
            {
                "base_folder": base_folder or DEFAULT_BASE,
                "base_folder_json": json.dumps(base_folder or DEFAULT_BASE),
            },
        )
    else:
        # Default JSON if no template found
        content = _json.dumps(
            {
                "parameters": [
                    {
                        "name": "BaseFolder",
                        "type": "Text",
                        "currentValue": base_folder or DEFAULT_BASE,
                    }
                ]
            },
            indent=2,
        )
    out.write_text(content, encoding="utf-8")
    files_created.append(str(out))
    logger.info("Generated parameters.json")
    return out


def _write_relationships(
    template_dir: Path,
    output_dir: Path,
    files_created: list[str],
    *,
    include_time_rel: bool = False,
) -> Path:
    """Write relationships.json from template or default scaffold."""
    tpl = template_dir / "relationships.json.j2"
    out = output_dir / "relationships.json"
    if tpl.exists():
        content = render_template(tpl, {"include_time_rel": include_time_rel})
    else:
        payload: dict[str, Any] = {
            "tables": {
                "dim_dataset": {"primary_key": ["dataset_id"]},
                "dim_column": {
                    "primary_key": ["column_id"],
                    "foreign_keys": [["dataset_id", "dim_dataset", "dataset_id"]],
                },
                "fact_profile_runs": {
                    "foreign_keys": [["dataset_id", "dim_dataset", "dataset_id"]],
                },
                "fact_quality_metrics": {
                    "foreign_keys": [["column_id", "dim_column", "column_id"]],
                },
                "dim_time": {"primary_key": ["time_id"]},
            },
            "relationships": [
                {
                    "from": ["dim_column", "dataset_id"],
                    "to": ["dim_dataset", "dataset_id"],
                    "type": "many-to-one",
                    "crossFilter": "single",
                },
                {
                    "from": ["fact_profile_runs", "dataset_id"],
                    "to": ["dim_dataset", "dataset_id"],
                    "type": "many-to-one",
                    "crossFilter": "single",
                },
                {
                    "from": ["fact_quality_metrics", "column_id"],
                    "to": ["dim_column", "column_id"],
                    "type": "many-to-one",
                    "crossFilter": "single",
                },
            ],
        }
        if include_time_rel:
            relationships_list: list[dict[str, Any]] = cast(
                list[dict[str, Any]], payload["relationships"]
            )
            relationships_list.append(
                {
                    "from": ["fact_profile_runs", "time_id"],
                    "to": ["dim_time", "time_id"],
                    "type": "many-to-one",
                    "crossFilter": "single",
                }
            )
        content = json.dumps(payload, indent=2)

    out.write_text(content, encoding="utf-8")
    files_created.append(str(out))
    logger.info("Generated relationships.json")
    return out


def _copy_star_csvs(star_dir: Path, star_out: Path, files_created: list[str]) -> int:
    """Copy *.csv from star_dir → star_out. Returns count."""
    star_files = list(star_dir.glob("*.csv"))
    for csv_file in star_files:
        dst = star_out / csv_file.name
        shutil.copy2(csv_file, dst)
        files_created.append(str(dst))
    logger.info("Copied %s star schema files", len(star_files))
    return len(star_files)


def _copy_dim_time_if_provided(
    dim_time_path: str | Path | None, time_out: Path, files_created: list[str]
) -> bool:
    """Copy dim_time.csv to time_out if given, skipping same-file copies. Returns has_time."""
    if not dim_time_path:
        return False
    src = Path(dim_time_path)
    if not src.exists():
        logger.warning("dim_time_path provided but missing: %s", src)
        return False
    dst = time_out / "dim_time.csv"
    try:
        same = src.resolve() == dst.resolve()
    except Exception:
        same = str(src) == str(dst)
    if not same:
        shutil.copy2(src, dst)
        logger.info("Copied dim_time.csv")
    else:
        logger.info("dim_time.csv already in destination; skipping copy")
    files_created.append(str(dst))
    return True


def _write_readme(output_dir: Path, base_folder: str) -> Path:
    """Write README.txt with quick instructions."""
    readme_path = output_dir / "README.txt"
    readme_content = (
        "Power BI Package\n"
        "================\n\n"
        "To use this package:\n"
        "1. Open model.pbit in Power BI Desktop\n"
        f"2. When prompted for BaseFolder parameter, enter: {base_folder}\n"
        "3. Click Load to import all data\n\n"
        "Files included:\n"
        "- model.pbit: Power BI template\n"
        "- parameters.json: Configuration parameters\n"
        "- relationships.json: Table relationships\n"
        "- star/: Star schema tables\n"
        "- time/: Time dimension table\n"
        "- dax/: DAX measures (Phase 3)\n\n"
        f"Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    )
    readme_path.write_text(readme_content, encoding="utf-8")
    return readme_path


# ------------------------ main API ------------------------ #


def generate_powerbi_package(
    star_dir: Path,
    output_dir: Path,
    base_folder: str = DEFAULT_BASE,
    dim_time_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Generate Power BI package structure.

    Args:
        star_dir: Directory containing star schema CSVs
        output_dir: Output directory for package
        base_folder: Base folder parameter value
        dim_time_path: Path to dim_time.csv (optional)

    Returns:
        dict with:
          - files: {filename: full_path}
          - star_count: int
          - has_time: bool
          - output_dir: str
    """
    logger.info("Generating Power BI package structure")

    template_dir = _get_template_dir()

    # Ensure output structure
    ensure_dir(output_dir)
    star_out = ensure_dir(output_dir / "star")
    time_out = ensure_dir(output_dir / "time")
    ensure_dir(output_dir / "dax")

    files_created: list[str] = []

    # 1. model.pbit
    _copy_model(template_dir, output_dir, files_created)

    # 2. parameters.json
    _write_parameters(template_dir, output_dir, base_folder, files_created)

    # 3. star csvs
    star_count = _copy_star_csvs(star_dir, star_out, files_created)

    # 4. optional dim_time copy
    has_time = _copy_dim_time_if_provided(dim_time_path, time_out, files_created)

    # 5. relationships.json (decide conditionally)
    include_time_rel = has_time and _csv_has_column(star_out / "fact_profile_runs.csv", "time_id")
    _write_relationships(template_dir, output_dir, files_created, include_time_rel=include_time_rel)

    # 6. README
    _write_readme(output_dir, base_folder)

    # Final mapping
    files_map: dict[str, str] = {Path(p).name: p for p in files_created}
    return {
        "files": files_map,
        "star_count": star_count,
        "has_time": has_time,
        "output_dir": str(output_dir),
    }
