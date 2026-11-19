"""Resolve selected protocol field types from the frozen ARM64 ELF and metadata.

Uses only local files; no process injection, memory dump or credentials. Layouts
are based on Il2CppDumper's public Il2CppClass.cs. Both input fingerprints and
the registration counts are checked before interpreting any pointer.
"""

import argparse
import hashlib
import json
import struct
from functools import lru_cache
from pathlib import Path

if __package__:
    from .client_metadata_pages import METADATA_HASH as METADATA_HASH
    from .client_metadata_pages import frozen_view
    from .inspect_client_metadata import inspect
else:
    from client_metadata_pages import METADATA_HASH as METADATA_HASH
    from client_metadata_pages import frozen_view
    from inspect_client_metadata import inspect

ELF_HASH = "3ece1e7b34165233fe8c3c919cf55dfcb4406b6bbc2725def2b1242b4c0a6259"
PRIMITIVES = {1: "void", 2: "bool", 3: "char", 4: "sbyte", 5: "byte", 6: "short", 7: "ushort",
              8: "int", 9: "uint", 10: "long", 11: "ulong", 12: "float", 13: "double",
              14: "string", 22: "TypedReference", 24: "IntPtr", 25: "UIntPtr", 28: "object"}


class NativeTypes:
    def __init__(self, elf: Path, metadata: Path):
        self.blob = elf.read_bytes()
        if hashlib.sha256(self.blob).hexdigest() != ELF_HASH:
            raise ValueError("Input fingerprint differs from the frozen client")
        self.meta, self.header, self.metadata_pages = frozen_view(metadata.read_bytes())
        header = struct.unpack_from("<16sHHIQQQIHHHHHH", self.blob)
        if header[0][:6] != b"\x7fELF\x02\x01":
            raise ValueError("Expected a little-endian ELF64")
        self.segments = [section for index in range(header[10]) if (section := struct.unpack_from(
            "<II6Q", self.blob, header[5] + index * header[9]))[0] == 1]
        # Validated metadata registration in this exact ELF; never reuse in a new version.
        registration = self.read(0xBE31388, "<16Q")
        self.type_count, self.types = registration[6:8]
        if self.type_count != 120692 or registration[10] != 49382 or registration[12] != 49382:
            raise ValueError("Metadata registration counts differ")

    def read(self, address, format):
        size = struct.calcsize(format)
        for section in self.segments:
            if section[3] <= address and address + size <= section[3] + section[5]:
                return struct.unpack_from(format, self.blob, section[2] + address - section[3])
        raise ValueError("Native metadata pointer is outside file-backed ELF segments")

    def string(self, index):
        start, size = self.header[6:8]
        if not 0 <= index < size:
            raise ValueError("Metadata string index out of bounds")
        position = start + index
        end = self.meta.find(b"\0", position, start + size)
        if end < 0:
            raise ValueError("Unterminated metadata string")
        data = self.meta[position:end]
        return data.decode("utf-8")

    @lru_cache(maxsize=1024)
    def class_name(self, index):
        if not 0 <= index < 49382:
            raise ValueError("Native class index out of bounds")
        position = self.header[40] + index * 88
        data = self.meta[position:position + 88]
        row = struct.unpack("<16I8H2I", data)
        if row[25] & 0xFF000000 != 0x02000000:
            raise ValueError("Decoded class definition token differs")
        name, namespace = self.string(row[0]), self.string(row[1])
        if row[3] != 0xFFFFFFFF:
            if row[3] >= self.type_count:
                raise ValueError("Nested type's declaring type index is out of bounds")
            return self.index_name(row[3]) + "+" + name
        return (namespace + "." if namespace else "") + name

    def index_name(self, index):
        if not 0 <= index < self.type_count:
            raise ValueError("Native type index out of bounds")
        pointer, = self.read(self.types + index * 8, "<Q")
        return self.pointer_name(pointer)

    @lru_cache(maxsize=2048)
    def pointer_name(self, pointer, depth=0):
        if depth > 16:
            raise ValueError("Native generic type nesting is too deep")
        data, bits = self.read(pointer, "<QI")
        kind = (bits >> 16) & 0xFF
        if kind in PRIMITIVES:
            return PRIMITIVES[kind]
        if kind in (17, 18):
            return self.class_name(data)
        if kind in (15, 29):
            return self.pointer_name(data, depth + 1) + ("*" if kind == 15 else "[]")
        if kind in (19, 30):
            start, size = self.header[26:28]
            if size % 16 or not 0 <= data < size // 16:
                raise ValueError("Native generic parameter index out of bounds")
            raw = self.meta[start + data * 16:start + (data + 1) * 16]
            row = struct.unpack("<2i2h2H", raw)
            if not 0 <= row[1] < self.header[7]:
                raise ValueError("Decoded generic parameter name index is out of bounds")
            return ("!" if kind == 19 else "!!") + self.string(row[1])
        if kind == 20:
            element, rank, _, _ = self.read(data, "<QBBB")
            if not 1 <= rank <= 32:
                raise ValueError("Native array rank out of bounds")
            return self.pointer_name(element, depth + 1) + "[" + "," * (rank - 1) + "]"
        if kind == 21:
            definition, instance, _, _ = self.read(data, "<4Q")
            count, arguments = self.read(instance, "<2Q")
            if not 1 <= count <= 32:
                raise ValueError("Native generic argument count out of bounds")
            names = [self.pointer_name(self.read(arguments + index * 8, "<Q")[0], depth + 1)
                     for index in range(count)]
            return self.pointer_name(definition, depth + 1) + "<" + ", ".join(names) + ">"
        raise ValueError(f"Unsupported native metadata type kind: {kind}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, default=Path(".cache/client-metadata/libil2cpp.so"))
    parser.add_argument("--metadata", type=Path, default=Path("data/research/cached-global-metadata.dat"))
    parser.add_argument("--type", action="append", default=[])
    parser.add_argument("--type-index", type=int, action="append", default=[])
    args = parser.parse_args()
    native = NativeTypes(args.elf, args.metadata)
    report = inspect(args.metadata, args.type, tuple(args.type_index))
    report["elf_sha256"] = ELF_HASH
    for definition in report["types"]:
        for field in definition["fields"]:
            field["native_type"] = native.index_name(field["type_index"])
    print(json.dumps(report, ensure_ascii=False, indent=2))
