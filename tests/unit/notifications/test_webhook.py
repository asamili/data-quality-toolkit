"""Unit tests for the stdlib webhook transport (SSRF guard, redaction, POST).

No real network: DNS resolution and the URL opener are injected as fakes.
"""

from __future__ import annotations

import urllib.error
from typing import Any

import pytest

from data_quality_toolkit.adapters.notifications import webhook
from data_quality_toolkit.shared.exceptions import NotificationError, WebhookSecurityError


def _resolver_for(*ips: str):
    """Return a fake socket.getaddrinfo yielding the given IPs."""

    def _fake(host: str, port: int, proto: int = 0, **_: Any) -> list[Any]:
        return [(2, 1, 6, "", (ip, port)) for ip in ips]

    return _fake


class _FakeResp:
    def __init__(self, status: int) -> None:
        self.status = status

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *_: Any) -> None:
        return None


class _FakeOpener:
    def __init__(self, status: int = 200, exc: Exception | None = None) -> None:
        self.status = status
        self.exc = exc
        self.captured: dict[str, Any] = {}

    def open(self, request: Any, timeout: float | None = None) -> _FakeResp:
        self.captured["request"] = request
        self.captured["timeout"] = timeout
        if self.exc is not None:
            raise self.exc
        return _FakeResp(self.status)


# --- redaction -------------------------------------------------------------


def test_redact_url_strips_query_userinfo_fragment() -> None:
    out = webhook.redact_url("https://user:secret@hooks.example.com/path?token=abc#frag")
    assert out == "https://hooks.example.com/path"
    assert "secret" not in out
    assert "token" not in out
    assert "abc" not in out
    assert "frag" not in out


def test_redact_url_keeps_port() -> None:
    assert webhook.redact_url("https://h.example.com:8443/p?x=1") == "https://h.example.com:8443/p"


# --- scheme validation -----------------------------------------------------


def test_validate_accepts_https_public_host() -> None:
    redacted = webhook.validate_webhook_url(
        "https://hooks.example.com/x?token=zzz", resolver=_resolver_for("93.184.216.34")
    )
    assert redacted == "https://hooks.example.com/x"


def test_validate_rejects_http_by_default() -> None:
    with pytest.raises(WebhookSecurityError):
        webhook.validate_webhook_url(
            "http://hooks.example.com/x", resolver=_resolver_for("93.184.216.34")
        )


def test_validate_accepts_http_with_allow_http() -> None:
    redacted = webhook.validate_webhook_url(
        "http://hooks.example.com/x",
        allow_http=True,
        resolver=_resolver_for("93.184.216.34"),
    )
    assert redacted == "http://hooks.example.com/x"


def test_validate_rejects_non_http_scheme() -> None:
    with pytest.raises(WebhookSecurityError):
        webhook.validate_webhook_url("ftp://h.example.com/x", resolver=_resolver_for("1.2.3.4"))


def test_validate_rejects_file_scheme() -> None:
    with pytest.raises(WebhookSecurityError):
        webhook.validate_webhook_url("file:///etc/passwd", resolver=_resolver_for("1.2.3.4"))


# --- SSRF guard ------------------------------------------------------------


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",  # loopback
        "10.0.0.5",  # private
        "192.168.1.10",  # private
        "172.16.0.1",  # private
        "169.254.169.254",  # link-local / cloud metadata
        "0.0.0.0",  # unspecified  # noqa: S104
        "::1",  # IPv6 loopback
        "fc00::1",  # IPv6 unique-local (private)
        "fd00:ec2::254",  # IPv6 metadata
    ],
)
def test_validate_blocks_non_public_addresses(ip: str) -> None:
    with pytest.raises(WebhookSecurityError):
        webhook.validate_webhook_url("https://internal.example.com/x", resolver=_resolver_for(ip))


def test_validate_blocks_localhost() -> None:
    with pytest.raises(WebhookSecurityError):
        webhook.validate_webhook_url("https://localhost/x", resolver=_resolver_for("127.0.0.1"))


def test_validate_blocks_metadata_ip_literal() -> None:
    with pytest.raises(WebhookSecurityError):
        webhook.validate_webhook_url(
            "https://169.254.169.254/latest/meta-data",
            resolver=_resolver_for("169.254.169.254"),
        )


def test_validate_blocks_when_any_resolved_ip_is_private() -> None:
    # One public + one private IP -> must reject (every IP must pass).
    with pytest.raises(WebhookSecurityError):
        webhook.validate_webhook_url(
            "https://mixed.example.com/x",
            resolver=_resolver_for("93.184.216.34", "10.0.0.1"),
        )


def test_validate_allow_insecure_host_bypasses_resolution() -> None:
    # Should not even call the resolver; localhost permitted for local testing.
    def _boom(*_: Any, **__: Any) -> list[Any]:
        raise AssertionError("resolver must not be called when allow_insecure_host=True")

    redacted = webhook.validate_webhook_url(
        "https://localhost:9000/x", allow_insecure_host=True, resolver=_boom
    )
    assert redacted == "https://localhost:9000/x"


def test_validate_error_message_is_redacted() -> None:
    with pytest.raises(WebhookSecurityError) as exc:
        webhook.validate_webhook_url(
            "https://localhost/x?token=supersecret", resolver=_resolver_for("127.0.0.1")
        )
    assert "supersecret" not in str(exc.value)


# --- POST ------------------------------------------------------------------


def test_post_json_success_returns_status_and_passes_timeout() -> None:
    opener = _FakeOpener(status=204)
    status = webhook.post_json(
        "https://h.example.com/x",
        {"a": 1},
        version="9.9.9",
        timeout=4.5,
        opener_factory=lambda: opener,
    )
    assert status == 204
    assert opener.captured["timeout"] == 4.5
    req = opener.captured["request"]
    assert req.method == "POST"
    assert req.get_header("Content-type") == "application/json"
    assert req.get_header("User-agent") == "data-quality-toolkit/9.9.9"
    assert req.data == b'{"a": 1}'


def test_post_json_non_2xx_raises() -> None:
    err = urllib.error.HTTPError("https://h/x", 500, "err", {}, None)  # type: ignore[arg-type]
    with pytest.raises(NotificationError):
        webhook.post_json(
            "https://h.example.com/x",
            {"a": 1},
            version="1.0",
            opener_factory=lambda: _FakeOpener(exc=err),
        )


def test_post_json_timeout_raises_redacted() -> None:
    with pytest.raises(NotificationError) as exc:
        webhook.post_json(
            "https://h.example.com/x?token=zzz",
            {"a": 1},
            version="1.0",
            opener_factory=lambda: _FakeOpener(exc=TimeoutError("timed out")),
        )
    assert "zzz" not in str(exc.value)


def test_post_json_url_error_raises() -> None:
    with pytest.raises(NotificationError):
        webhook.post_json(
            "https://h.example.com/x",
            {"a": 1},
            version="1.0",
            opener_factory=lambda: _FakeOpener(exc=urllib.error.URLError("no route")),
        )


def test_post_json_payload_too_large_raises() -> None:
    big = {"blob": "x" * (webhook.MAX_BODY_BYTES + 1)}
    with pytest.raises(NotificationError):
        webhook.post_json(
            "https://h.example.com/x",
            big,
            version="1.0",
            opener_factory=lambda: _FakeOpener(),
        )


def test_redirect_handler_refuses() -> None:
    handler = webhook._NoRedirectHandler()
    with pytest.raises(WebhookSecurityError):
        handler.redirect_request(None, None, 302, "Found", {}, "https://evil.example.com/x")
