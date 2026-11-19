from __future__ import annotations

import ipaddress
import os
import ssl
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import dsa, ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


class CertificateError(ValueError):
    """Local TLS material needs attention before starting the service."""


def _server_names(settings) -> list[x509.GeneralName]:
    names = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
             x509.IPAddress(ipaddress.ip_address("10.0.2.2"))]
    host = urlsplit(settings.advertised_url).hostname
    try:
        names.append(x509.IPAddress(ipaddress.ip_address(host)))
    except ValueError:
        names.append(x509.DNSName(host))
    names.extend(x509.DNSName(name) for name in settings.tls_dns_names)
    return list(dict.fromkeys(names))


def _load_ca(ca_path: Path, key_path: Path, now: datetime):
    try:
        certificates = x509.load_pem_x509_certificates(ca_path.read_bytes())
        if len(certificates) != 1:
            raise ValueError("Expected one CA certificate")
        [ca] = certificates
        ca_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        if not isinstance(ca_key, (rsa.RSAPrivateKey, ec.EllipticCurvePrivateKey, dsa.DSAPrivateKey)):
            raise ValueError("Unsupported CA key type")
        if not ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            raise ValueError("Certificate is not a CA")
        usage = next((entry.value for entry in ca.extensions if isinstance(entry.value, x509.KeyUsage)), None)
        if usage is not None and not usage.key_cert_sign:
            raise ValueError("Certificate is not authorised to sign the server leaf")
        ca.verify_directly_issued_by(ca)
    except (OSError, ValueError, TypeError, x509.ExtensionNotFound, x509.DuplicateExtension,
            InvalidSignature, UnsupportedAlgorithm):
        raise CertificateError("无法验证本地 CA 证书或私钥，请核对原有证书备份。") from None
    if not ca.not_valid_before_utc <= now < ca.not_valid_after_utc:
        raise CertificateError("本地 CA 不在有效期内，请核对系统时间或原有证书。")
    key_format = (serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    if ca.public_key().public_bytes(*key_format) != ca_key.public_key().public_bytes(*key_format):
        raise CertificateError("本地 CA 证书与私钥不匹配，请使用配对的原文件。")
    return ca, ca_key


def _can_reuse_leaf(certificate: Path, key_path: Path, ca: x509.Certificate,
                    names: list[x509.GeneralName], now: datetime) -> bool:
    if not certificate.is_file() or not key_path.is_file():
        return False
    try:
        leaf, *chain = x509.load_pem_x509_certificates(certificate.read_bytes())
        leaf.verify_directly_issued_by(ca)
        if chain and (len(chain) != 1 or chain[0].fingerprint(hashes.SHA256()) != ca.fingerprint(hashes.SHA256())):
            return False
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(certificate), str(key_path), password="")
        leaf_names = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        usages = leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        is_ca = leaf.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    except (OSError, ValueError, x509.ExtensionNotFound, x509.DuplicateExtension, InvalidSignature, UnsupportedAlgorithm):
        return False
    renewal = min(now + timedelta(days=30), ca.not_valid_after_utc)
    return (not is_ca and ExtendedKeyUsageOID.SERVER_AUTH in usages and set(names).issubset(set(leaf_names))
            and leaf.not_valid_before_utc <= now < leaf.not_valid_after_utc
            and renewal <= leaf.not_valid_after_utc <= ca.not_valid_after_utc
            and leaf.not_valid_after_utc - leaf.not_valid_before_utc <= timedelta(days=398))


def _inspect(settings, now: datetime):
    directory = settings.data_dir / "certs"
    certificate, key_path = directory / "server.pem", directory / "server.key"
    ca_path, ca_key_path = directory / "ca.pem", directory / "ca.key"
    if (directory.exists() or directory.is_symlink()) and not directory.is_dir():
        raise CertificateError("证书路径需要是目录。")
    for path in (certificate, key_path, ca_path, ca_key_path):
        if (path.exists() or path.is_symlink()) and not path.is_file():
            raise CertificateError(f"证书路径 {path.name} 需要是普通文件。")
    names = _server_names(settings)
    if not any(path.is_file() for path in (certificate, key_path, ca_path, ca_key_path)):
        return "will_create", names, None
    if not ca_path.is_file() or not ca_key_path.is_file():
        raise CertificateError("本地 CA 文件不完整，请从备份找回 ca.pem 和 ca.key。")
    ca, ca_key = _load_ca(ca_path, ca_key_path, now)
    status = "ready" if _can_reuse_leaf(certificate, key_path, ca, names, now) else "will_renew"
    return status, names, (ca, ca_key)


def certificate_status(settings) -> str:
    if not settings.tls:
        return "disabled"
    status, _, _ = _inspect(settings, datetime.now(UTC))
    return status


def _write_certificate_file(path: Path, content: bytes) -> None:
    stream = tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}-", delete=False)
    temporary = Path(stream.name)
    try:
        with stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_certificate(settings) -> tuple[str, str]:
    directory = settings.data_dir / "certs"
    certificate, key_path = directory / "server.pem", directory / "server.key"
    now = datetime.now(UTC)
    status, names, pair = _inspect(settings, now)
    if status == "ready":
        return str(certificate), str(key_path)
    directory.mkdir(parents=True, exist_ok=True)
    if pair is None:
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ca_subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TerraLocal Local CA")])
        ca = (x509.CertificateBuilder().subject_name(ca_subject).issuer_name(ca_subject)
              .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=3650))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                                          key_encipherment=False, data_encipherment=False, key_agreement=False,
                                          key_cert_sign=True, crl_sign=True, encipher_only=None, decipher_only=None),
                             critical=True)
              .sign(ca_key, hashes.SHA256()))
        _write_certificate_file(directory / "ca.key", ca_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        _write_certificate_file(directory / "ca.pem", ca.public_bytes(serialization.Encoding.PEM))
    else:
        ca, ca_key = pair
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TerraLocal")])
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(ca.subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(max(now - timedelta(minutes=5), ca.not_valid_before_utc))
            .not_valid_after(min(now + timedelta(days=90), ca.not_valid_after_utc))
            .add_extension(x509.SubjectAlternativeName(names), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    _write_certificate_file(key_path, key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    _write_certificate_file(certificate, cert.public_bytes(serialization.Encoding.PEM) + ca.public_bytes(
        serialization.Encoding.PEM))
    return str(certificate), str(key_path)
