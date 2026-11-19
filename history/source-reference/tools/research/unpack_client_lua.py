"""Verify and unpack Lua assets from the frozen owned CN 2.7.71 APK.

Analysis only: no game process, credentials, requests or client modifications.
The resulting official scripts stay in the ignored D-drive analysis cache.
Asset cipher/signature format reference:
https://github.com/djpadbit/Arknights-RE/blob/master/pyknights/converter.py
LZ4AK transform adapted from Ark-Unpacker Block.py (BSD-3-Clause).
The complete applicable notice is retained in tools/research/ARK_UNPACKER_LICENSE.txt.
"""

# LZ4AK adaptation: Copyright (c) 2022-2025, Harry Huang.
# Other analysis code independently implemented for TerraLocal.

import argparse
import hashlib
import json
import re
import zipfile
from contextlib import contextmanager
from pathlib import Path

from cryptography.hazmat.primitives import hashes, padding, serialization
from cryptography.hazmat.primitives.asymmetric import padding as rsa_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache/client-metadata"
APK_HASH = "0b79b85383e21a6343283bc6bfd7a9d24eb4134abf901115f757da6a5d50f6db"
LUA_MEMBER = "assets/AB/Android/anon/3ea52f7d41a320d200aa7e61735f0819.bin"
LUA_BUNDLE_HASH = "4711a08bc1aa519125bda5b64ea5760254fb03c0e412054f8f73f06e3c1dfa76"
MAX_BLOCK = 64 * 1024 * 1024
MAX_SCRIPT = 1024 * 1024
# Public static asset material, not SDK/game authentication credentials.
ASSET_MATERIAL = b"UITpAi82pHAWwnzqHRMCwPonJLIB3WCl"
ASSET_PUBLIC_KEY = b"""-----BEGIN PUBLIC KEY-----
MIGdMA0GCSqGSIb3DQEBAQUAA4GLADCBhwKBgQCvlvAc3e4BZc1vtc/45jTKMpDFcDsbYQUIRV9Y
jQToB4vaypDHbZvEWTktFZuoM5MMET/lo4H4fgtF5dN0ELHMhiod9NtANzsDXiJyALYdVdxgr6p2
AUM3DYtlrBj1rmVDMMzvbebaHbaCoPfhJ3/w+uIVZI85f6CIK0CKnZ38hQIBEQ==
-----END PUBLIC KEY-----
"""


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def local_container_paths(environment) -> list[str]:
    """List already loaded asset paths without resolving external preloads.

    Environment.container builds a global dependency index first. Reading the
    per-file catalogs preserves the names without loading unrelated files.
    """
    return sorted({name for asset in environment.assets for name in asset.container.keys()})


def decompress_lz4ak(data: bytes, expected: int) -> bytes:
    """Convert the custom token/offset layout, rejecting malformed lengths."""
    import lz4.block

    if type(expected) is not int or not 0 < expected <= MAX_BLOCK or not data:
        raise ValueError("Invalid bounded LZ4AK block")
    fixed = bytearray(data)
    cursor = produced = 0

    def length(base: int) -> int:
        nonlocal cursor
        if base != 15:
            return base
        while True:
            if cursor >= len(fixed):
                raise ValueError("Truncated extended LZ4AK length")
            value = fixed[cursor]
            cursor += 1
            base += value
            if base > expected:
                raise ValueError("LZ4AK length exceeds its declared output")
            if value != 255:
                return base

    while cursor < len(fixed):
        token = fixed[cursor]
        fixed[cursor] = ((token & 15) << 4) | (token >> 4)
        cursor += 1
        literal = length(token & 15)
        if cursor + literal > len(fixed) or produced + literal > expected:
            raise ValueError("Invalid LZ4AK literal extent")
        cursor += literal
        produced += literal
        if produced == expected:
            if cursor != len(fixed):
                raise ValueError("Unexpected bytes after LZ4AK output")
            break
        if cursor + 2 > len(fixed):
            raise ValueError("Truncated LZ4AK match offset")
        offset = int.from_bytes(fixed[cursor:cursor + 2], "big")
        if not 0 < offset <= produced:
            raise ValueError("Invalid LZ4AK backward match")
        fixed[cursor:cursor + 2] = offset.to_bytes(2, "little")
        cursor += 2
        produced += length(token >> 4) + 4
        if produced > expected:
            raise ValueError("LZ4AK match exceeds its declared output")
    if produced != expected:
        raise ValueError("Incomplete LZ4AK block")
    decoded = lz4.block.decompress(bytes(fixed), uncompressed_size=expected)
    if len(decoded) != expected:
        raise ValueError("LZ4AK output length differs")
    return decoded


@contextmanager
def custom_compression():
    from UnityPy.enums import CompressionFlags
    from UnityPy.helpers import CompressionHelper

    handlers = CompressionHelper.DECOMPRESSION_MAP
    original = handlers[CompressionFlags.LZHAM]
    handlers[CompressionFlags.LZHAM] = decompress_lz4ak
    try:
        yield
    finally:
        handlers[CompressionFlags.LZHAM] = original


def decode_signed_lua(body: bytes, public, material: bytes = ASSET_MATERIAL) -> bytes:
    if len(material) != 32 or not 160 <= len(body) <= MAX_SCRIPT or len(body) % 16:
        raise ValueError("Unsupported signed Lua asset extent")
    if public.key_size != 1024:
        raise ValueError("The frozen asset signature requires its 1024-bit public key")
    # MD5/RSA is the existing asset format, never used for local account security.
    public.verify(body[:128], body[128:], rsa_padding.PKCS1v15(), hashes.MD5())
    payload = body[128:]
    iv = bytes(left ^ right for left, right in zip(payload[:16], material[16:], strict=True))
    decryptor = Cipher(algorithms.AES(material[:16]), modes.CBC(iv)).decryptor()
    padded = decryptor.update(payload[16:]) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    plain = unpadder.update(padded) + unpadder.finalize()
    if len(plain) < 16 or plain[:16] != iv:
        raise ValueError("The decoded first block differs from the asset IV")
    plain.decode("utf-8")  # Lua source only; no bytecode is silently relabelled.
    return plain


def private_output(directory: Path) -> Path:
    directory = directory.resolve()
    if not directory.is_relative_to(CACHE.resolve()) or directory == CACHE.resolve():
        raise ValueError("Lua output must be a child of the private analysis cache")
    return directory


def extract(apk: Path, directory: Path) -> dict:
    import UnityPy

    directory = private_output(directory)
    if digest(apk) != APK_HASH:
        raise ValueError("APK fingerprint differs from frozen CN 2.7.71")
    public = serialization.load_pem_public_key(ASSET_PUBLIC_KEY)
    with zipfile.ZipFile(apk) as archive:
        members = [entry for entry in archive.infolist() if entry.filename == LUA_MEMBER]
        if len(members) != 1 or members[0].file_size > 16 * 1024 * 1024:
            raise ValueError("The frozen Lua bundle member differs")
        raw = archive.read(LUA_MEMBER)
    if hashlib.sha256(raw).hexdigest() != LUA_BUNDLE_HASH:
        raise ValueError("Lua bundle fingerprint differs")
    with custom_compression():
        environment = UnityPy.load(raw)
    scripts = []
    seen = set()
    for obj in environment.objects:
        if obj.type.name != "TextAsset":
            continue
        data = obj.read()
        name = data.m_Name
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\.lua", name, flags=re.IGNORECASE):
            raise ValueError("Unexpected Lua asset name")
        if name.casefold() in seen:
            raise ValueError("Lua names collide on Windows")
        seen.add(name.casefold())
        encoded = data.m_Script
        body = encoded.encode("utf-8", "surrogateescape") if isinstance(encoded, str) else bytes(encoded)
        plain = decode_signed_lua(body, public)
        path = directory / name
        if path.resolve().parent != directory:
            raise ValueError("Lua output escapes the selected private directory")
        if path.exists() and path.read_bytes() != plain:
            raise ValueError("Retain earlier Lua evidence; select a new output directory")
        scripts.append((path, plain, {"name": name, "path_id": obj.path_id,
                       "source_sha256": hashlib.sha256(body).hexdigest(),
                       "decoded_sha256": hashlib.sha256(plain).hexdigest(),
                       "decoded_size": len(plain), "signature_verified": True}))
    if len(scripts) != 339:
        raise ValueError("The frozen Lua asset count differs")
    # Verify all scripts and earlier evidence before writing any official source.
    directory.mkdir(parents=True, exist_ok=True)
    for path, plain, _record in scripts:
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(plain)
    report = {"apk_sha256": APK_HASH, "bundle_member": LUA_MEMBER,
              "bundle_sha256": LUA_BUNDLE_HASH, "scripts": [record for _, _, record in scripts],
              "containers": local_container_paths(environment),
              "scope": "signed static APK Lua source; runtime hotfix activation remains unverified"}
    receipt = directory / "receipt.json"
    receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"scripts": len(scripts), "decoded_bytes": sum(len(plain) for _, plain, _ in scripts),
            "receipt": str(receipt), "receipt_sha256": digest(receipt)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, default=ROOT / "data/client/base.apk")
    parser.add_argument("--output", type=Path, default=CACHE / "lua-apk")
    arguments = parser.parse_args()
    print(json.dumps(extract(arguments.apk, arguments.output), ensure_ascii=False))
