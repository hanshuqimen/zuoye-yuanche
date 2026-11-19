"""Read selected frozen metadata attributes without executing client code.

Definition layouts shared by several IL2CPP versions do not establish a
metadata version. This reader validates the observed 8-byte token/data-offset
table independently, then resolves attribute constructors using decoded method
definitions. It only interprets a single typeof argument of JsonConverter.
Other argument payloads remain explicitly unverified. No process or auth data
is read, and the original ELF and metadata are never modified.
"""

import argparse
import hashlib
import itertools
import json
import struct
from pathlib import Path

if __package__:
    from .client_metadata_pages import METADATA_HASH
    from .inspect_client_native_types import ELF_HASH, NativeTypes
else:
    from client_metadata_pages import METADATA_HASH
    from inspect_client_native_types import ELF_HASH, NativeTypes

PREFIXES = frozenset({0x01, 0x02, 0x04, 0x06, 0x08, 0x14, 0x17, 0x20, 0x2A})
MAX_ATTRIBUTES = 32  # A bounded research budget, not an IL2CPP format limit.


def compressed_uint(data, at=0):
    """Return an IL2CPP compressed unsigned integer and its next byte offset."""
    if not 0 <= at < len(data):
        raise ValueError("Truncated attribute integer")
    first = data[at]
    if first < 0x80:
        size, value = 1, first
    elif first & 0xC0 == 0x80:
        size, value = 2, None
    elif first & 0xE0 == 0xC0:
        size, value = 4, None
    elif first == 0xF0:
        size, value = 5, None
    elif first in (0xFE, 0xFF):
        size, value = 1, 0xFFFFFFFE if first == 0xFE else 0xFFFFFFFF
    else:
        raise ValueError("Unsupported attribute integer prefix")
    if at + size > len(data):
        raise ValueError("Truncated attribute integer")
    if value is None:
        value = int.from_bytes(data[at + 1:at + 5], "little") if size == 5 else (
            int.from_bytes(data[at:at + size], "big") & (0x7FFF if size == 2 else 0x3FFFFFFF))
    return value, at + size


def type_argument(payload):
    """Decode only the exact one-type/no-named-arguments attribute form."""
    if payload[:4] != bytes((1, 0, 0, 0xFF)):
        return None
    value, end = compressed_uint(payload, 4)
    if end != len(payload):
        return None
    return -2147483648 if value == 0xFFFFFFFF else -(value // 2 + 1) if value & 1 else value // 2


class AttributeData:
    """Independent token markers and constructor identities must agree by page."""

    def __init__(self, raw, *, range_start, range_size, data_start, data_size):
        if (any(type(n) is not int or n < 0 for n in (range_start, range_size, data_start, data_size))
                or range_start % 8 or not range_size or range_size % 8 or not data_size
                or range_start + range_size > len(raw) or data_start + data_size > len(raw)
                or max(range_start, data_start) < min(range_start + range_size, data_start + data_size)):
            raise ValueError("Attribute sections differ from the observed bounded layout")
        self.raw, self.data_start = raw, data_start
        self.blob_keys = {}
        keys, rows = {}, []
        for at in range(range_start, range_start + range_size, 8):
            token, offset = struct.unpack_from("<2I", raw, at)
            choices = [key for key in (0, 0x66)
                       if (token ^ (key * 0x01010101)) >> 24 in PREFIXES
                       and (offset ^ (key * 0x01010101)) <= data_size]
            if len(choices) != 1:
                raise ValueError("Attribute range marker has ambiguous or invalid protection")
            key, page = choices[0], at // 4096
            if page in keys and keys[page] != key:
                raise ValueError("Attribute range markers disagree on page protection")
            keys[page] = key
            mask = key * 0x01010101
            rows.append((token ^ mask, offset ^ mask))
        if (len(rows) < 2 or rows[0][1] != 0 or rows[-1][0] & 0xFFFFFF
                or not 0 <= data_size - rows[-1][1] < 4
                or any(a[1] >= b[1] for a, b in zip(rows, rows[1:]))):
            raise ValueError("Attribute range order or terminal boundary differs")
        self.rows = tuple(rows)
        self.padding = data_size - rows[-1][1]
        self.blob_keys = dict(keys)

    def entries(self, first, count):
        if (type(first) is not int or type(count) is not int or min(first, count) < 0
                or first + count >= len(self.rows)):
            raise ValueError("Attribute image range is outside the table")
        selected = self.rows[first:first + count]
        if len({r[0] for r in selected}) != count:
            raise ValueError("Duplicate attribute tokens within one image")
        return {r[0]: first + index for index, r in enumerate(selected)}

    def constructors(self, index, lookup):
        """lookup accepts only known instance constructors; never executes them."""
        if type(index) is not int or not 0 <= index < len(self.rows) - 1:
            raise ValueError("Attribute entry is outside the table")
        lo, hi = self.rows[index][1], self.rows[index + 1][1]
        a, b = self.data_start + lo, self.data_start + hi
        candidates = []
        for key in (0, 0x66):
            count = self.raw[a] ^ key
            if not 1 <= count <= MAX_ATTRIBUTES or 1 + count * 4 > b - a:
                continue
            pages = sorted({p // 4096 for p in range(a, a + 1 + count * 4)})
            for values in itertools.product((0, 0x66), repeat=len(pages)):
                choices = dict(zip(pages, values, strict=True))
                if choices[a // 4096] != key or any(
                        page in self.blob_keys and self.blob_keys[page] != value
                        for page, value in choices.items()):
                    continue
                prefix = bytes(self.raw[p] ^ choices[p // 4096] for p in range(a, a + 1 + count * 4))
                ids = struct.unpack("<" + "I" * count, prefix[1:])
                try:
                    names = [lookup(i) for i in ids]
                except (ValueError, IndexError):
                    continue
                candidates.append((ids, names, choices))
        if len(candidates) != 1:
            raise ValueError("Attribute constructor evidence is ambiguous or unavailable")
        ids, names, choices = candidates[0]
        self.blob_keys.update(choices)
        attributes = [{"constructor": i, "type": name, "arguments_verified": False}
                      for i, name in zip(ids, names, strict=True)]
        payload = None
        if all(p // 4096 in self.blob_keys for p in range(a, b)):
            decoded = bytes(self.raw[p] ^ self.blob_keys[p // 4096] for p in range(a, b))
            payload = decoded[1 + len(ids) * 4:]
        return attributes, payload


def inspect(elf, metadata, type_indices):
    if (type(type_indices) is not tuple or not 1 <= len(type_indices) <= 512
            or any(type(i) is not int or not 0 <= i < 49382 for i in type_indices)):
        raise ValueError("Select one to 512 frozen type indices")
    native = NativeTypes(elf, metadata)
    raw = metadata.read_bytes()
    if hashlib.sha256(raw).hexdigest() != METADATA_HASH:
        raise ValueError("Metadata fingerprint changed during inspection")
    table = AttributeData(raw, range_start=native.header[52], range_size=native.header[53],
                          data_start=native.header[50], data_size=native.header[51])
    images = []
    for at in range(native.header[42], native.header[42] + native.header[43], 40):
        image = struct.unpack_from("<10I", native.meta, at)
        first, count = image[8:10]
        entries = table.entries(first, count)
        images.append((native.string(image[0]), image[2], image[3], entries))

    def constructor(index):
        if not 0 <= index < native.header[13] // 32:
            raise ValueError("Constructor index is outside method definitions")
        row = struct.unpack_from("<5iI4H", native.meta, native.header[12] + index * 32)
        if native.string(row[0]) != ".ctor" or row[5] >> 24 != 6 or not 0 <= row[1] < 49382:
            raise ValueError("Attribute does not reference an instance constructor")
        return native.class_name(row[1])

    def attributes(entries, token):
        if token not in entries:
            return []
        result, payload = table.constructors(entries[token], constructor)
        if len(result) == 1 and result[0]["type"] == "Newtonsoft.Json.JsonConverterAttribute" and payload:
            index = type_argument(payload)
            if index is not None:
                if not 0 <= index < native.type_count:
                    raise ValueError("Converter argument is not a concrete native type")
                result[0] |= {"arguments_verified": True, "converter_type_index": index,
                              "converter_type": native.index_name(index)}
        return result

    types = []
    for index in dict.fromkeys(type_indices):
        row = struct.unpack_from("<16I8H2I", native.meta, native.header[40] + index * 88)
        matches = [r for r in images if r[1] <= index < r[1] + r[2]]
        if len(matches) != 1 or row[25] >> 24 != 2:
            raise ValueError("Selected type is not uniquely bound to one metadata image")
        image, _, _, entries = matches[0]
        first, count = row[8], row[18]
        maximum = native.header[25] // 12
        if count and first + count > maximum or not count and first > maximum and first != 0xFFFFFFFF:
            raise ValueError("Selected field range is outside metadata definitions")
        fields = []
        for field in range(first, first + count):
            name, _, token = struct.unpack_from("<3I", native.meta, native.header[24] + field * 12)
            if token >> 24 != 4:
                raise ValueError("Selected field token differs")
            fields.append({"index": field, "name": native.string(name), "token": hex(token),
                           "attributes": attributes(entries, token)})
        types.append({"index": index, "name": native.class_name(index), "image": image,
                      "attributes": attributes(entries, row[25]), "fields": fields})
    return {"metadata_sha256": METADATA_HASH, "elf_sha256": ELF_HASH,
            "attribute_layout": "token/u32-data-offset; 8 bytes", "range_count": len(table.rows),
            "trailing_alignment_bytes_not_interpreted": table.padding, "types": types,
            "runtime_values_or_official_credentials_read": False, "other_arguments_verified": False}


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, default=root / ".cache/client-metadata/libil2cpp.so")
    parser.add_argument("--metadata", type=Path, default=root / "data/research/cached-global-metadata.dat")
    parser.add_argument("--type-index", action="append", type=int, required=True,
                        help="Exact metadata type index; repeat to inspect a bounded family")
    args = parser.parse_args()
    try:
        result = inspect(args.elf, args.metadata, tuple(args.type_index))
    except (ValueError, OSError) as exc:
        parser.exit(2, json.dumps({"error": "ATTRIBUTE_INSPECTION_FAILED", "message": str(exc)}) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
