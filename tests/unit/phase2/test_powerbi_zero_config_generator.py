from __future__ import annotations

import json
from pathlib import Path

from data_quality_toolkit.adapters.exporters.bi.powerbi_zero_config.generator import (
    generate_powerbi_package,
)

# ---------- helpers ----------


def _write_star(tmp: Path) -> Path:
    star = tmp / "star_src"
    star.mkdir()
    (star / "dim_dataset.csv").write_text("dataset_id,name\n1,foo\n", encoding="utf-8")
    (star / "dim_column.csv").write_text("column_id,dataset_id,name\n1,1,col\n", encoding="utf-8")
    (star / "fact_profile_runs.csv").write_text(
        "id,dataset_id,ts\n1,1,2024-01-01\n", encoding="utf-8"
    )
    (star / "fact_quality_metrics.csv").write_text(
        "id,column_id,metric,value\n1,1,acc,1.0\n", encoding="utf-8"
    )
    return star


# ---------- tests ----------


def test_generator_default_scaffolds_without_templates(tmp_path: Path):
    """No templates on disk -> default placeholders and JSON created."""
    star_dir = _write_star(tmp_path)
    outdir = tmp_path / "pkg"
    outdir.mkdir()

    # Provide a real dim_time.csv (to test copy behavior)
    dim_src = tmp_path / "dim_time.csv"
    dim_src.write_text("time_id,date\n20240101,2024-01-01\n", encoding="utf-8")

    result = generate_powerbi_package(
        star_dir=star_dir,
        output_dir=outdir,
        base_folder="./dist",
        dim_time_path=dim_src,
    )

    files = result["files"]
    # Template handling:
    # - If a real model.pbit exists, ensure it exists (optionally validate zip)
    # - Else, expect model.pbit.README guidance file.
    pbit_path = files.get("model.pbit")
    readme_path = files.get("model.pbit.README")
    if pbit_path:
        assert Path(pbit_path).exists()
        # Optional: ensure it's a valid Power BI template (zip container)
        # import zipfile
        # assert zipfile.is_zipfile(pbit_path)
    else:
        assert (
            readme_path is not None and Path(readme_path).exists()
        ), "Expected either model.pbit or model.pbit.README when no templates are present"

    # params / relationships present
    assert "parameters.json" in files and Path(files["parameters.json"]).exists()
    assert "relationships.json" in files and Path(files["relationships.json"]).exists()

    # star csvs copied
    assert result["star_count"] == 4
    for name in (
        "dim_dataset.csv",
        "dim_column.csv",
        "fact_profile_runs.csv",
        "fact_quality_metrics.csv",
    ):
        assert name in files and Path(files[name]).exists()

    # dim_time copied into time/
    assert result["has_time"] is True
    assert "dim_time.csv" in files
    assert Path(files["dim_time.csv"]).parent.name == "time"
    assert Path(result["output_dir"]).exists()

    # README exists
    assert (outdir / "README.txt").exists()


def test_generator_with_templates(monkeypatch, tmp_path: Path):
    """Templates override default outputs; has_time False when not provided."""
    # Create fake templates dir structure
    tpl_dir = tmp_path / "tpl"
    tpl_dir.mkdir()
    (tpl_dir / "model.pbit").write_text("fake-binary-not-really", encoding="utf-8")
    (tpl_dir / "parameters.json.j2").write_text(
        '{{ "parameters": [ {"name": "BaseFolder", "currentValue": "'
        + "{{ base_folder }}"
        + '"} ] }}',
        encoding="utf-8",
    )
    (tpl_dir / "relationships.json.j2").write_text(
        json.dumps({"tables": {"X": {}}, "relationships": []}),
        encoding="utf-8",
    )

    # Monkeypatch template dir discovery
    monkeypatch.setattr(
        "data_quality_toolkit.exporters.bi.powerbi_zero_config.generator._get_template_dir",
        lambda: tpl_dir,
    )

    star_dir = _write_star(tmp_path)
    outdir = tmp_path / "pkg"
    outdir.mkdir()

    result = generate_powerbi_package(
        star_dir=star_dir,
        output_dir=outdir,
        base_folder="/my/base",
        dim_time_path=None,  # not provided
    )

    files = result["files"]

    # model came from template
    assert (
        "model.pbit" in files
        and Path(files["model.pbit"]).read_text(encoding="utf-8") == "fake-binary-not-really"
    )

    # parameters rendered via Jinja
    params = json.loads(Path(files["parameters.json"]).read_text(encoding="utf-8"))
    assert params["parameters"][0]["currentValue"] == "/my/base"

    # relationships rendered via Jinja
    rel = json.loads(Path(files["relationships.json"]).read_text(encoding="utf-8"))
    assert "tables" in rel and rel["tables"] == {"X": {}}

    # no time provided -> has_time False and no dim_time.csv in files map
    assert result["has_time"] is False
    assert "dim_time.csv" not in files


def test_generator_skips_same_file_copy_for_dim_time(tmp_path: Path):
    """When dim_time_path already equals destination, copy is skipped (no error)."""
    star_dir = _write_star(tmp_path)
    outdir = tmp_path / "pkg"
    outdir.mkdir()
    # Pre-create destination dim_time.csv
    time_dir = outdir / "time"
    time_dir.mkdir()
    dst = time_dir / "dim_time.csv"
    dst.write_text("time_id,date\n20240101,2024-01-01\n", encoding="utf-8")

    result = generate_powerbi_package(
        star_dir=star_dir,
        output_dir=outdir,
        base_folder="./dist",
        dim_time_path=dst,  # same path
    )

    # Still recorded in files, file exists
    assert result["has_time"] is True
    assert "dim_time.csv" in result["files"]
    assert Path(result["files"]["dim_time.csv"]).exists()


def test_parameters_template_windows_path_json_safe(monkeypatch, tmp_path: Path):
    # Fake templates with our updated parameters.json.j2
    tpl_dir = tmp_path / "tpl"
    tpl_dir.mkdir()
    (tpl_dir / "model.pbit").write_text("stub", encoding="utf-8")
    (tpl_dir / "relationships.json.j2").write_text(
        json.dumps({"tables": {"X": {}}, "relationships": []}), encoding="utf-8"
    )
    (tpl_dir / "parameters.json.j2").write_text(
        '{ "parameters": [ { "name": "BaseFolder", "type": "Text", "currentValue": {{ base_folder_json | safe }} } ] }',
        encoding="utf-8",
    )

    # Use our template dir
    monkeypatch.setattr(
        "data_quality_toolkit.exporters.bi.powerbi_zero_config.generator._get_template_dir",
        lambda: tpl_dir,
    )

    # Minimal star + out
    star_dir = tmp_path / "star_src"
    star_dir.mkdir()
    (star_dir / "dim_dataset.csv").write_text("dataset_id,name\n1,foo\n", encoding="utf-8")
    (star_dir / "dim_column.csv").write_text(
        "column_id,dataset_id,name\n1,1,col\n", encoding="utf-8"
    )
    (star_dir / "fact_profile_runs.csv").write_text(
        "id,dataset_id,ts\n1,1,2024-01-01\n", encoding="utf-8"
    )
    (star_dir / "fact_quality_metrics.csv").write_text(
        "id,column_id,metric,value\n1,1,acc,1.0\n", encoding="utf-8"
    )
    outdir = tmp_path / "pkg"
    outdir.mkdir()

    # Windows-like path (backslashes)
    win_base = r"C:\data\dist"

    res = generate_powerbi_package(
        star_dir=star_dir,
        output_dir=outdir,
        base_folder=win_base,
        dim_time_path=None,
    )

    params_path = Path(res["files"]["parameters.json"])
    payload = json.loads(params_path.read_text(encoding="utf-8"))
    assert payload["parameters"][0]["currentValue"] == win_base
