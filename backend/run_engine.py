"""
Start the screening engine.

    python run_engine.py [--host 127.0.0.1] [--port 8000] [--reload]

Transport:
  * If backend/certs holds the files written by `python -m scripts.make_tls_certs`
    (or ENGINE_TLS_CERT / ENGINE_TLS_KEY / ENGINE_TLS_CLIENT_CA point at others),
    the engine serves HTTPS only and requires every caller to present a client
    certificate signed by that authority (mutual TLS).
  * Otherwise it serves plain HTTP, which is only acceptable on loopback. It
    refuses to bind a non-loopback address without TLS unless
    ENGINE_ALLOW_PLAINTEXT=true is set on purpose.
"""
from __future__ import annotations

import argparse
import os
import ssl
import sys
from pathlib import Path

import uvicorn

BACKEND = Path(__file__).resolve().parent
CERTS = BACKEND / "certs"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def tls_files() -> tuple[Path, Path, Path] | None:
    cert = Path(os.getenv("ENGINE_TLS_CERT") or CERTS / "engine.pem")
    key = Path(os.getenv("ENGINE_TLS_KEY") or CERTS / "engine.key")
    client_ca = Path(os.getenv("ENGINE_TLS_CLIENT_CA") or CERTS / "ca.pem")
    return (cert, key, client_ca) if cert.is_file() and key.is_file() and client_ca.is_file() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.getenv("ENGINE_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.getenv("ENGINE_PORT", "8000")))
    ap.add_argument("--reload", action="store_true")
    args = ap.parse_args()

    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))
    options: dict = dict(host=args.host, port=args.port, reload=args.reload)
    tls = None if os.getenv("ENGINE_TLS", "").lower() == "off" else tls_files()
    if tls:
        cert, key, client_ca = tls
        options.update(
            ssl_certfile=str(cert), ssl_keyfile=str(key),
            ssl_ca_certs=str(client_ca), ssl_cert_reqs=ssl.CERT_REQUIRED,   # callers must present a certificate
            ssl_version=ssl.PROTOCOL_TLS_SERVER,
        )
        print(f"Engine: https://{args.host}:{args.port} (mutual TLS; client certificates signed by {client_ca.name} only)")
    else:
        if args.host not in LOOPBACK and os.getenv("ENGINE_ALLOW_PLAINTEXT", "").lower() != "true":
            print("Refusing to serve plain HTTP on a non-loopback address. Run `python -m scripts.make_tls_certs "
                  f"--host {args.host}` first, or set ENGINE_ALLOW_PLAINTEXT=true if a TLS proxy sits in front.",
                  file=sys.stderr)
            return 2
        print(f"Engine: http://{args.host}:{args.port} (no TLS certificates found; loopback only)")
    uvicorn.run("app.main:app", **options)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
