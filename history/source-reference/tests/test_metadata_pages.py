"""Protection-page evidence must survive rows crossing page boundaries."""

import struct

import pytest

from tools.research.client_metadata_pages import decoded_view


def test_definition_crossing_two_differently_protected_pages():
    plain = bytearray(8192)
    header = [0] * 64
    header[12:14] = [256, 32]
    struct.pack_into("<I", plain, 276, 0x06000001)
    header[40:42] = [4028, 88]
    struct.pack_into("<I", plain, 4028, 37)  # Name index before the protection boundary.
    struct.pack_into("<I", plain, 4112, 0x02000001)  # Token after the boundary.
    header[42:44] = [4200, 40]
    struct.pack_into("<I", plain, 4228, 1)
    protected = bytes(plain[:4096]) + bytes(value ^ 0x66 for value in plain[4096:])
    view, report = decoded_view(protected, tuple(header))
    assert view == bytes(plain)
    assert struct.unpack_from("<I", view, 4028)[0] == 37
    assert report["page_counts"] == {0: 1, 0x66: 1}


def test_conflicting_independent_markers_are_rejected():
    body = bytearray(4096)
    header = [0] * 64
    header[12:14] = [256, 64]
    struct.pack_into("<I", body, 276, 0x06000001)
    struct.pack_into("<I", body, 308, 0x06000002 ^ 0x66666666)
    with pytest.raises(ValueError, match="disagree"):
        decoded_view(bytes(body), tuple(header))


@pytest.mark.parametrize("key", [0, 0x66])
def test_uppercase_identifier_pages_use_nul_separators_when_control_scores_tie(key):
    body = bytearray(4096)
    header = [0] * 64
    names = b"PUBLIC_VALUE\0" * 12
    header[6:8] = [256, len(names)]
    body[256:256 + len(names)] = names
    protected = bytes(value ^ key for value in body)
    view, report = decoded_view(protected, tuple(header))
    assert view[256:256 + len(names)] == names
    assert report["identifier_classified_pages"] == 1


@pytest.mark.parametrize("left_key,right_key", [(0, 0x66), (0x66, 0)])
@pytest.mark.parametrize("data_index,value_size", [(0, 4), (0xFFFFFFFF, 0)])
def test_default_definition_crosses_pages_with_independent_word_evidence(left_key, right_key, data_index, value_size):
    plain = bytearray(8192)
    header = [0] * 64
    header[24:26] = [256, 12]
    struct.pack_into("<3I", plain, 256, 0, 8, 0x04000001)
    header[16:18] = [4092, 12]
    struct.pack_into("<3I", plain, 4092, 0, 8, data_index)
    header[18:20] = [5000, value_size]
    protected = bytes(value ^ left_key for value in plain[:4096]) + bytes(
        value ^ right_key for value in plain[4096:])
    view, _ = decoded_view(protected, tuple(header))
    assert view == bytes(plain)
    assert struct.unpack_from("<3I", view, 4092) == (0, 8, data_index)


def test_default_word_conflicting_with_independent_field_token_is_rejected():
    body = bytearray(4096)
    header = [0] * 64
    header[24:26] = [256, 12]
    struct.pack_into("<3I", body, 256, 0, 8, 0x04000001)
    header[16:18] = [300, 12]
    struct.pack_into("<3I", body, 300, 0x66666666, 8, 0xFFFFFFFF)
    with pytest.raises(ValueError, match="disagree"):
        decoded_view(bytes(body), tuple(header))


@pytest.mark.parametrize("section,stride", [(12, 32), (42, 40), (16, 12)])
def test_bad_structure_stride_is_rejected(section, stride):
    header = [0] * 64
    header[section:section + 2] = [256, stride - 1]
    with pytest.raises(ValueError, match="stride"):
        decoded_view(bytes(4096), tuple(header))


def test_out_of_file_section_is_rejected_before_unpacking():
    header = [0] * 64
    header[40:42] = [4052, 88]
    with pytest.raises(ValueError, match="bounds"):
        decoded_view(bytes(4096), tuple(header))
