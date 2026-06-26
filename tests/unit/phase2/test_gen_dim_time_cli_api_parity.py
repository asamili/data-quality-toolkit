"""G8C3C: gen-dim-time CLI/API parity — locks current behavior before any reroute.

Three test groups:
1. Pin the exact CLI --json payload key set and value semantics.
2. Document the API DimTimeResult shape separately.
3. Assert the key names differ (guardrail for future reroute-with-mapping).

Future reroute must preserve CLI payload by mapping API result keys back to the
current CLI keys: start_date→start, end_date→end, fiscal_year_start→fiscal,
path→dim_time_path, add status="success", drop rows.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 1. CLI --json payload: lock exact key set
# ---------------------------------------------------------------------------


def test_cli_json_payload_exact_keys(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The --json payload must contain exactly these six keys — no more, no less."""
    import data_quality_toolkit.adapters.exporters.time.dim_time_generator as gen

    fake_csv = tmp_path / "time" / "dim_time.csv"
    fake_csv.parent.mkdir(parents=True, exist_ok=True)
    fake_csv.write_text("time_id,date\n20240101,2024-01-01\n", encoding="utf-8")

    monkeypatch.setattr(
        gen,
        "write_dim_time",
        lambda output_dir, start_date, end_date, week_start=1, fiscal_year_start=None: str(
            fake_csv
        ),
    )

    from data_quality_toolkit.adapters.cli import main as dqt_main

    rc = dqt_main.main(
        [
            "gen-dim-time",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-05",
            "--week-start",
            "3",
            "--fiscal",
            "4",
            "--out",
            str(tmp_path / "time"),
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload.keys()) == {
        "status",
        "dim_time_path",
        "start",
        "end",
        "week_start",
        "fiscal",
    }


# ---------------------------------------------------------------------------
# 2. CLI --json payload: lock value semantics
# ---------------------------------------------------------------------------


def test_cli_json_payload_values(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Each CLI payload value must echo the CLI input (or fixed sentinel for status/path)."""
    import data_quality_toolkit.adapters.exporters.time.dim_time_generator as gen

    fake_csv = tmp_path / "time" / "dim_time.csv"
    fake_csv.parent.mkdir(parents=True, exist_ok=True)
    fake_csv.write_text("time_id,date\n20240101,2024-01-01\n", encoding="utf-8")

    monkeypatch.setattr(
        gen,
        "write_dim_time",
        lambda output_dir, start_date, end_date, week_start=1, fiscal_year_start=None: str(
            fake_csv
        ),
    )

    from data_quality_toolkit.adapters.cli import main as dqt_main

    rc = dqt_main.main(
        [
            "gen-dim-time",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-05",
            "--week-start",
            "3",
            "--fiscal",
            "4",
            "--out",
            str(tmp_path / "time"),
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "success"
    assert payload["start"] == "2024-01-01"
    assert payload["end"] == "2024-01-05"
    assert payload["week_start"] == 3
    assert payload["fiscal"] == 4
    assert payload["dim_time_path"].endswith("dim_time.csv")


# ---------------------------------------------------------------------------
# 3. API result shape: document DimTimeResult separately
# ---------------------------------------------------------------------------


def test_api_generate_dim_time_result_shape(tmp_path: Path) -> None:
    """API DimTimeResult key set and values — documented independently of CLI."""
    from data_quality_toolkit.api import generate_dim_time

    result = generate_dim_time(
        "2024-01-01",
        "2024-01-05",
        week_start=3,
        fiscal_year_start=4,
        output_dir=tmp_path / "api_time",
    )

    assert set(result.keys()) == {
        "rows",
        "start_date",
        "end_date",
        "week_start",
        "fiscal_year_start",
        "path",
    }
    assert result["rows"] == 5
    assert result["start_date"] == "2024-01-01"
    assert result["end_date"] == "2024-01-05"
    assert result["week_start"] == 3
    assert result["fiscal_year_start"] == 4
    assert Path(result["path"]).name == "dim_time.csv"
    assert Path(result["path"]).exists()


# ---------------------------------------------------------------------------
# 4. Mismatch guardrail: future reroute MUST add a mapping shim
# ---------------------------------------------------------------------------


def test_cli_and_api_key_names_differ_reroute_requires_mapping() -> None:
    """Static guardrail: CLI payload keys ≠ API result keys.

    Any future reroute of gen-dim-time through api.generate_dim_time MUST map:
      start_date  → start
      end_date    → end
      fiscal_year_start → fiscal
      path        → dim_time_path
      (add)       status = "success"
      (drop)      rows
    Without this mapping the --json stdout contract changes for callers.
    """
    cli_json_keys = {"status", "dim_time_path", "start", "end", "week_start", "fiscal"}
    api_result_keys = {"rows", "start_date", "end_date", "week_start", "fiscal_year_start", "path"}

    assert cli_json_keys != api_result_keys

    # CLI-only keys (must be synthesised or preserved by a mapping shim)
    assert "status" not in api_result_keys
    assert "dim_time_path" not in api_result_keys
    assert "start" not in api_result_keys
    assert "end" not in api_result_keys
    assert "fiscal" not in api_result_keys

    # API-only keys (absent from CLI payload, must be dropped/renamed by shim)
    assert "rows" not in cli_json_keys
    assert "start_date" not in cli_json_keys
    assert "end_date" not in cli_json_keys
    assert "fiscal_year_start" not in cli_json_keys
    assert "path" not in cli_json_keys

    # week_start is the only shared key
    assert "week_start" in cli_json_keys & api_result_keys


# ---------------------------------------------------------------------------
# 5. Reroute proof: CLI routes through api.generate_dim_time
# ---------------------------------------------------------------------------


def test_cli_routes_through_api_generate_dim_time(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Prove cmd_gen_dim_time calls api.generate_dim_time, not the internal exporter.

    After the G8C3D reroute, the CLI must delegate to the public API seam and
    map the DimTimeResult back to the pinned CLI payload shape.
    """
    import data_quality_toolkit.api as api

    captured: dict[str, object] = {}
    fake_result = {
        "rows": 5,
        "start_date": "2024-01-01",
        "end_date": "2024-01-05",
        "week_start": 3,
        "fiscal_year_start": 4,
        "path": str(tmp_path / "time" / "dim_time.csv"),
    }

    def _fake_generate(
        start_date: str,
        end_date: str,
        *,
        week_start: int = 1,
        fiscal_year_start: int | None = None,
        output_dir: object = None,
    ) -> dict[str, object]:
        captured["start_date"] = start_date
        captured["end_date"] = end_date
        captured["week_start"] = week_start
        captured["fiscal_year_start"] = fiscal_year_start
        captured["output_dir"] = output_dir
        return fake_result

    monkeypatch.setattr(api, "generate_dim_time", _fake_generate)

    from data_quality_toolkit.adapters.cli import main as dqt_main

    rc = dqt_main.main(
        [
            "gen-dim-time",
            "--start",
            "2024-01-01",
            "--end",
            "2024-01-05",
            "--week-start",
            "3",
            "--fiscal",
            "4",
            "--out",
            str(tmp_path / "time"),
            "--json",
        ]
    )
    assert rc == 0

    # API was called with the right arguments
    assert captured["start_date"] == "2024-01-01"
    assert captured["end_date"] == "2024-01-05"
    assert captured["week_start"] == 3
    assert captured["fiscal_year_start"] == 4
    assert captured["output_dir"] == str(tmp_path / "time")

    # CLI payload still matches the locked shape and maps API result correctly
    payload = json.loads(capsys.readouterr().out)
    assert set(payload.keys()) == {
        "status",
        "dim_time_path",
        "start",
        "end",
        "week_start",
        "fiscal",
    }
    assert payload["status"] == "success"
    assert payload["dim_time_path"] == fake_result["path"]
    assert payload["start"] == "2024-01-01"
    assert payload["end"] == "2024-01-05"
    assert payload["week_start"] == 3
    assert payload["fiscal"] == 4
