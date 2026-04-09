import asyncio
import socket

import pytest
from fastapi import HTTPException

from app.routes.download import (
    _DNS_SAFE_HOST_CACHE,
    _assert_safe_remote_url,
    _is_allowed_host,
    _is_public_ip,
)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def clear_dns_cache():
    _DNS_SAFE_HOST_CACHE.clear()


def test_is_allowed_host_accepts_suffix_and_subdomain():
    assert _is_allowed_host("googlevideo.com") is True
    assert _is_allowed_host("rr1---sn.googlevideo.com") is True
    assert _is_allowed_host("evil-googlevideo.com") is False


def test_is_public_ip_distinguishes_public_vs_private():
    assert _is_public_ip("8.8.8.8") is True
    assert _is_public_ip("127.0.0.1") is False


def test_assert_safe_remote_url_rejects_disallowed_host():
    with pytest.raises(HTTPException) as exc:
        _run(_assert_safe_remote_url("https://example.com/file.mp4"))

    assert exc.value.status_code == 403
    assert "allow-list" in str(exc.value.detail)


def test_assert_safe_remote_url_rejects_private_dns_target(monkeypatch):
    def fake_getaddrinfo(host, port, type=None):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(HTTPException) as exc:
        _run(_assert_safe_remote_url("https://rr1---sn.googlevideo.com/videoplayback?id=1"))

    assert exc.value.status_code == 403
    assert "private/internal" in str(exc.value.detail)


def test_assert_safe_remote_url_accepts_public_dns_target(monkeypatch):
    def fake_getaddrinfo(host, port, type=None):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    _run(_assert_safe_remote_url("https://rr1---sn.googlevideo.com/videoplayback?id=1"))
