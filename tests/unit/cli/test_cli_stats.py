"""Unit tests for the ``dqt stats`` command group."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import data_quality_toolkit.adapters.cli.main as cli


def _stats_csv(tmp_path: Path) -> Path:
    csv_path = tmp_path / "stats.csv"
    csv_path.write_text(
        "variant,score,converted\nA,10,1\nA,12,1\nA,14,1\nB,20,0\nB,22,1\nB,24,1\n",
        encoding="utf-8",
    )
    return csv_path


@pytest.fixture(autouse=True)
def _quiet_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)


@pytest.mark.parametrize(
    "argv",
    [
        ["stats", "profile", "--help"],
        ["stats", "select-test", "--help"],
        ["stats", "test", "--help"],
        ["stats", "ab", "--help"],
    ],
)
def test_stats_subcommand_help_exits_0(argv: list[str], capsys: pytest.CaptureFixture) -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(argv)
    assert exc_info.value.code == 0
    assert capsys.readouterr().out


def test_stats_profile_real_csv(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    csv_path = _stats_csv(tmp_path)

    rc = cli.main(["stats", "profile", str(csv_path), "--columns", "variant,score"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "Statistics profile complete" in captured.err
    result = json.loads(captured.out)
    assert result["status"] == "ok"
    assert result["columns"] == ["variant", "score"]
    assert result["profile"]["n_rows"] == 6
    assert result["numeric_summary"][0]["column"] == "score"


def test_stats_profile_invalid_path_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    missing = tmp_path / "missing.csv"

    rc = cli.main(["stats", "profile", str(missing)])

    captured = capsys.readouterr()
    assert rc == 1
    assert "Statistics profile" in captured.err
    result = json.loads(captured.out)
    assert result["status"] == "invalid_input"


def test_stats_select_test_maps_representative_case(capsys: pytest.CaptureFixture) -> None:
    rc = cli.main(
        [
            "stats",
            "select-test",
            "--variable-type",
            "numeric",
            "--group-structure",
            "two_independent",
            "--sigma-known",
            "false",
            "--equal-variance-assumed",
            "false",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert "TWO_T_WELCH" in captured.err
    result = json.loads(captured.out)
    assert result["status"] == "ok"
    assert result["test_key"] == "TWO_T_WELCH"


def test_stats_test_extracts_numeric_sample_and_calls_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    csv_path = _stats_csv(tmp_path)
    calls: list[tuple[str, dict]] = []

    def fake_run_statistical_test(test_key: str, **kw):
        calls.append((test_key, kw))
        return {
            "status": "ok",
            "test_key": test_key,
            "statistic": 0.0,
            "p_value": 1.0,
            "alpha": kw["alpha"],
            "reject_null": False,
            "method": "one_sample_t",
        }

    monkeypatch.setattr(cli, "run_statistical_test", fake_run_statistical_test)

    rc = cli.main(
        [
            "stats",
            "test",
            str(csv_path),
            "--test-key",
            "ONE_T",
            "--value-column",
            "score",
            "--null-mean",
            "17",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert "Statistical test" in captured.err
    test_key, kwargs = calls[0]
    assert test_key == "ONE_T"
    assert kwargs["sample"] == [10.0, 12.0, 14.0, 20.0, 22.0, 24.0]
    assert kwargs["null_mean"] == 17.0
    assert json.loads(captured.out)["status"] == "ok"


def test_stats_ab_real_numeric_csv(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    pytest.importorskip("scipy")
    csv_path = _stats_csv(tmp_path)

    rc = cli.main(
        [
            "stats",
            "ab",
            str(csv_path),
            "--group-column",
            "variant",
            "--metric-column",
            "score",
            "--group-a",
            "B",
            "--group-b",
            "A",
            "--alternative",
            "greater",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert "A/B comparison" in captured.err
    result = json.loads(captured.out)
    assert result["status"] == "ok"
    assert result["test_key"] == "TWO_T_WELCH"


def test_stats_ab_unavailable_returns_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    csv_path = _stats_csv(tmp_path)

    def fake_compare_ab(*args, **kw):
        return {
            "status": "unavailable",
            "reason": "scipy is not installed; install the stats extra",
            "test_key": "TWO_T_WELCH",
            "statistic": None,
            "p_value": None,
            "scipy_available": False,
        }

    monkeypatch.setattr(cli, "compare_ab", fake_compare_ab)

    rc = cli.main(
        [
            "stats",
            "ab",
            str(csv_path),
            "--group-column",
            "variant",
            "--metric-column",
            "score",
            "--group-a",
            "B",
            "--group-b",
            "A",
        ]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "unavailable" in captured.err
    result = json.loads(captured.out)
    assert result["status"] == "unavailable"
    assert result["scipy_available"] is False


# ── backend statistical diagnostics reach the CLI surface ────────────────────


def _real_chi_result(test_key: str, **kwargs: Any) -> dict:
    """The authoritative kernel result for a chi-square table, unmodified."""
    from data_quality_toolkit import run_statistical_test

    return dict(run_statistical_test(test_key, **kwargs))


def test_stats_test_prints_backend_warnings_and_messages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """``dqt stats test`` renders the result's own diagnostics; it decides none of them.

    ``stats test`` builds numeric samples from CSV, so the sparse chi-square table is
    injected at the public seam the command already calls. What is asserted here is the
    surfacing contract: whatever warnings and messages the kernel result carries are
    printed and serialized verbatim.
    """
    pytest.importorskip("scipy")
    csv_path = _stats_csv(tmp_path)
    backend = _real_chi_result("CHI_IND", table=[[1, 0], [0, 99]])
    monkeypatch.setattr(cli, "run_statistical_test", lambda *a, **kw: backend)

    rc = cli.main(
        ["stats", "test", str(csv_path), "--test-key", "ONE_T", "--value-column", "score"]
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert "Warning: Some expected cell counts are below 1" in captured.err
    assert "Note: Yates' continuity correction was applied" in captured.err
    payload = json.loads(captured.out)
    assert payload["warnings"] == backend["warnings"]
    assert payload["messages"] == backend["messages"]
    assert payload["assumptions"]["expected_counts"]["any_below_1"] is True


def test_stats_test_prints_no_notes_for_a_clean_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    pytest.importorskip("scipy")
    csv_path = _stats_csv(tmp_path)
    backend = _real_chi_result("CHI_GOF", observed=[30, 10, 10])
    monkeypatch.setattr(cli, "run_statistical_test", lambda *a, **kw: backend)

    rc = cli.main(
        ["stats", "test", str(csv_path), "--test-key", "ONE_T", "--value-column", "score"]
    )

    captured = capsys.readouterr()
    assert rc == 0
    assert "Warning:" not in captured.err
    assert "Note:" not in captured.err


def test_stats_cli_owns_no_expected_frequency_rule() -> None:
    import inspect

    from data_quality_toolkit.adapters.cli.commands import stats as stats_cmd

    source = inspect.getsource(stats_cmd)
    assert "_EXPECTED_SMALL_CELL" not in source
    assert "expected cell counts are below" not in source
