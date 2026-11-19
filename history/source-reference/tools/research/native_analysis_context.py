"""Declare unknown callees in a bounded ARM64 analysis fragment, without code stubs.

This transforms an owned analysis container, never a client executable. Ghidra
may otherwise trace an unmapped direct call into bad data and truncate the
caller. Read-only, uninitialized ranges and labels describe that missing
context; they establish neither a callee implementation nor its return value.
"""

import re
import struct
from dataclasses import dataclass
from hashlib import sha256

ELF_HEADER = struct.Struct("<16sHHIQQQIHHHHHH")
PROGRAM_HEADER = struct.Struct("<IIQQQQQQ")
PAGE = 4096
MAX_CODE = 65536


@dataclass(frozen=True)
class UnknownCall:
    address: int
    label: str


@dataclass(frozen=True)
class AnalysisContext:
    artifact: bytes
    labels: str
    source_sha256: str
    artifact_sha256: str
    code_sha256: str
    unknown_pages: tuple[int, ...]


def add_unknown_call_context(source: bytes, calls: tuple[UnknownCall, ...]) -> AnalysisContext:
    """Keep every initialized byte; append only bounded uninitialized mappings.

    Call addresses must come from a separately verified instruction/metadata
    inventory. This helper does not discover calls, infer no-return semantics,
    repair disassembly, or authorize reading an address from a live process.
    """
    if type(source) is not bytes or not ELF_HEADER.size <= len(source) <= PAGE + MAX_CODE:
        raise ValueError("Expected a bounded immutable ELF fragment")
    header = ELF_HEADER.unpack_from(source)
    if (header[0][:7] != b"\x7fELF\x02\x01\x01" or header[1] not in (2, 3) or header[2] != 183
            or header[3] != 1 or header[5] != ELF_HEADER.size or header[6] != 0
            or header[8] != ELF_HEADER.size or header[9] != PROGRAM_HEADER.size
            or not 0 < header[10] <= 32 or any(header[i] for i in (11, 12, 13))):
        raise ValueError("Expected a section-free little-endian ARM64 fragment")
    count = header[10]
    end_headers = ELF_HEADER.size + count * PROGRAM_HEADER.size
    if end_headers > len(source):
        raise ValueError("Program headers exceed the source")
    segments = [PROGRAM_HEADER.unpack_from(source, ELF_HEADER.size + i * PROGRAM_HEADER.size)
                for i in range(count)]
    initialized, ranges, virtual_ranges = [], [], []
    for kind, flags, offset, address, physical, size, memory_size, alignment in segments:
        if (kind != 1 or flags != 5 or alignment != PAGE or offset < PAGE or offset % PAGE
                or address < PAGE or address % PAGE or address != physical or size != memory_size
                or not 0 < size <= MAX_CODE or size % PAGE or offset + size > len(source)
                or address + size >= 2**63):
            raise ValueError("Only initialized, bounded executable code segments are admitted")
        ranges.append((offset, offset + size))
        virtual_ranges.append((address, address + size))
        initialized.append(source[offset:offset + size])
    for spans in (ranges, virtual_ranges):
        ordered = sorted(spans)
        if any(left[1] > right[0] for left, right in zip(ordered, ordered[1:])):
            raise ValueError("Overlapping source mappings")
    if sum(len(body) for body in initialized) > MAX_CODE or max(b for _, b in ranges) != len(source):
        raise ValueError("Code budget exceeded or source has unexplained trailing bytes")
    if type(calls) is not tuple or not 0 < len(calls) <= 256:
        raise ValueError("Declare a bounded explicit tuple of unknown calls")
    addresses, labels, pages = set(), set(), set()
    for call in calls:
        if (type(call) is not UnknownCall or type(call.address) is not int
                or not PAGE <= call.address < 2**63 - PAGE or call.address % 4
                or type(call.label) is not str or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,199}", call.label)
                or call.address in addresses or call.label in labels):
            raise ValueError("Unknown calls require unique aligned addresses and safe labels")
        page = call.address // PAGE * PAGE
        if any(page < end and page + PAGE > start for start, end in virtual_ranges):
            raise ValueError("Unknown context must not overlap source code")
        addresses.add(call.address)
        labels.add(call.label)
        pages.add(page)
    unknown = tuple(sorted(pages))
    new_end = end_headers + len(unknown) * PROGRAM_HEADER.size
    first_code = min(a for a, _ in ranges)
    if new_end > first_code or any(source[end_headers:new_end]):
        raise ValueError("Insufficient empty header space; never move or overwrite code")
    artifact = bytearray(source)
    struct.pack_into("<H", artifact, 56, count + len(unknown))
    for i, page in enumerate(unknown):
        # PF_R only, filesz=0: no executable bytes, instructions or RET stubs.
        PROGRAM_HEADER.pack_into(artifact, end_headers + i * PROGRAM_HEADER.size,
                                 1, 4, len(source), page, page, 0, PAGE, PAGE)
    for offset, end in ranges:
        assert artifact[offset:end] == source[offset:end]
    result = bytes(artifact)
    text = "".join(f"{call.address:#x}\tlabel\t{call.label}\n" for call in sorted(calls, key=lambda c: c.address))
    return AnalysisContext(result, text, sha256(source).hexdigest(), sha256(result).hexdigest(),
                           sha256(b"".join(initialized)).hexdigest(), unknown)
