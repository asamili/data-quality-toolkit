"""Webhook delivery transport: URL validation (SSRF guard), redaction, and a
single-attempt JSON POST built on the standard library only.

No third-party HTTP client (no requests/httpx/aiohttp), no retries, no scheduler,
no daemon, no secret persistence. Redirects are refused. Proxies are disabled so
``*_proxy`` environment variables cannot be used to bypass the SSRF guard.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from data_quality_toolkit.shared.exceptions import NotificationError, WebhookSecurityError

DEFAULT_TIMEOUT = 10.0
MAX_BODY_BYTES = 64 * 1024

# Cloud instance-metadata endpoints (also covered by link-local, listed for clarity).
_METADATA_HOSTS = frozenset({"169.254.169.254", "fd00:ec2::254"})

Resolver = Callable[..., list[Any]]
# Any opener exposing ``.open(request, timeout=...)``; injectable for tests.
OpenerFactory = Callable[[], Any]


def redact_url(url: str) -> str:
    """Return a log-safe URL with userinfo, query, and fragment stripped.

    Tokens commonly hide in query strings or in ``user:pass@`` userinfo; this keeps
    only ``scheme://host[:port]/path`` so messages and logs never leak secrets.
    """
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return "<unparseable-url>"
    host = parts.hostname or ""
    if not host:
        return "<redacted-url>"
    if parts.port:
        host = f"{host}:{parts.port}"
    scheme = (parts.scheme or "").lower()
    path = parts.path or ""
    return f"{scheme}://{host}{path}" if scheme else f"//{host}{path}"


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True when *ip* is not a safe public destination (SSRF guard)."""
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or str(ip) in _METADATA_HOSTS
    )


def validate_webhook_url(
    url: str,
    *,
    allow_http: bool = False,
    allow_insecure_host: bool = False,
    resolver: Resolver = socket.getaddrinfo,
) -> str:
    """Validate *url* for safe webhook delivery; return its redacted form.

    Enforces: https-only by default (http only with *allow_http*), http(s) schemes
    only, a present hostname, and — unless *allow_insecure_host* is set — that EVERY
    resolved IP address is a public address (rejecting loopback, private, link-local,
    multicast, reserved, unspecified, and cloud-metadata ranges). Raises
    WebhookSecurityError on any failure. *resolver* is injectable for tests so no
    real DNS/network is required.
    """
    redacted = redact_url(url)
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError as exc:
        raise WebhookSecurityError(
            f"invalid webhook URL: {redacted}",
            hint="provide a valid https:// URL",
        ) from exc

    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise WebhookSecurityError(
            f"unsupported webhook URL scheme '{scheme or '(none)'}': {redacted}",
            hint="only http(s) URLs are allowed; use https",
        )
    if scheme == "http" and not allow_http:
        raise WebhookSecurityError(
            f"refusing plain-http webhook URL: {redacted}",
            hint="use https, or pass --allow-http for a trusted local endpoint",
        )

    host = parts.hostname
    if not host:
        raise WebhookSecurityError(
            f"webhook URL has no host: {redacted}",
            hint="provide a full https:// URL including a hostname",
        )

    if allow_insecure_host:
        return redacted

    port = parts.port or (443 if scheme == "https" else 80)
    _assert_public_host(host, port, redacted, resolver)
    return redacted


def _assert_public_host(host: str, port: int, redacted: str, resolver: Resolver) -> None:
    """Resolve *host* and raise WebhookSecurityError if any IP is non-public."""
    try:
        infos = resolver(host, port, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise WebhookSecurityError(
            f"could not resolve webhook host: {redacted}",
            hint="check that the hostname is correct and resolvable",
        ) from exc

    addrs = {info[4][0] for info in infos}
    if not addrs:
        raise WebhookSecurityError(f"webhook host did not resolve: {redacted}")

    for addr in addrs:
        try:
            ip = ipaddress.ip_address(addr.split("%", 1)[0])
        except ValueError as exc:
            raise WebhookSecurityError(
                f"webhook host resolved to an invalid address: {redacted}"
            ) from exc
        if _is_blocked_ip(ip):
            raise WebhookSecurityError(
                f"refusing to POST to a non-public address for {redacted}",
                hint=(
                    "the webhook host resolves to a private/loopback/link-local/"
                    "metadata address (SSRF guard); use --allow-insecure-host only "
                    "for trusted local testing"
                ),
            )


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse to follow redirects (a redirect could escape the validated host)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise WebhookSecurityError(
            f"refusing to follow webhook redirect to {redact_url(newurl)}",
            hint="redirects are disabled for webhook delivery",
        )


def _build_opener() -> urllib.request.OpenerDirector:
    # ProxyHandler({}) disables *_proxy env vars so they cannot bypass the SSRF guard.
    return urllib.request.build_opener(_NoRedirectHandler, urllib.request.ProxyHandler({}))


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    version: str,
    timeout: float = DEFAULT_TIMEOUT,
    opener_factory: OpenerFactory = _build_opener,
) -> int:
    """POST *payload* as JSON to *url* once and return the HTTP status code.

    Single attempt, no retries. Mandatory timeout. 2xx is success; any non-2xx,
    timeout, or transport error raises NotificationError with a redacted message.
    Callers MUST validate *url* with :func:`validate_webhook_url` first.
    *opener_factory* is injectable for tests so no real network is required.
    """
    body = json.dumps(payload).encode("utf-8")
    if len(body) > MAX_BODY_BYTES:
        raise NotificationError(
            f"notification payload too large ({len(body)} bytes)",
            hint=f"payload exceeds the {MAX_BODY_BYTES}-byte limit",
        )

    redacted = redact_url(url)
    request = urllib.request.Request(  # noqa: S310  (scheme pre-validated by validate_webhook_url)
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"data-quality-toolkit/{version}",
        },
    )
    opener = opener_factory()
    try:
        with opener.open(request, timeout=timeout) as resp:  # noqa: S310
            status = int(getattr(resp, "status", 0) or resp.getcode())
    except WebhookSecurityError:
        raise
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        if 200 <= status < 300:
            return status
        raise NotificationError(
            f"webhook returned HTTP {status} for {redacted}",
            hint="the endpoint rejected the notification",
        ) from exc
    except OSError as exc:  # URLError and TimeoutError are OSError subclasses
        raise NotificationError(
            f"failed to POST webhook to {redacted}: {type(exc).__name__}",
            hint="check connectivity, the URL, and the --timeout value",
        ) from exc

    if not (200 <= status < 300):
        raise NotificationError(f"webhook returned HTTP {status} for {redacted}")
    return status
