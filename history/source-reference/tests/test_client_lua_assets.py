from types import SimpleNamespace

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.asymmetric import padding as rsa_padding
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from tools.research.unpack_client_lua import (
    decode_signed_lua,
    decompress_lz4ak,
    local_container_paths,
    private_output,
)


def test_asset_catalog_does_not_resolve_external_preload(monkeypatch, tmp_path):
    from UnityPy import Environment
    from UnityPy.classes import PPtr
    from UnityPy.files.SerializedFile import SerializedFile
    from UnityPy.helpers.ContainerHelper import ContainerHelper

    pointer = PPtr(m_FileID=1, m_PathID=42)
    entry = SimpleNamespace(asset=pointer, preloadIndex=0, preloadSize=1)
    asset = object.__new__(SerializedFile)
    asset.is_dependency = False
    asset._container = ContainerHelper(SimpleNamespace(
        m_PreloadTable=[pointer], m_Container=[("synthetic/source.lua", entry)]))
    env = Environment(path=str(tmp_path))
    env.files = {"synthetic": asset}
    env.cabs = {"synthetic": asset}

    def forbid_dependency(*args, **kwargs):
        raise AssertionError("External dependency resolution must not occur")

    monkeypatch.setattr(PPtr, "deref", forbid_dependency)
    assert local_container_paths(env) == ["synthetic/source.lua"]
    # Demonstrate that the earlier API would hit the guarded external preload.
    with pytest.raises(AssertionError, match="External dependency"):
        _ = env.container


def test_local_catalog_merges_duplicate_paths_and_ignores_dependency_assets(tmp_path):
    from UnityPy import Environment
    from UnityPy.classes import PPtr
    from UnityPy.files.SerializedFile import SerializedFile
    from UnityPy.helpers.ContainerHelper import ContainerHelper

    env = Environment(path=str(tmp_path))
    for index, (names, dependency) in enumerate((
            (("z.lua", "a.lua"), False), (("a.lua", "b.lua"), False),
            (("external.lua",), True))):
        asset = object.__new__(SerializedFile)
        asset.is_dependency = dependency
        asset._container = ContainerHelper([
            (name, SimpleNamespace(asset=PPtr(m_FileID=0, m_PathID=i+1)))
            for i, name in enumerate(names)])
        env.files[str(index)] = asset
    assert local_container_paths(env) == ["a.lua", "b.lua", "z.lua"]


def test_custom_lz4_literals_extension_and_big_endian_match():
    assert decompress_lz4ak(b"\x05HELLO", 5) == b"HELLO"
    assert decompress_lz4ak(b"\x0f\x05" + b"a" * 20, 20) == b"a" * 20
    assert decompress_lz4ak(b"\x34ABCD\x00\x04\x05HIJKL", 16) == b"ABCDABCDABCHIJKL"


def test_custom_lz4_rejects_truncation_extent_and_invalid_match():
    for compressed, size in ((b"\x0f", 20), (b"\x05HELL", 5), (b"\x05HELLO!", 5),
                             (b"\x34ABCD\x00", 16), (b"\x34ABCD\x00\x05", 16),
                             (b"\x34ABCD\x00\x00", 16), (b"\x05HELLO", 4),
                             (b"\x05HELLO", True), (b"\x05HELLO", 2**30)):
        with pytest.raises(ValueError):
            decompress_lz4ak(compressed, size)


def test_signed_asset_verification_precedes_decode_and_rejects_tampering():
    material = b"0123456789ABCDEFfedcba9876543210"
    plain = b"-- synthetic fixture\nreturn { finished = false }\n"
    iv = plain[:16]
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plain) + padder.finalize()
    encoder = Cipher(algorithms.AES(material[:16]), modes.CBC(iv)).encryptor()
    encrypted = encoder.update(padded) + encoder.finalize()
    payload = bytes(a ^ b for a, b in zip(iv, material[16:], strict=True)) + encrypted
    signer = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    signature = signer.sign(payload, rsa_padding.PKCS1v15(), hashes.MD5())
    body = signature + payload
    assert decode_signed_lua(body, signer.public_key(), material) == plain
    modified = body[:-1] + bytes([body[-1] ^ 1])
    with pytest.raises(InvalidSignature):
        decode_signed_lua(modified, signer.public_key(), material)
    with pytest.raises(ValueError):
        decode_signed_lua(body[:-1], signer.public_key(), material)
    with pytest.raises(ValueError):
        decode_signed_lua(body, signer.public_key(), material[:16])
    with pytest.raises(ValueError):
        decode_signed_lua(body, signer.public_key(), material[::-1])


def test_official_sources_cannot_be_exported_into_release_or_project_code():
    from tools.research.unpack_client_lua import CACHE, ROOT

    for directory in (ROOT / "dist", ROOT / "terralocal", CACHE):
        with pytest.raises(ValueError):
            private_output(directory)
