"""Agent Mark — Local API entrypoint (N1 skeleton).

Networking constraint per Node Architecture Section 3 / N1 spec:
  - Binds ONLY to localhost and the school LAN.
  - Never exposed to the public internet.
  - Host is controlled via API_HOST env (default 127.0.0.1); setting a
    public-routable host requires ALLOW_PUBLIC_BIND=true which is refused
    in production. In docker the LAN is represented by 0.0.0.0 (all local
    interfaces) — still LAN-only when the host firewall/NAT is correctly
    configured; the check here is a safety net, not a replacement for
    network policy.
"""

import ipaddress
import logging

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.n2 import router as n2_router
from app.core.config import settings

log = logging.getLogger(__name__)


def _is_public_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_global
    except ValueError:
        # hostname, not IP — treat as non-public for now (DNS will resolve locally)
        return False


def validate_bind_host(host: str) -> None:
    if _is_public_ip(host) and not settings.allow_public_bind:
        raise RuntimeError(
            f"Refusing to bind Local API to public IP {host!r} without ALLOW_PUBLIC_BIND=true. "
            "Per architecture Section 3, the Local API must never be exposed to the public internet. "
            "Use 127.0.0.1 (localhost) or a LAN address (e.g. 192.168.x.x, 10.x.x.x) instead."
        )


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Agent Mark node — Local API (N1 skeleton, health endpoint only)",
)

app.include_router(health_router, prefix="/api/v1")
app.include_router(n2_router, prefix="/api/v1")


@app.get("/")
def root():
    return {"service": settings.app_name, "version": settings.app_version, "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn

    validate_bind_host(settings.api_host)
    uvicorn.run("app.main:app", host=settings.api_host, port=settings.api_port, reload=False)
