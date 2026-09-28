"""Single supported launcher for the Local API (verification finding 2026-09-28).

The LAN-only guard (validate_bind_host) used to run only under
``if __name__ == "__main__"``, so the runbook's own ``uvicorn app.main:app``
invocation skipped it entirely. This module is now the one supported entry
point: it validates the bind host FIRST and only then starts uvicorn.
Raw ``uvicorn app.main:app`` is forbidden by the runbook.

Usage:
    python -m app.serve [--host 127.0.0.1] [--port 8000]
"""

import argparse
import sys

import uvicorn

from app.core.config import settings
from app.main import validate_bind_host


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Agent Mark node — Local API launcher (LAN-only).")
    parser.add_argument("--host", default=settings.api_host, help="Bind host (localhost or LAN only).")
    parser.add_argument("--port", type=int, default=settings.api_port, help="Bind port.")
    args = parser.parse_args(argv)
    try:
        validate_bind_host(args.host)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
