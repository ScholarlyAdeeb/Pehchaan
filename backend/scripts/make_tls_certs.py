"""
Issue the certificates for mutual TLS between the gateway and the engine.

Creates a private certificate authority that exists only for this
deployment, a server certificate for the engine and a client certificate for
the gateway:

    backend/certs/ca.pem        the authority both sides trust
    backend/certs/engine.pem    engine server certificate (+ engine.key)
    backend/certs/gateway.pem   gateway client certificate (+ gateway.key)

With these files present the engine serves HTTPS only and refuses any caller
that does not present a certificate signed by this authority; the gateway
verifies the engine's certificate the same way. The API key stays in place as
a second factor.

Usage (from backend/):
    python -m scripts.make_tls_certs                         local: localhost, 127.0.0.1
    python -m scripts.make_tls_certs --host engine.example.org --host 203.0.113.7
    python -m scripts.make_tls_certs --print-env             also print the values to paste into a
                                                             hosted gateway's environment (e.g. Vercel)

Existing files are kept unless --force is given: re-issuing the authority
invalidates every certificate signed by the old one.
"""
from __future__ import annotations

import argparse
import base64
import ipaddress
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

CERTS = Path(__file__).resolve().parents[1] / "certs"
VALID_DAYS = 825


def _name(common_name: str) -> x509.Name:
    return x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PEHCHAAN"),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])


def _write(path: Path, data: bytes, private: bool = False) -> None:
    path.write_bytes(data)
    if private:
        path.chmod(0o600)


def _key_pem(key) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def _issue(subject: str, ca_cert, ca_key, usage, sans: list[str] | None = None):
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(subject))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=VALID_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
    )
    if sans:
        names: list[x509.GeneralName] = []
        for host in sans:
            try:
                names.append(x509.IPAddress(ipaddress.ip_address(host)))
            except ValueError:
                names.append(x509.DNSName(host))
        builder = builder.add_extension(x509.SubjectAlternativeName(names), critical=False)
    return key, builder.sign(ca_key, hashes.SHA256())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", action="append", default=[], help="extra name or IP the engine is reached at (repeatable)")
    ap.add_argument("--force", action="store_true", help="replace existing certificates")
    ap.add_argument("--print-env", action="store_true", help="print base64 values for a hosted gateway's environment")
    args = ap.parse_args()

    CERTS.mkdir(exist_ok=True)
    wanted = ["ca.pem", "ca.key", "engine.pem", "engine.key", "gateway.pem", "gateway.key"]
    if all((CERTS / f).is_file() for f in wanted) and not args.force:
        print(f"Certificates already exist in {CERTS} (use --force to re-issue).")
    else:
        hosts = ["localhost", "127.0.0.1", "::1", *args.host]
        ca_key = ec.generate_private_key(ec.SECP256R1())
        now = datetime.now(timezone.utc)
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(_name("PEHCHAAN internal CA"))
            .issuer_name(_name("PEHCHAAN internal CA"))
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=VALID_DAYS * 2))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
            .sign(ca_key, hashes.SHA256())
        )
        engine_key, engine_cert = _issue("pehchaan-engine", ca_cert, ca_key, ExtendedKeyUsageOID.SERVER_AUTH, hosts)
        gateway_key, gateway_cert = _issue("pehchaan-gateway", ca_cert, ca_key, ExtendedKeyUsageOID.CLIENT_AUTH)

        pem = serialization.Encoding.PEM
        _write(CERTS / "ca.pem", ca_cert.public_bytes(pem))
        _write(CERTS / "ca.key", _key_pem(ca_key), private=True)
        _write(CERTS / "engine.pem", engine_cert.public_bytes(pem))
        _write(CERTS / "engine.key", _key_pem(engine_key), private=True)
        _write(CERTS / "gateway.pem", gateway_cert.public_bytes(pem))
        _write(CERTS / "gateway.key", _key_pem(gateway_key), private=True)
        print(f"Issued CA, engine and gateway certificates in {CERTS} (engine valid for: {', '.join(hosts)}).")

    if args.print_env:
        b64 = lambda name: base64.b64encode((CERTS / name).read_bytes()).decode()  # noqa: E731
        print("\n# Paste into the hosted gateway's environment. ENGINE_CLIENT_KEY is a secret.")
        print(f"ENGINE_CA_CERT={b64('ca.pem')}")
        print(f"ENGINE_CLIENT_CERT={b64('gateway.pem')}")
        print(f"ENGINE_CLIENT_KEY={b64('gateway.key')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
