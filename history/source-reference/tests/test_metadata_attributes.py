"""Attribute interpretation needs token/constructor evidence, not a version guess."""

import hashlib
import struct
from types import SimpleNamespace

import pytest

from tools.research import inspect_client_attributes as reader

CTOR = 12345
CONVERTER = "Newtonsoft.Json.JsonConverterAttribute"


def artifact(*, left=0, right=0x66, table_key=0, payload=bytes((1, 0, 0, 0xFF, 26)), ctor=CTOR):
    body = bytes((1,)) + struct.pack("<I", ctor) + payload
    plain = bytearray(16384)
    data = 4094  # Count/constructor straddle two differently protected pages.
    plain[data:data + len(body)] = body
    ranges = 12288
    struct.pack_into("<4I", plain, ranges, 0x04000001, 0, 0x20000000, len(body))
    keys = (left, right, 0, table_key)
    raw = bytes(value ^ keys[at // 4096] for at, value in enumerate(plain))
    return bytes(plain), raw, {"range_start": ranges, "range_size": 16, "data_start": data,
                             "data_size": len(body)}


def lookup(index):
    if index != CTOR:
        raise ValueError("Not an instance constructor")
    return CONVERTER


@pytest.mark.parametrize("left,right", [(0, 0x66), (0x66, 0), (0, 0), (0x66, 0x66)])
@pytest.mark.parametrize("table_key", [0, 0x66])
def test_constructor_prefix_can_cross_protection_pages(left, right, table_key):
    _, raw, sections = artifact(left=left, right=right, table_key=table_key)
    table = reader.AttributeData(raw, **sections)
    assert table.entries(0, 1) == {0x04000001: 0}
    attrs, payload = table.constructors(0, lookup)
    assert attrs == [{"constructor": CTOR, "type": CONVERTER, "arguments_verified": False}]
    assert reader.type_argument(payload) == 13
    assert table.constructors(0, lookup) == (attrs, payload)


@pytest.mark.parametrize("padding", [0, 1, 2, 3])
def test_section_alignment_is_not_treated_as_another_attribute(padding):
    _, raw, sections = artifact()
    sections["data_size"] += padding
    table = reader.AttributeData(raw, **sections)
    assert table.padding == padding and len(table.rows) == 2
    assert table.constructors(0, lookup)[0][0]["constructor"] == CTOR


@pytest.mark.parametrize("change", ["stride", "alignment", "overlap", "end", "terminal", "order", "prefix"])
def test_wrong_legacy_layout_or_bad_boundaries_rejected(change):
    _, raw, sections = artifact(left=0, right=0, table_key=0)
    raw = bytearray(raw)
    start = sections["range_start"]
    if change == "stride":
        sections["range_size"] = 12
    elif change == "alignment":
        sections["range_start"] += 4
    elif change == "overlap":
        sections["data_start"] = start
    elif change == "end":
        sections["data_size"] += 4
    elif change == "terminal":
        struct.pack_into("<I", raw, start + 8, 0x20000001)
    elif change == "order":
        struct.pack_into("<I", raw, start + 12, 0)
    else:
        struct.pack_into("<I", raw, start, 0x99000001)
    with pytest.raises(ValueError):
        reader.AttributeData(bytes(raw), **sections)


def test_range_page_markers_must_not_disagree():
    _, raw, sections = artifact(left=0, right=0, table_key=0)
    raw = bytearray(raw)
    start = sections["range_start"] + 8
    raw[start:start + 8] = bytes(v ^ 0x66 for v in raw[start:start + 8])
    with pytest.raises(ValueError, match="disagree"):
        reader.AttributeData(bytes(raw), **sections)


@pytest.mark.parametrize("index", [-1, 1, True])
def test_attribute_entry_never_reads_terminal_or_noninteger(index):
    _, raw, sections = artifact()
    with pytest.raises(ValueError, match="outside"):
        reader.AttributeData(raw, **sections).constructors(index, lookup)


def test_unknown_constructor_or_unsupported_count_is_not_a_guessed_attribute():
    _, raw, sections = artifact(ctor=54321)
    with pytest.raises(ValueError, match="constructor evidence"):
        reader.AttributeData(raw, **sections).constructors(0, lookup)


@pytest.mark.parametrize("data,expected,end", [
    (b"\x7f", 127, 1), (b"\x81\x23", 0x123, 2), (b"\xc0\x02\x3c\x30", 146480, 4),
    (b"\xf0\x78\x56\x34\x12", 0x12345678, 5), (b"\xfe", 0xFFFFFFFE, 1),
    (b"\xff", 0xFFFFFFFF, 1),
])
def test_compressed_constructor_type_integer(data, expected, end):
    assert reader.compressed_uint(data) == (expected, end)


@pytest.mark.parametrize("data", [b"", b"\x81", b"\xc0\x02", b"\xf0\x01", b"\xe1"])
def test_truncated_or_unknown_integer_is_rejected(data):
    with pytest.raises(ValueError):
        reader.compressed_uint(data)


def test_only_exact_type_argument_shape_is_interpreted():
    assert reader.type_argument(bytes((1, 0, 0, 0xFF, 0xC0, 2, 0x3C, 0x30))) == 73240
    assert reader.type_argument(bytes((1, 0, 0, 0xFF, 1))) == -1
    assert reader.type_argument(bytes((1, 0, 0, 0xFF, 0xFF))) == -2147483648
    assert reader.type_argument(bytes((1, 0, 0, 0xFF, 26, 0))) is None
    assert reader.type_argument(bytes((1, 1, 0, 0xFF, 26))) is None


@pytest.mark.parametrize("empty_start", [0, 0xFFFFFFFF])
def test_selected_field_converter_is_bound_through_its_own_image(tmp_path, monkeypatch, empty_start):
    plain, _, sections = artifact(ctor=1)
    plain = bytearray(plain)
    header = [0] * 64
    header[12:14], header[24:26], header[40:42] = [800, 64], [1100, 12], [1200, 176]
    header[42:44], header[50:52], header[52:54] = [700, 40], [4094, 10], [12288, 16]
    struct.pack_into("<10I", plain, 700, 1, 0, 0, 2, 0, 0, 0, 1, 0, 1)
    struct.pack_into("<5iI4H", plain, 832, 2, 1, 0, 0, -1, 0x06000002, 0, 0, 0, 1)
    struct.pack_into("<3I", plain, 1100, 3, 0, 0x04000001)
    row = [0] * 26
    row[18], row[25] = 1, 0x02000001
    struct.pack_into("<16I8H2I", plain, 1200, *row)
    row[8], row[18], row[25] = empty_start, 0, 0x02000002
    struct.pack_into("<16I8H2I", plain, 1288, *row)
    path = tmp_path / "owned-synthetic.dat"
    path.write_bytes(plain)
    native = SimpleNamespace(meta=bytes(plain), header=header, type_count=120692,
                             class_name=lambda i: ("Example.Stats", CONVERTER)[i],
                             string=lambda i: {1: "Example.dll", 2: ".ctor", 3: "counterType"}[i],
                             index_name=lambda i: "Example.StringEnumConverter" if i == 13 else "invalid")
    monkeypatch.setattr(reader, "NativeTypes", lambda *args: native)
    monkeypatch.setattr(reader, "METADATA_HASH", hashlib.sha256(plain).hexdigest())
    result = reader.inspect(tmp_path / "not-executed.so", path, (0, 0))
    assert len(result["types"]) == 1 and result["range_count"] == 2
    attrs = result["types"][0]["fields"][0]["attributes"]
    assert attrs == [{"constructor": 1, "type": CONVERTER, "arguments_verified": True,
                      "converter_type_index": 13, "converter_type": "Example.StringEnumConverter"}]
    assert result["types"][0]["attributes"] == []
    assert result["runtime_values_or_official_credentials_read"] is False
    assert reader.inspect(tmp_path / "not-executed.so", path, (1,))["types"][0]["fields"] == []
    path.write_bytes(bytes(len(plain)))
    with pytest.raises(ValueError, match="fingerprint"):
        reader.inspect(tmp_path / "not-executed.so", path, (0,))
