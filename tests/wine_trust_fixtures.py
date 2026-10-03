#!/usr/bin/env python3
"""Generate disposable certs with the exact EveJS name-constraint structure.

Dependency: python3-cryptography. These contain test-only random keys; neither
the user's server certificates nor prefix are read or modified.
"""
from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import json
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


# Keep aligned with vendor EveJS localTlsCertificate.js. The CA excludes the
# dotted subtrees to permit only exact intercepted DNS names, and excludes the
# empty directoryName subtree to reject every nonempty subject distinguished name.
LOCAL_NAMES = (
    "app.launchdarkly.com", "clientstream.launchdarkly.com",
    "clientsdk.launchdarkly.com", "dev-public-gateway.evetech.net",
    "events.launchdarkly.com", "mobile.launchdarkly.com",
    "public-gateway.evetech.net", "sdk.launchdarkly.com", "sentry.io",
    "stream.launchdarkly.com", "localhost",
)


def generate(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    root_name = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "EvEJS Local"),
        x509.NameAttribute(NameOID.COMMON_NAME, "EvEJS Local Development CA"),
    ])
    constraints = x509.NameConstraints(
        permitted_subtrees=[*(x509.DNSName(name) for name in LOCAL_NAMES),
                            x509.IPAddress(ipaddress.ip_network("127.0.0.1/32"))],
        excluded_subtrees=[*(x509.DNSName("." + name) for name in LOCAL_NAMES),
                           x509.DirectoryName(x509.Name([]))],
    )

    def authority(authority_key, name, constrain=True):
        builder = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                   .public_key(authority_key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - dt.timedelta(days=1))
                   .not_valid_after(now + dt.timedelta(days=7300))
                   .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                   .add_extension(x509.KeyUsage(True, False, False, False, False,
                                                True, True, False, False), critical=True)
                   .add_extension(x509.SubjectKeyIdentifier.from_public_key(authority_key.public_key()),
                                  critical=False))
        if constrain:
            builder = builder.add_extension(constraints, critical=True)
        return builder.sign(authority_key, hashes.SHA256())

    root = authority(key, root_name)
    root_der = root.public_bytes(serialization.Encoding.DER)
    (destination / "root.der").write_bytes(root_der)
    (destination / "root.pem").write_bytes(root.public_bytes(serialization.Encoding.PEM))

    def leaf(*, subject=x509.Name([]), names=("localhost",), ip=None,
             authority_key=key, issuer=root_name, expired=False, server_auth=True):
        leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        builder = (x509.CertificateBuilder().subject_name(subject).issuer_name(issuer)
                   .public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - dt.timedelta(days=2 if expired else 1))
                   .not_valid_after(now - dt.timedelta(days=1) if expired else now + dt.timedelta(days=3650))
                   .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                   .add_extension(x509.KeyUsage(True, False, True, False, False,
                                                False, False, False, False), critical=True)
                   .add_extension(x509.ExtendedKeyUsage([
                       ExtendedKeyUsageOID.SERVER_AUTH if server_auth else ExtendedKeyUsageOID.CLIENT_AUTH]),
                       critical=True)
                   .add_extension(x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()),
                                  critical=False))
        sans = [x509.DNSName(name) for name in names]
        if ip:
            sans.append(x509.IPAddress(ipaddress.ip_address(ip)))
        if sans:
            builder = builder.add_extension(x509.SubjectAlternativeName(sans), critical=True)
        return builder.sign(authority_key, hashes.SHA256()).public_bytes(serialization.Encoding.DER)

    nonempty = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    foreign_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    foreign_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Untrusted test CA")])
    foreign = authority(foreign_key, foreign_name, False)
    (destination / "foreign-root.der").write_bytes(foreign.public_bytes(serialization.Encoding.DER))
    original = leaf()
    # The last byte belongs to the RSA signature BIT STRING, not the certificate
    # structure; flipping it yields a parseable cert with an invalid signature.
    tampered = original[:-1] + bytes([original[-1] ^ 1])
    cases = [
        ("empty-subject-localhost", original, "localhost", True, 0),
        ("empty-subject-with-ip-san", leaf(ip="127.0.0.1"), "localhost", True, 0),
        ("empty-subject-allowed-gateway", leaf(names=("public-gateway.evetech.net",)),
         "public-gateway.evetech.net", True, 0),
        ("nonempty-subject-with-valid-san", leaf(subject=nonempty), "localhost", False, 0x8000),
        ("cn-only-subject", leaf(subject=nonempty, names=()), "localhost", False, 0x8000),
        ("additional-external-san", leaf(names=("localhost", "example.org")), "localhost", False, 0x4000),
        ("excluded-dns-subdomain", leaf(names=("child.localhost",)), "child.localhost", False, 0x8000),
        ("disallowed-ip-san", leaf(ip="127.0.0.2"), "localhost", False, 0x4000),
        ("wrong-hostname", leaf(), "example.org", False, 0),
        ("expired-leaf", leaf(expired=True), "localhost", False, 0x1),
        ("tampered-leaf-signature", tampered, "localhost", False, 0x8),
        ("wrong-server-auth-usage", leaf(server_auth=False), "localhost", False, 0x10),
        ("untrusted-issuer", leaf(authority_key=foreign_key, issuer=foreign_name),
         "localhost", False, 0x10000),
    ]
    manifest = []
    for name, der, hostname, expected, required_bits in cases:
        filename = name + ".der"
        (destination / filename).write_bytes(der)
        manifest.append({"name": name, "leaf": filename, "hostname": hostname,
                         "expected_pass": expected, "required_chain_bits": required_bits})
    (destination / "cases.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Generated {len(cases)} private Wine trust cases in {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    generate(parser.parse_args().destination)
