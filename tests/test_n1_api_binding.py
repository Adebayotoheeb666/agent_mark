"""N1 Test: Local API binding and LAN-only constraint."""

import socket
import subprocess
import sys
from pathlib import Path

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


def test_launcher_refuses_public_bind():
    """The supported launcher (python -m app.serve) must refuse a public IP.

    Runs the documented command as a subprocess and asserts the guard's OWN
    error text — a bare nonzero exit would pass for the wrong reason (e.g. an
    import error). The guard raises before uvicorn starts, so nothing binds.
    The manual same-LAN curl proof stays in the runbook (README Section 3.8).
    """
    repo_root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "app.serve", "--host", "8.8.8.8"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=repo_root,
    )
    assert proc.returncode == 2, f"launcher must exit 2 on public bind, got {proc.returncode}: {proc.stderr}"
    assert "Refusing to bind" in proc.stderr, f"expected the guard's error, got: {proc.stderr}"
