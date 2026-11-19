"""Authored tiny ARM64 containers; no official executable or code fixture."""

import struct

import pytest

from tools.research.native_analysis_context import UnknownCall, add_unknown_call_context


def fragment():
    header = struct.pack("<16sHHIQQQIHHHHHH", b"\x7fELF\x02\x01\x01"+b"\0"*9,
                         3, 183, 1, 0x2000, 64, 0, 0, 64, 56, 1, 0, 0, 0)
    ph = struct.pack("<IIQQQQQQ", 1, 5, 4096, 0x2000, 0x2000, 4096, 4096, 4096)
    # NOP and RET are authored fixture bytes, not a replacement callee body.
    body = bytes.fromhex("1f2003d5c0035fd6") + b"\0" * (4096-8)
    return header + ph + b"\0" * (4096-len(header)-len(ph)) + body


def test_unknown_context_keeps_all_code_and_adds_no_initialized_bytes():
    source = fragment()
    calls = (UnknownCall(0x8120, "unresolved_a"), UnknownCall(0x8180, "unresolved_b"),
             UnknownCall(0xA004, "unresolved_c"))
    result = add_unknown_call_context(source, calls)
    assert len(result.artifact) == len(source)
    assert result.artifact[4096:] == source[4096:]
    assert source == fragment() and result.unknown_pages == (0x8000, 0xA000)
    assert struct.unpack_from("<H", result.artifact, 56)[0] == 3
    for offset in (120, 176):
        kind, flags, file_offset, address, physical, size, memory_size, alignment = struct.unpack_from(
            "<IIQQQQQQ", result.artifact, offset)
        assert (kind, flags, file_offset, size, memory_size, alignment) == (1, 4, len(source), 0, 4096, 4096)
        assert address == physical
    assert "\tfunction\t" not in result.labels and "\tcode\t" not in result.labels
    assert result == add_unknown_call_context(source, tuple(reversed(calls)))


@pytest.mark.parametrize("calls", [
    (UnknownCall(0x2000, "overlap"),),
    (UnknownCall(0x8001, "unaligned"),),
    (UnknownCall(0x8000, "bad\nlabel"),),
    (UnknownCall(0x8000, "dup"), UnknownCall(0x9000, "dup")),
    (UnknownCall(0x8000, "one"), UnknownCall(0x8000, "two")),
    (UnknownCall(True, "boolean_address"),),
])
def test_bad_context_cannot_patch_source_or_inject_seed_commands(calls):
    source = fragment()
    with pytest.raises(ValueError):
        add_unknown_call_context(source, calls)
    assert source == fragment()


def test_header_capacity_exhaustion_is_rejected_instead_of_moving_code():
    source = fragment()
    with pytest.raises(ValueError, match="header space"):
        add_unknown_call_context(source, tuple(UnknownCall(0x100000+i*4096, "target_"+str(i)) for i in range(80)))
    assert source == fragment()


@pytest.mark.parametrize("offset,value", [(4, 1), (18, 0), (32, 0), (113, 0)])
def test_wrong_format_or_mapping_is_rejected(offset, value):
    raw = bytearray(fragment())
    raw[offset] = value
    with pytest.raises(ValueError):
        add_unknown_call_context(bytes(raw), (UnknownCall(0x8000, "target"),))
