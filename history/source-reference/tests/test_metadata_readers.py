"""All reader entry points use verified page decoding, never whole-row guesses."""
import hashlib
import struct
from types import SimpleNamespace

import pytest

from tools.research import client_metadata_pages as pages
from tools.research import index_client, inspect_client_metadata, inspect_client_native_types


@pytest.fixture
def synthetic_metadata(tmp_path, monkeypatch):
    plain = bytearray(8192)
    header = [0] * 64
    strings = b"\0CrossPage\0A.Namespace\0DecodedField\0DecodedMethod\0" + b"n" * 300 + b"\0"
    header[6:8] = [256, len(strings)]
    plain[256:256 + len(strings)] = strings
    header[12:14] = [1024, 32]
    method = (strings.index(b"DecodedMethod"), 0, 8, 0, -1, 0x06000001, 0, 0, 0, 0)
    struct.pack_into("<5iI4H", plain, 1024, *method)
    header[24:26] = [1200, 12]
    struct.pack_into("<3I", plain, 1200, strings.index(b"DecodedField"), 8, 0x04000001)
    header[16:18] = [2100, 12]
    struct.pack_into("<3i", plain, 2100, 0, 8, 0)
    header[18:20] = [2200, 4]
    struct.pack_into("<I", plain, 2200, 2)
    header[40:42] = [4028, 88]
    row = [0] * 26
    row[0], row[1], row[3], row[16], row[18], row[24], row[25] = 1, strings.index(b"A.Namespace"), 0xFFFFFFFF, 1, 1, 2, 0x02000001
    struct.pack_into("<16I8H2I", plain, 4028, *row)
    header[42:44] = [4200, 40]
    struct.pack_into("<I", plain, 4228, 1)
    body = bytearray(plain[:4096]) + bytearray(value ^ 0x66 for value in plain[4096:])
    body[:256] = bytes(value ^ 0x66 for value in struct.pack("<64I", *header))
    body = bytes(body)
    path = tmp_path / "synthetic-metadata.dat"
    path.write_bytes(body)
    monkeypatch.setattr(pages, "METADATA_HASH", hashlib.sha256(body).hexdigest())
    return path, strings, tuple(header)


def test_direct_inspector_decodes_class_field_and_method_from_one_view(synthetic_metadata):
    path, _, _ = synthetic_metadata
    report = inspect_client_metadata.inspect(path, ["CrossPage"], methods=True)
    definition, = report["types"]
    assert definition["name"] == "CrossPage" and definition["namespace"] == "A.Namespace"
    assert definition["fields"][0]["name"] == "DecodedField"
    assert definition["methods"][0]["name"] == "DecodedMethod"
    assert definition["fields"][0]["enum_default_raw_compressed_int32"] == 1
    assert definition["fields"][0]["enum_default_protection_verified"] is False
    assert report["default_value_payloads_verified"] is False


def test_name_query_returns_duplicates_at_distinct_string_indices(synthetic_metadata, monkeypatch):
    path, strings, old_header = synthetic_metadata
    header, body = list(old_header), bytearray(path.read_bytes())
    extra = b"CrossPage\0B.Namespace\0"
    position = header[6] + len(strings)
    body[position:position + len(extra)] = extra
    header[7] += len(extra)
    header[41] = 176
    row = [0] * 26
    row[0], row[1], row[3], row[25] = len(strings), len(strings) + 10, 0xFFFFFFFF, 0x02000002
    second = struct.pack("<16I8H2I", *row)
    body[header[40] + 88:header[40] + 176] = bytes(value ^ 0x66 for value in second)
    header[42:44] = [4320, 40]
    image = bytearray(40)
    struct.pack_into("<I", image, 28, 1)
    body[4320:4360] = bytes(value ^ 0x66 for value in image)
    body[:256] = bytes(value ^ 0x66 for value in struct.pack("<64I", *header))
    path.write_bytes(body)
    monkeypatch.setattr(pages, "METADATA_HASH", hashlib.sha256(body).hexdigest())
    report = inspect_client_metadata.inspect(path, ["CrossPage"])
    assert [(row["name"], row["namespace"]) for row in report["types"]] == [
        ("CrossPage", "A.Namespace"), ("CrossPage", "B.Namespace")]


def test_native_constructor_loads_the_shared_view_once_and_long_names_are_plain(synthetic_metadata, tmp_path, monkeypatch):
    path, strings, _ = synthetic_metadata
    elf = struct.pack("<16sHHIQQQIHHHHHH", b"\x7fELF\x02\x01" + bytes(10),
                      0, 183, 1, 0, 0, 0, 0, 64, 56, 0, 0, 0, 0)
    elf_path = tmp_path / "synthetic.so"
    elf_path.write_bytes(elf)
    monkeypatch.setattr(inspect_client_native_types, "ELF_HASH", hashlib.sha256(elf).hexdigest())

    def registration(_self, address, fmt):
        assert address == 0xBE31388 and fmt == "<16Q"
        row = [0] * 16
        row[6], row[10], row[12] = 120692, 49382, 49382
        return tuple(row)

    monkeypatch.setattr(inspect_client_native_types.NativeTypes, "read", registration)
    original, calls = inspect_client_native_types.frozen_view, []

    def shared(body):
        calls.append(True)
        return original(body)

    monkeypatch.setattr(inspect_client_native_types, "frozen_view", shared)
    native = inspect_client_native_types.NativeTypes(elf_path, path)
    assert len(calls) == 1
    assert native.class_name(0) == "A.Namespace.CrossPage"
    assert native.string(strings.index(b"n" * 300)) == "n" * 300
    assert native.metadata_pages["page_counts"] == {0: 1, 0x66: 1}


def test_indexer_reuses_native_view_instead_of_decoding_it_again(tmp_path, monkeypatch):
    report = {"derived_sha256": "synthetic", "page_counts": {0: 1, 0x66: 1}}
    native = SimpleNamespace(meta=b"already decoded", header=tuple([0] * 64), metadata_pages=report)
    monkeypatch.setattr(index_client, "NativeTypes", lambda *_args: native)
    monkeypatch.setattr(index_client, "CACHE", tmp_path)
    monkeypatch.setattr(index_client, "ROOT", tmp_path)
    indexer = index_client.Indexer()
    assert indexer.native is native and indexer.metadata_pages is report
    assert indexer.native.meta == b"already decoded"


@pytest.mark.parametrize("index", [-1, 1, True, "0"])
def test_selected_type_indices_are_strict_and_bounded(synthetic_metadata, index):
    path, _, _ = synthetic_metadata
    with pytest.raises(ValueError, match="index is out of bounds"):
        inspect_client_metadata.inspect(path, [], (index,))


def test_unknown_input_hash_is_rejected_before_layout_interpretation():
    with pytest.raises(ValueError, match="fingerprint differs"):
        pages.frozen_view(bytes(256))


def test_unknown_raw_enum_payload_does_not_invent_a_value_or_hide_declarations(synthetic_metadata, monkeypatch):
    path, _, header = synthetic_metadata
    body = bytearray(path.read_bytes())
    body[header[18]] = 0xF1
    path.write_bytes(body)
    monkeypatch.setattr(pages, "METADATA_HASH", hashlib.sha256(body).hexdigest())
    report = inspect_client_metadata.inspect(path, [], (0,), methods=True)
    field = report["types"][0]["fields"][0]
    assert field["name"] == "DecodedField" and field["enum_default_protection_verified"] is False
    assert "enum_default_raw_compressed_int32" not in field
    assert "Unsupported" in field["enum_default_raw_decode_error"]
