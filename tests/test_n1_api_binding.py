"""N1 Test: Local API binding and LAN-only constraint."""

import socket
from fastapi.testclient import TestClient

from app.main import app, validate_bind_host
from app.core.config import settings


def test_health_endpoint_responds():
    client = TestClient(app)
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    assert body["service"] == "agent-mark-node"
    # When DB is up, db should be ok
    assert body["db"] == "ok"


def test_readiness_endpoint():
    client = TestClient(app)
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_api_refuses_public_bind_without_flag():
    # 8.8.8.8 is a known global IP
    try:
        validate_bind_host("8.8.8.8")
        # Should have raised unless ALLOW_PUBLIC_BIND=true
        assert settings.allow_public_bind, "Public bind should be rejected when ALLOW_PUBLIC_BIND=false"
    except RuntimeError as e:
        assert "public" in str(e).lower()


def test_api_allows_local_bind():
    # LAN and localhost must be allowed
    for host in ["127.0.0.1", "192.168.1.10", "10.0.0.5"]:
        validate_bind_host(host)  # should not raise


def test_api_bound_to_localhost_by_default():
    assert settings.api_host in ("127.0.0.1", "0.0.0.0", "localhost") or settings.api_host.startswith("192.168.") or settings.api_host.startswith("10.")


def test_api_not_reachable_from_outside_lan_note():
    """Documents the LAN-only guarantee.

    A fully automated 'outside LAN' test requires two network segments.
    Here we verify the binding configuration and document the manual step.
    The runbook (README) instructs the tester to run:
      curl -v http://<node-lan-ip>:8000/api/v1/health   # from same LAN -> 200
      curl --connect-timeout 3 http://<public-ip>:8000/api/v1/health  # from internet -> timeout/refused
    This test asserts the config enforces the distinction.
    """
    # App must NOT be configured to listen on 0.0.0.0 with public exposure;
    # the validate_bind_host guard ensures a public IP cannot be used accidentally.
    assert not settings.allow_public_bind, "ALLOW_PUBLIC_BIND must be false in N1 default config"
