"""Unit tests for the public api.send_drift_notification seam.

No real network: the threshold readers and the webhook transport are faked.
"""

from __future__ import annotations

from typing import Any

import pytest

from data_quality_toolkit import api
from data_quality_toolkit.adapters.notifications import webhook
from data_quality_toolkit.shared.exceptions import NotificationError

_SUMMARY_LOW = {
    "total_runs": 5,
    "drifted_runs": 1,
    "non_drifted_runs": 4,
    "drift_rate": 0.2,
    "latest_run_id": "r5",
    "latest_created_at": "2026-01-01T00:00:00+00:00",
}
_SUMMARY_HIGH = dict(_SUMMARY_LOW, drift_rate=0.9, drifted_runs=4)

_COLUMNS = [
    {"column_name": "a", "psi": 0.05},
    {"column_name": "b", "psi": 0.40},
]


def _patch_readers(monkeypatch, summary=_SUMMARY_LOW, columns=_COLUMNS) -> None:
    monkeypatch.setattr(api, "summarize_drift_trends_sqlite", lambda *a, **k: summary)
    monkeypatch.setattr(api, "read_drift_columns_sqlite", lambda *a, **k: columns)


def test_dry_run_builds_payload_no_network(monkeypatch) -> None:
    _patch_readers(monkeypatch)

    def _boom(*a: Any, **k: Any) -> int:
        raise AssertionError("post_json must not be called in dry-run")

    monkeypatch.setattr(webhook, "post_json", _boom)

    result = api.send_drift_notification(
        "m.db", "https://hooks.example.com/x?token=zzz", dry_run=True
    )
    assert result["sent"] is False
    assert result["status"] is None
    assert result["redacted_url"] == "https://hooks.example.com/x"
    payload = result["payload"]
    assert payload["tool"] == "data-quality-toolkit"
    assert payload["event"] == "drift_threshold_check"
    assert payload["drift_summary"]["drift_rate"] == 0.2
    assert payload["status"] == "ok"
    # payload never carries the webhook URL or token
    assert "zzz" not in str(payload)


def test_breach_sets_breached_and_offenders(monkeypatch) -> None:
    _patch_readers(monkeypatch, summary=_SUMMARY_HIGH)
    result = api.send_drift_notification(
        "m.db",
        "https://hooks.example.com/x",
        max_drift_rate=0.2,
        max_psi=0.2,
        dry_run=True,
    )
    assert result["breached"] is True
    assert result["payload"]["status"] == "breach"
    offenders = result["payload"]["columns_breached"]
    assert {o["column_name"] for o in offenders} == {"b"}


def test_send_refused_when_network_disabled(monkeypatch) -> None:
    _patch_readers(monkeypatch)
    monkeypatch.delenv("DQT_ALLOW_NETWORK", raising=False)
    with pytest.raises(NotificationError):
        api.send_drift_notification("m.db", "https://hooks.example.com/x", dry_run=False, send=True)


def test_send_succeeds_when_allowed_and_transport_mocked(monkeypatch) -> None:
    _patch_readers(monkeypatch)
    monkeypatch.setenv("DQT_ALLOW_NETWORK", "true")
    captured: dict[str, Any] = {}

    monkeypatch.setattr(webhook, "validate_webhook_url", lambda url, **k: webhook.redact_url(url))

    def _fake_post(url: Any, payload: Any, *, version: str, timeout: float = 10.0, **k: Any) -> int:
        captured["timeout"] = timeout
        captured["version"] = version
        return 200

    monkeypatch.setattr(webhook, "post_json", _fake_post)

    result = api.send_drift_notification(
        "m.db", "https://hooks.example.com/x", dry_run=False, send=True, timeout=7.0
    )
    assert result["sent"] is True
    assert result["status"] == 200
    assert captured["timeout"] == 7.0


def test_send_false_is_dry_run_even_with_network(monkeypatch) -> None:
    _patch_readers(monkeypatch)
    monkeypatch.setenv("DQT_ALLOW_NETWORK", "true")

    def _boom(*a: Any, **k: Any) -> int:
        raise AssertionError("must not send when send=False")

    monkeypatch.setattr(webhook, "post_json", _boom)
    result = api.send_drift_notification("m.db", "https://hooks.example.com/x", send=False)
    assert result["sent"] is False


def test_seam_present_on_both_interfaces() -> None:
    import data_quality_toolkit.adapters.cli.main as cli

    assert callable(api.send_drift_notification)
    assert callable(cli.send_drift_notification)
