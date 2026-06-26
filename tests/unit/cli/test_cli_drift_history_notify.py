"""Unit tests for the `dqt drift-history notify` command.

The API seam is faked, so no network is exercised.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import data_quality_toolkit.adapters.cli.main as cli
from data_quality_toolkit.shared.exceptions import NotificationError

_PAYLOAD_OK = {
    "tool": "data-quality-toolkit",
    "version": "9.9.9",
    "event": "drift_threshold_check",
    "generated_at": "2026-01-01T00:00:00+00:00",
    "status": "ok",
    "breached": False,
    "drift_summary": {
        "total_runs": 3,
        "drifted_runs": 0,
        "drift_rate": 0.0,
        "latest_run_id": "r3",
        "latest_created_at": "2026-01-01T00:00:00+00:00",
    },
    "thresholds": {"max_drift_rate": None, "max_psi": None},
    "columns_breached": [],
}
_PAYLOAD_BREACH = dict(_PAYLOAD_OK, status="breach", breached=True)


def _patch(monkeypatch, *, payload=_PAYLOAD_OK, sent=False, breached=False, exc=None):
    calls: dict[str, Any] = {}

    def fake_send(db_path, webhook_url, **kwargs):
        calls["db_path"] = db_path
        calls["webhook_url"] = webhook_url
        calls.update(kwargs)
        if exc is not None:
            raise exc
        return {
            "payload": payload,
            "sent": sent,
            "status": 200 if sent else None,
            "breached": breached,
            "redacted_url": "https://hooks.example.com/x",
        }

    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "send_drift_notification", fake_send)
    return calls


def test_notify_dry_run_default_prints_payload_json(monkeypatch, capsys) -> None:
    calls = _patch(monkeypatch)
    rc = cli.main(
        [
            "drift-history",
            "notify",
            "--db",
            "m.db",
            "--webhook-url",
            "https://hooks.example.com/x?token=zzz",
        ]
    )
    assert rc == 0
    out = capsys.readouterr()
    parsed = json.loads(out.out)
    assert parsed["event"] == "drift_threshold_check"
    # dry-run is the default (no --send) and reaches the seam as such
    assert calls["dry_run"] is True
    assert calls["send"] is False
    assert "dry-run" in out.err


def test_notify_stderr_has_no_secret(monkeypatch, capsys) -> None:
    _patch(monkeypatch)
    cli.main(
        [
            "drift-history",
            "notify",
            "--db",
            "m.db",
            "--webhook-url",
            "https://user:secret@hooks.example.com/x?token=zzz",
        ]
    )
    err = capsys.readouterr().err
    assert "secret" not in err
    assert "zzz" not in err
    assert "https://hooks.example.com/x" in err


def test_notify_no_json_suppresses_stdout(monkeypatch, capsys) -> None:
    _patch(monkeypatch)
    rc = cli.main(
        [
            "--no-json",
            "drift-history",
            "notify",
            "--db",
            "m.db",
            "--webhook-url",
            "https://hooks.example.com/x",
        ]
    )
    out = capsys.readouterr()
    assert rc == 0
    assert out.out == ""
    assert "dry-run" in out.err


def test_notify_breach_returns_exit_2(monkeypatch, capsys) -> None:
    _patch(monkeypatch, payload=_PAYLOAD_BREACH, breached=True)
    rc = cli.main(
        [
            "drift-history",
            "notify",
            "--db",
            "m.db",
            "--webhook-url",
            "https://hooks.example.com/x",
            "--fail-on-drift-rate",
            "0.1",
        ]
    )
    assert rc == 2
    assert "breached" in capsys.readouterr().err.lower()


def test_notify_send_flag_forwarded(monkeypatch) -> None:
    calls = _patch(monkeypatch, sent=True)
    rc = cli.main(
        [
            "drift-history",
            "notify",
            "--db",
            "m.db",
            "--webhook-url",
            "https://hooks.example.com/x",
            "--send",
            "--timeout",
            "5",
        ]
    )
    assert rc == 0
    assert calls["send"] is True
    assert calls["dry_run"] is False
    assert calls["timeout"] == 5.0


def test_notify_send_failure_returns_exit_1(monkeypatch, capsys) -> None:
    _patch(monkeypatch, exc=NotificationError("real webhook send refused: network is disabled"))
    rc = cli.main(
        [
            "drift-history",
            "notify",
            "--db",
            "m.db",
            "--webhook-url",
            "https://hooks.example.com/x",
            "--send",
        ]
    )
    assert rc == 1
    assert "Error:" in capsys.readouterr().err


def test_notify_missing_required_args_exits_2(monkeypatch) -> None:
    _patch(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        cli.main(["drift-history", "notify", "--db", "m.db"])  # missing --webhook-url
    assert exc.value.code == 2


def test_notify_dry_run_and_send_mutually_exclusive(monkeypatch) -> None:
    _patch(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "drift-history",
                "notify",
                "--db",
                "m.db",
                "--webhook-url",
                "https://hooks.example.com/x",
                "--dry-run",
                "--send",
            ]
        )
    assert exc.value.code == 2
