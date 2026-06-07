import csv
import json
from pathlib import Path

from data_quality_toolkit.adapters.exporters.bi.powerbi_zero_config import generator as gen


def _touch_csv(path: Path, headers, rows=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for r in rows:
            w.writerow(r)


def test_render_template_handles_template_syntax_error(tmp_path):
    # Build a template with a Jinja syntax error so TemplateSyntaxError occurs
    tpl = tmp_path / "bad.json.j2"
    tpl.write_text("{{ this is : not valid jinja %}}", encoding="utf-8")
    out = gen.render_template(tpl, {"x": 1})
    # on TemplateSyntaxError, function returns raw text (best-effort mode)
    assert "not valid jinja" in out


def test_render_template_unwraps_braced_json_and_best_effort_subs(tmp_path):
    # This content is wrapped in {{ ... }} and has unresolved tokens
    tpl = tmp_path / "wrap.json.j2"
    tpl.write_text('{{  "a": 1, "b": {{missing}} , "c": {{ k }} }}', encoding="utf-8")
    out = gen.render_template(tpl, {"k": 42})
    # Should become valid-ish JSON object string with best-effort replacements
    assert out.strip().startswith("{")
    assert '"a": 1' in out
    assert "42" in out  # best-effort replacement for {{ k }}


def test_generate_powerbi_package_missing_model_writes_readme(monkeypatch, tmp_path):
    star = tmp_path / "star_src"
    star.mkdir()
    _touch_csv(star / "dim_dataset.csv", ["dataset_id"])
    _touch_csv(star / "dim_column.csv", ["column_id", "dataset_id"])
    _touch_csv(star / "fact_profile_runs.csv", ["dataset_id"])  # no time_id yet
    _touch_csv(star / "fact_quality_metrics.csv", ["column_id"])

    # Provide a template dir with NO model.pbit to hit README path
    templates = tmp_path / "templates"
    templates.mkdir()
    monkeypatch.setattr(gen, "_get_template_dir", lambda: templates)

    out_dir = tmp_path / "pkg"
    result = gen.generate_powerbi_package(star_dir=star, output_dir=out_dir, base_folder="./dist")

    files = result["files"]
    # README is produced instead of a fake model.pbit
    assert "model.pbit.README" in files
    # relationships should exist even without time_id
    assert (out_dir / "relationships.json").exists()


def test_generate_powerbi_package_includes_time_relationship_when_present(monkeypatch, tmp_path):
    import csv
    from pathlib import Path

    from data_quality_toolkit.adapters.exporters.bi.powerbi_zero_config import generator as gen

    def _touch_csv(path: Path, headers, rows=()):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(headers)
            for r in rows:
                w.writerow(r)

    star = tmp_path / "star_src"
    star.mkdir()
    _touch_csv(star / "dim_dataset.csv", ["dataset_id"])
    _touch_csv(star / "dim_column.csv", ["column_id", "dataset_id"])
    # include time_id in the fact table
    _touch_csv(star / "fact_profile_runs.csv", ["dataset_id", "time_id"])
    _touch_csv(star / "fact_quality_metrics.csv", ["column_id"])

    # Provide a real dim_time.csv and pass it in so has_time=True
    dim_time_src = tmp_path / "dim_time.csv"
    _touch_csv(dim_time_src, ["time_id", "date"])

    # No templates needed; default scaffold path gets used
    monkeypatch.setattr(gen, "_get_template_dir", lambda: tmp_path / "no_templates")

    out_dir = tmp_path / "pkg2"
    res = gen.generate_powerbi_package(
        star_dir=star,
        output_dir=out_dir,
        base_folder="./dist",
        dim_time_path=dim_time_src,  # <-- critical: ensures has_time=True
    )

    assert res["has_time"] is True

    rel = json.loads((out_dir / "relationships.json").read_text(encoding="utf-8"))
    rels = rel["relationships"]
    assert any(
        r.get("from") == ["fact_profile_runs", "time_id"] and r.get("to") == ["dim_time", "time_id"]
        for r in rels
    )


def test_copy_dim_time_same_file_skips_copy(monkeypatch, tmp_path):
    star = tmp_path / "star_src"
    star.mkdir()
    _touch_csv(star / "dim_dataset.csv", ["dataset_id"])
    _touch_csv(star / "dim_column.csv", ["column_id", "dataset_id"])
    _touch_csv(star / "fact_profile_runs.csv", ["dataset_id"])
    _touch_csv(star / "fact_quality_metrics.csv", ["column_id"])

    # No templates
    monkeypatch.setattr(gen, "_get_template_dir", lambda: tmp_path / "no_templates")

    out_dir = tmp_path / "pkg3"
    (out_dir / "time").mkdir(parents=True, exist_ok=True)
    same = out_dir / "time" / "dim_time.csv"
    _touch_csv(same, ["time_id"])

    res = gen.generate_powerbi_package(
        star_dir=star, output_dir=out_dir, base_folder="./dist", dim_time_path=same
    )
    # still reports has_time True and the existing file remains
    assert res["has_time"] is True
    assert same.exists()


def test_relationships_template_corruption_falls_back_to_raw(monkeypatch, tmp_path):
    star = tmp_path / "s"
    star.mkdir()
    for name, hdr in [
        ("dim_dataset.csv", ["dataset_id"]),
        ("dim_column.csv", ["column_id", "dataset_id"]),
        ("fact_profile_runs.csv", ["dataset_id"]),
        ("fact_quality_metrics.csv", ["column_id"]),
    ]:
        _touch_csv(star / name, hdr)

    templates = tmp_path / "templates"
    templates.mkdir()
    # Invalid Jinja template triggers TemplateSyntaxError → code uses raw text
    (templates / "relationships.json.j2").write_text("{{ this is : invalid %}}", encoding="utf-8")
    monkeypatch.setattr(gen, "_get_template_dir", lambda: templates)

    out_dir = tmp_path / "pkg_bad_tpl"
    gen.generate_powerbi_package(star, out_dir)
    # File still created with the raw (invalid) content; existence proves branch was hit
    assert (out_dir / "relationships.json").exists()


def test_generate_powerbi_package_does_not_include_time_relationship_without_dim_time(
    monkeypatch, tmp_path
):
    import csv
    from pathlib import Path

    from data_quality_toolkit.adapters.exporters.bi.powerbi_zero_config import generator as gen

    def _touch_csv(path: Path, headers, rows=()):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(headers)
            for r in rows:
                w.writerow(r)

    star = tmp_path / "star_src"
    star.mkdir()
    _touch_csv(star / "dim_dataset.csv", ["dataset_id"])
    _touch_csv(star / "dim_column.csv", ["column_id", "dataset_id"])
    _touch_csv(star / "fact_profile_runs.csv", ["dataset_id", "time_id"])  # has time_id
    _touch_csv(star / "fact_quality_metrics.csv", ["column_id"])

    monkeypatch.setattr(gen, "_get_template_dir", lambda: tmp_path / "no_templates")

    out_dir = tmp_path / "pkg_no_time"
    res = gen.generate_powerbi_package(star_dir=star, output_dir=out_dir, base_folder="./dist")
    assert res["has_time"] is False

    rel = json.loads((out_dir / "relationships.json").read_text(encoding="utf-8"))
    rels = rel["relationships"]
    assert not any(
        r.get("from") == ["fact_profile_runs", "time_id"] and r.get("to") == ["dim_time", "time_id"]
        for r in rels
    )
