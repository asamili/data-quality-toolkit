from __future__ import annotations

import argparse
import json
from unittest.mock import MagicMock

import data_quality_toolkit.adapters.cli.main as cli


def _ns(**kwargs):
    d = {
        "config": None,
        "run_id": "test-run",
        "sessions_root": ".sessions",
        "extract": None,
        "transform": None,
        "load": None,
        "assess": False,
        "manifest": False,
        "no_json": False,
    }
    d.update(kwargs)
    return argparse.Namespace(**d)


def _make_mock_pipeline(monkeypatch):
    mock_pipeline = MagicMock()
    mock_pipeline.extract.return_value = mock_pipeline
    mock_pipeline.transform.return_value = mock_pipeline
    mock_pipeline.load.return_value = mock_pipeline
    mock_pipeline.assess.return_value = mock_pipeline
    mock_pipeline.manifest.return_value = mock_pipeline
    from data_quality_toolkit.application.workflow.elt_pipeline import ELTResult

    mock_pipeline.run.return_value = ELTResult(
        run_id="test-run", status="success", steps_executed=[], manifest=None
    )
    monkeypatch.setattr(
        "data_quality_toolkit.api.create_elt_pipeline", lambda *a, **kw: mock_pipeline
    )
    return mock_pipeline


def test_cmd_pipeline_run_no_steps(monkeypatch, capsys):
    mock_pipeline = _make_mock_pipeline(monkeypatch)
    rc = cli.cmd_pipeline_run(_ns())
    assert rc == 0
    mock_pipeline.extract.assert_not_called()
    mock_pipeline.transform.assert_not_called()
    mock_pipeline.load.assert_not_called()
    mock_pipeline.assess.assert_not_called()
    mock_pipeline.manifest.assert_not_called()
    out = json.loads(capsys.readouterr().out)
    assert out["run_id"] == "test-run"
    assert out["status"] == "success"


def test_cmd_pipeline_run_all_steps(monkeypatch, capsys):
    mock_pipeline = _make_mock_pipeline(monkeypatch)
    from data_quality_toolkit.application.workflow.elt_pipeline import ELTResult, ELTStep

    steps = [
        ELTStep("extract", "extract", {"source": "in.csv", "kind": "bronze"}),
        ELTStep("transform", "clean", {"description": None}),
        ELTStep("load", "load", {"output": "out.csv", "kind": "silver"}),
        ELTStep("assess", "assess", {"description": None}),
        ELTStep("manifest", "manifest", {}),
    ]
    mock_pipeline.run.return_value = ELTResult(
        run_id="test-run", status="success", steps_executed=steps, manifest=None
    )
    rc = cli.cmd_pipeline_run(
        _ns(extract="in.csv", transform="clean", load="out.csv", assess=True, manifest=True)
    )
    assert rc == 0
    mock_pipeline.extract.assert_called_once_with("in.csv")
    mock_pipeline.transform.assert_called_once_with(name="clean")
    mock_pipeline.load.assert_called_once_with("out.csv")
    mock_pipeline.assess.assert_called_once_with()
    mock_pipeline.manifest.assert_called_once_with()
    out = json.loads(capsys.readouterr().out)
    assert len(out["steps_executed"]) == 5


def test_cmd_pipeline_run_extract_and_manifest_only(monkeypatch, capsys):
    mock_pipeline = _make_mock_pipeline(monkeypatch)
    rc = cli.cmd_pipeline_run(_ns(extract="data.csv", manifest=True))
    assert rc == 0
    mock_pipeline.extract.assert_called_once_with("data.csv")
    mock_pipeline.transform.assert_not_called()
    mock_pipeline.load.assert_not_called()
    mock_pipeline.assess.assert_not_called()
    mock_pipeline.manifest.assert_called_once_with()


def test_cmd_pipeline_run_no_json_suppresses_stdout(monkeypatch, capsys):
    _make_mock_pipeline(monkeypatch)
    rc = cli.cmd_pipeline_run(_ns(no_json=True))
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_build_parser_registers_pipeline_run():
    p = cli.build_parser()
    args = p.parse_args(["pipeline", "run", "--run-id", "x", "--sessions-root", "y"])
    assert args.func is cli.cmd_pipeline_run
    assert args.run_id == "x"
    assert args.sessions_root == "y"
    assert args.extract is None
    assert args.manifest is False


# ---------------------------------------------------------------------------
# --config flag tests
# ---------------------------------------------------------------------------


def test_build_parser_has_config_flag():
    p = cli.build_parser()
    args = p.parse_args(
        ["pipeline", "run", "--config", "pipeline.yaml", "--run-id", "x", "--sessions-root", "y"]
    )
    assert args.config == "pipeline.yaml"
    assert args.run_id == "x"


def test_cmd_pipeline_run_config_only(monkeypatch, tmp_path, capsys):
    cfg = tmp_path / "pipeline.yaml"
    cfg.write_text(
        "run_id: cfg-run\nsessions_root: ./s\nextract: in.csv\ntransform: clean\n"
        "load: out.csv\nassess: true\nmanifest: true\n",
        encoding="utf-8",
    )
    mock_pipeline = _make_mock_pipeline(monkeypatch)
    from data_quality_toolkit.application.workflow.elt_pipeline import ELTResult

    mock_pipeline.run.return_value = ELTResult(
        run_id="cfg-run", status="success", steps_executed=[], manifest=None
    )
    rc = cli.cmd_pipeline_run(_ns(config=str(cfg), run_id=None, sessions_root=None))
    assert rc == 0
    mock_pipeline.extract.assert_called_once_with("in.csv")
    mock_pipeline.transform.assert_called_once_with(name="clean")
    mock_pipeline.load.assert_called_once_with("out.csv")
    mock_pipeline.assess.assert_called_once_with()
    mock_pipeline.manifest.assert_called_once_with()
    out = json.loads(capsys.readouterr().out)
    assert out["run_id"] == "cfg-run"


def test_cmd_pipeline_run_cli_overrides_config(monkeypatch, tmp_path, capsys):
    cfg = tmp_path / "pipeline.yaml"
    cfg.write_text("run_id: cfg-run\nsessions_root: ./s\nextract: old.csv\n", encoding="utf-8")
    mock_pipeline = _make_mock_pipeline(monkeypatch)
    rc = cli.cmd_pipeline_run(
        _ns(config=str(cfg), run_id=None, sessions_root=None, extract="new.csv")
    )
    assert rc == 0
    mock_pipeline.extract.assert_called_once_with("new.csv")


def test_cmd_pipeline_run_missing_run_id(monkeypatch, capsys):
    _make_mock_pipeline(monkeypatch)
    rc = cli.cmd_pipeline_run(_ns(run_id=None, sessions_root=".sessions"))
    assert rc == 2
    assert "--run-id" in capsys.readouterr().err


def test_cmd_pipeline_run_missing_sessions_root(monkeypatch, capsys):
    _make_mock_pipeline(monkeypatch)
    rc = cli.cmd_pipeline_run(_ns(run_id="x", sessions_root=None))
    assert rc == 2
    assert "--sessions-root" in capsys.readouterr().err


def test_cmd_pipeline_run_config_not_found(monkeypatch, capsys):
    _make_mock_pipeline(monkeypatch)
    rc = cli.cmd_pipeline_run(_ns(config="missing.yaml", run_id=None, sessions_root=None))
    assert rc == 2
    assert "not found" in capsys.readouterr().err


def test_cmd_pipeline_run_config_invalid_yaml(monkeypatch, tmp_path, capsys):
    cfg = tmp_path / "pipeline.yaml"
    cfg.write_text("run_id: [\nbad yaml", encoding="utf-8")
    _make_mock_pipeline(monkeypatch)
    rc = cli.cmd_pipeline_run(_ns(config=str(cfg), run_id=None, sessions_root=None))
    assert rc == 2
    assert "Invalid YAML" in capsys.readouterr().err


def test_cmd_pipeline_run_config_unknown_key(monkeypatch, tmp_path, capsys):
    cfg = tmp_path / "pipeline.yaml"
    cfg.write_text("run_id: r\nsessions_root: ./s\nunknown_field: oops\n", encoding="utf-8")
    _make_mock_pipeline(monkeypatch)
    rc = cli.cmd_pipeline_run(_ns(config=str(cfg), run_id=None, sessions_root=None))
    assert rc == 2
    assert "unknown key" in capsys.readouterr().err
