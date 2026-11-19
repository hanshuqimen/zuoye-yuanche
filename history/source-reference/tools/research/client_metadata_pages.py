"""Decode the frozen metadata's page protection using independent token evidence.

Definition rows can cross 4 KiB boundaries. XORing an entire row based on its
last token corrupts the plaintext part of such a row. Each structural page must
have one consistent token-derived key. String pages use their identifier bytes;
this is a read-only derived view, never a rewritten APK or metadata baseline.
"""

import hashlib
import struct
from collections import Counter

METADATA_HASH = "bf14421bbafe9c71d944ba4f97b31ecd666232640eac0829db3d84ac716ac8b8"


def frozen_view(blob: bytes) -> tuple[bytes, tuple[int, ...], dict]:
    if hashlib.sha256(blob).hexdigest() != METADATA_HASH:
        raise ValueError("Metadata fingerprint differs; a new layout must be validated separately")
    if len(blob) < 256:
        raise ValueError("Metadata header is incomplete")
    # The first two words are deliberately not treated as a version assertion.
    header = struct.unpack("<64I", bytes(value ^ 0x66 for value in blob[:256]))
    for offset, size in zip(header[2::2], header[3::2]):
        if size and (offset < 256 or offset + size > len(blob)):
            raise ValueError("Metadata section bounds differ from the frozen layout")
    view, report = decoded_view(blob, header)
    return view, header, report


def decoded_view(blob: bytes, header: tuple[int, ...]) -> tuple[bytes, dict]:
    if len(header) != 64 or any(type(value) is not int or value < 0 for value in header):
        raise ValueError("Metadata section header differs")
    for offset, size in zip(header[2::2], header[3::2]):
        if size and (offset < 256 or offset + size > len(blob)):
            raise ValueError("Metadata section bounds differ")
    keys = {}

    def record(position, key):
        page = position // 4096
        if page in keys and keys[page] != key:
            raise ValueError("Independent metadata markers disagree on a page's protection")
        keys[page] = key

    # Token marker positions from the verified v27 definition layouts.
    for section, stride, token_offset, prefix in ((12, 32, 20, 0x06000000),
                                                  (22, 12, 4, 0x08000000),
                                                  (24, 12, 8, 0x04000000),
                                                  (40, 88, 84, 0x02000000)):
        start, size = header[section:section + 2]
        if size % stride:
            raise ValueError("Metadata definition stride differs")
        for position in range(start + token_offset, start + size, stride):
            value, = struct.unpack_from("<I", blob, position)
            if value & 0xFF000000 == prefix:
                record(position, 0)
            elif (value ^ 0x66666666) & 0xFF000000 == prefix:
                record(position, 0x66)
            else:
                raise ValueError("Metadata token marker has an unknown protection key")
    start, size = header[42:44]
    if size % 40:
        raise ValueError("Metadata image stride differs")
    for position in range(start + 28, start + size, 40):
        value, = struct.unpack_from("<I", blob, position)
        if value not in (0, 1, 0x66666666, 1 ^ 0x66666666):
            raise ValueError("Metadata image token differs")
        record(position, 0 if value <= 1 else 0x66)
    # Generic-parameter names are bounded indices even without a token. Managed
    # literals use additional protection; they are deliberately not classified.
    for section, stride, offset, maximum in ((26, 16, 4, header[7]),):
        start, size = header[section:section + 2]
        if size % stride:
            raise ValueError("Metadata auxiliary definition stride differs")
        for position in range(start + offset, start + size, stride):
            value, = struct.unpack_from("<I", blob, position)
            if value < maximum:
                record(position, 0)
            elif (value ^ 0x66666666) < maximum:
                record(position, 0x66)
            else:
                raise ValueError(f"Metadata auxiliary section {section} index at {position:#x} "
                                 f"has unknown protection: {value:#x}")
    # Defaults have no token. Their definition index and value-data index have
    # disjoint plaintext/XOR bounds, so infer each aligned word's page rather
    # than guessing one key for a row that may span differently protected pages.
    for section, maximum in ((14, header[23] // 12), (16, header[25] // 12)):
        start, size = header[section:section + 2]
        if size % 12:
            raise ValueError("Metadata default definition stride differs")
        for position in range(start, start + size, 12):
            for offset, bound, sentinel in ((0, maximum, False), (8, header[19], True)):
                address = position + offset
                if address % 4:
                    raise ValueError("Metadata default word is not aligned")
                value, = struct.unpack_from("<I", blob, address)
                choices = [key for key in (0, 0x66) if (value ^ (key * 0x01010101)) < bound or
                           (sentinel and (value ^ (key * 0x01010101)) == 0xFFFFFFFF)]
                if len(choices) != 1:
                    raise ValueError("Metadata default index has ambiguous or invalid protection")
                record(address, choices[0])
    classified = 0
    # Identifier pages contain no C0 controls except NUL separators. Protection
    # turns ordinary lowercase letters into those controls. UTF-8 validation
    # also distinguishes protected pages containing non-ASCII identifiers.
    start, size = header[6:8]
    for page in range(start // 4096, (start + size + 4095) // 4096):
        if page in keys:
            continue
        raw = blob[max(start, page * 4096):min(start + size, (page + 1) * 4096)]

        def score(data):
            return (sum(0 < value < 32 for value in data) +
                    data.decode("utf-8", "replace").count("\ufffd") - min(data.count(0), 32))

        scores = [(score(raw), 0), (score(bytes(value ^ 0x66 for value in raw)), 0x66)]
        scores.sort()
        if scores[1][0] - scores[0][0] < 4:
            raise ValueError(f"Metadata identifier page {page * 4096:#x} has ambiguous scores {scores}")
        keys[page] = scores[0][1]
        classified += 1
    view = bytearray(blob)
    for page, key in keys.items():
        if key:
            start, end = page * 4096, min((page + 1) * 4096, len(blob))
            view[start:end] = bytes(value ^ key for value in blob[start:end])
    return bytes(view), {"page_counts": dict(Counter(keys.values())), "identifier_classified_pages": classified,
                         "derived_sha256": hashlib.sha256(view).hexdigest()}
