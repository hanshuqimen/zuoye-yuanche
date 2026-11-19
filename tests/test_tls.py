import ssl
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID

from terralocal.config import Settings
from terralocal.server.services.tls import CertificateError, certificate_status, ensure_certificate


def test_local_chain_reuses_ca_and_refreshes_server_names(tmp_path):
    settings = Settings(data_dir=tmp_path)
    certificate, key = ensure_certificate(settings)
    ca_path = tmp_path / "certs" / "ca.pem"
    original_ca = ca_path.read_bytes()
    original_leaf = open(certificate, "rb").read()
    assert ensure_certificate(settings) == (certificate, key)
    assert open(certificate, "rb").read() == original_leaf
    settings.tls_dns_names = ["ak-conf.hypergryph.com"]
    ensure_certificate(settings)
    assert ca_path.read_bytes() == original_ca
    leaf = x509.load_pem_x509_certificate(open(certificate, "rb").read())
    assert not leaf.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    assert "ak-conf.hypergryph.com" in leaf.extensions.get_extension_for_class(
        x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
    assert ExtendedKeyUsageOID.SERVER_AUTH in leaf.extensions.get_extension_for_class(
        x509.ExtendedKeyUsage).value
    assert leaf.not_valid_after_utc - leaf.not_valid_before_utc <= timedelta(days=398)


def test_overlong_existing_leaf_is_renewed_without_changing_android_trust(tmp_path):
    settings = Settings(data_dir=tmp_path)
    certificate, key_path = ensure_certificate(settings)
    original = x509.load_pem_x509_certificate(open(certificate, "rb").read())
    ca_path = tmp_path / "certs/ca.pem"
    ca_bytes = ca_path.read_bytes()
    ca = x509.load_pem_x509_certificate(ca_bytes)
    ca_key = serialization.load_pem_private_key((tmp_path / "certs/ca.key").read_bytes(), None)
    key = serialization.load_pem_private_key(open(key_path, "rb").read(), None)
    now = datetime.now(UTC)
    overlong = (x509.CertificateBuilder().subject_name(original.subject).issuer_name(ca.subject)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=825))
                .add_extension(original.extensions.get_extension_for_class(x509.SubjectAlternativeName).value, False)
                .sign(ca_key, hashes.SHA256()))
    with open(certificate, "wb") as stream:
        stream.write(overlong.public_bytes(serialization.Encoding.PEM) + ca_bytes)
    ensure_certificate(settings)
    renewed = x509.load_pem_x509_certificate(open(certificate, "rb").read())
    assert renewed.serial_number != overlong.serial_number
    assert renewed.not_valid_after_utc - renewed.not_valid_before_utc <= timedelta(days=398)
    assert ca_path.read_bytes() == ca_bytes


def _private_pem(key):
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


@pytest.mark.parametrize("failure", ["wrong-key", "broken-certificate", "missing-key", "other-issuer"])
def test_invalid_server_material_is_renewed_with_the_same_local_ca(tmp_path, failure):
    settings = Settings(data_dir=tmp_path)
    certificate, key = map(Path, ensure_certificate(settings))
    ca_path, ca_key_path = tmp_path / "certs/ca.pem", tmp_path / "certs/ca.key"
    authority = ca_path.read_bytes(), ca_key_path.read_bytes()
    if failure == "wrong-key":
        key.write_bytes(_private_pem(rsa.generate_private_key(public_exponent=65537, key_size=2048)))
    elif failure == "broken-certificate":
        certificate.write_bytes(b"invalid synthetic certificate")
    elif failure == "other-issuer":
        other_certificate, other_key = map(Path, ensure_certificate(Settings(data_dir=tmp_path / "other")))
        certificate.write_bytes(other_certificate.read_bytes())
        key.write_bytes(other_key.read_bytes())
    else:
        key.unlink()
    assert certificate_status(settings) == "will_renew"
    ensure_certificate(settings)
    ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(certificate, key)
    x509.load_pem_x509_certificate(certificate.read_bytes()).verify_directly_issued_by(
        x509.load_pem_x509_certificate(authority[0]))
    assert certificate_status(settings) == "ready"
    assert (ca_path.read_bytes(), ca_key_path.read_bytes()) == authority


@pytest.mark.parametrize("failure", ["missing-key", "wrong-key", "broken-authority"])
def test_invalid_authority_remains_available_for_manual_recovery(tmp_path, failure):
    settings = Settings(data_dir=tmp_path)
    ensure_certificate(settings)
    files = tmp_path / "certs"
    if failure == "missing-key":
        (files / "ca.key").unlink()
    elif failure == "wrong-key":
        (files / "ca.key").write_bytes(_private_pem(rsa.generate_private_key(public_exponent=65537, key_size=2048)))
    else:
        (files / "ca.pem").write_bytes(b"invalid synthetic CA")
    before = {path.name: path.read_bytes() for path in files.iterdir()}
    for check in (certificate_status, ensure_certificate):
        with pytest.raises(CertificateError, match="本地 CA"):
            check(settings)
        assert {path.name: path.read_bytes() for path in files.iterdir()} == before


@pytest.mark.parametrize("remaining", [timedelta(days=3), timedelta(days=-1)])
def test_leaf_lifetime_respects_local_authority_expiry(tmp_path, remaining):
    settings = Settings(data_dir=tmp_path)
    certificate, _ = ensure_certificate(settings)
    ca_path = tmp_path / "certs/ca.pem"
    ca_key = serialization.load_pem_private_key((tmp_path / "certs/ca.key").read_bytes(), None)
    previous = x509.load_pem_x509_certificate(ca_path.read_bytes())
    now = datetime.now(UTC)
    ca = (x509.CertificateBuilder().subject_name(previous.subject).issuer_name(previous.subject)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - timedelta(days=7)).not_valid_after(now + remaining)
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .sign(ca_key, hashes.SHA256()))
    ca_bytes = ca.public_bytes(serialization.Encoding.PEM)
    ca_path.write_bytes(ca_bytes)
    if remaining.days < 0:
        with pytest.raises(CertificateError, match="CA 不在有效期内"):
            ensure_certificate(settings)
    else:
        ensure_certificate(settings)
        before = Path(certificate).read_bytes()
        assert x509.load_pem_x509_certificate(before).not_valid_after_utc == ca.not_valid_after_utc
        assert certificate_status(settings) == "ready"
        ensure_certificate(settings)
        assert Path(certificate).read_bytes() == before
    assert ca_path.read_bytes() == ca_bytes
