"""Read selected class/enum fields from the frozen 2.7.71 metadata.

Research only: no runtime injection, credentials, or official service calls.
The frozen header and protected pages are decoded by the shared evidence view;
type definitions follow Il2CppDumper's 88-byte v27 layout. Literal/default value
payloads remain raw interpretations, not verified client enum constants.
The untrusted first two header words are never used as a version assertion.
"""

import argparse
import hashlib
import json
import struct
from pathlib import Path

if __package__:
    from .client_metadata_pages import frozen_view
else:
    from client_metadata_pages import frozen_view


def inspect(path: Path, names: list[str], type_indices: tuple[int, ...] = (), *, methods: bool = False) -> dict:
    raw_blob = path.read_bytes()
    digest = hashlib.sha256(raw_blob).hexdigest()
    blob, header, page_report = frozen_view(raw_blob)
    string_start, string_size = header[6:8]
    field_start, field_size = header[24:26]
    type_start, type_size = header[40:42]
    method_start, method_size = header[12:14]
    default_start, default_size = header[16:18]
    value_start, value_size = header[18:20]
    if type_size % 88 or field_size % 12 or default_size % 12 or method_size % 32:
        raise ValueError("Metadata structure stride differs from the frozen layout")

    def string(index):
        if not 0 <= index < string_size:
            raise ValueError("Metadata string index out of bounds")
        end = blob.find(b"\0", string_start + index, string_start + string_size)
        if end < 0:
            raise ValueError("Unterminated metadata string")
        data = blob[string_start + index:end]
        return data.decode("utf-8")

    defaults = {}
    for position in range(default_start, default_start + default_size, 12):
        data = blob[position:position + 12]
        field, kind, index = struct.unpack("<3i", data)
        if not (0 <= field < field_size // 12 and kind >= 0 and -1 <= index < value_size):
            raise ValueError("Decoded field-default definition differs")
        defaults[field] = kind, index

    def compressed_int(index):
        data = raw_blob[value_start + index:value_start + min(value_size, index + 5)]
        first = data[0]
        if first < 0x80:
            encoded = first
        elif first & 0xC0 == 0x80:
            if len(data) < 2:
                raise ValueError("Truncated raw default value encoding")
            encoded = ((first & 0x7F) << 8) | data[1]
        elif first & 0xE0 == 0xC0:
            if len(data) < 4:
                raise ValueError("Truncated raw default value encoding")
            encoded = int.from_bytes(data[:4], "big") & 0x3FFFFFFF
        elif first == 0xF0:
            if len(data) < 5:
                raise ValueError("Truncated raw default value encoding")
            encoded = int.from_bytes(data[1:5], "little")
        elif first in (0xFE, 0xFF):
            encoded = 0xFFFFFFFE if first == 0xFE else 0xFFFFFFFF
        else:
            raise ValueError("Unsupported compressed metadata integer")
        return -2147483648 if encoded == 0xFFFFFFFF else (
            -((encoded >> 1) + 1) if encoded & 1 else encoded >> 1)
    wanted = set(names)
    selected = set(type_indices)
    if any(type(index) is not int or not 0 <= index < type_size // 88 for index in selected):
        raise ValueError("Selected metadata type index is out of bounds")
    rows = []
    for type_index, position in enumerate(range(type_start, type_start + type_size, 88)):
        data = blob[position:position + 88]
        row = struct.unpack("<16I8H2I", data)
        if row[25] & 0xFF000000 != 0x02000000:
            raise ValueError("Decoded type-definition token differs")
        name = string(row[0])
        if name not in wanted and type_index not in selected:
            continue
        start, count = row[8], row[18]
        if count and start + count > field_size // 12:
            raise ValueError("Metadata field range out of bounds")
        fields = []
        for field_index in range(start, start + count):
            position = field_start + field_index * 12
            data = blob[position:position + 12]
            field_name, kind, token = struct.unpack("<3I", data)
            if token & 0xFF000000 != 0x04000000:
                raise ValueError("Field-definition decoding failed")
            field = {"name": string(field_name), "type_index": kind, "index": field_index}
            if field_index in defaults:
                default_kind, index = defaults[field_index]
                field["default_type_index"] = default_kind
                if 0 <= index <= value_size - 4:
                    data = raw_blob[value_start + index:value_start + index + 4]
                    field["default_raw_int32"] = struct.unpack("<i", data)[0]
                    field["default_raw_hex"] = data.hex()
                    if row[24] & 2:
                        field["enum_default_protection_verified"] = False
                        try:
                            field["enum_default_raw_compressed_int32"] = compressed_int(index)
                        except ValueError as exc:
                            # Unknown payload protection must not turn into an
                            # invented enum value or invalidate known declarations.
                            field["enum_default_raw_decode_error"] = str(exc)
            fields.append(field)
        definition = {"name": name, "namespace": string(row[1]), "type_index": type_index,
                      "enum": bool(row[24] & 2), "fields": fields}
        if methods:
            start, count = row[9], row[16]
            if count and start + count > method_size // 32:
                raise ValueError("Metadata method range out of bounds")
            definition["methods"] = []
            for method_index in range(start, start + count):
                data = blob[method_start + method_index * 32:method_start + (method_index + 1) * 32]
                method = struct.unpack("<5iI4H", data)
                if method[5] & 0xFF000000 != 0x06000000 or method[1] != type_index:
                    raise ValueError("Method-definition decoding failed")
                definition["methods"].append({"name": string(method[0]), "index": method_index,
                                               "token": method[5], "return_type_index": method[2],
                                               "parameter_count": method[9]})
        rows.append(definition)
    return {"metadata_sha256": digest, "metadata_page_view": page_report, "types": rows,
            "default_value_payloads_verified": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=Path("data/research/cached-global-metadata.dat"))
    parser.add_argument("--type", action="append", default=[])
    parser.add_argument("--type-index", action="append", type=int, default=[])
    parser.add_argument("--methods", action="store_true")
    args = parser.parse_args()
    print(json.dumps(inspect(args.path, args.type, tuple(args.type_index), methods=args.methods),
                     ensure_ascii=False, indent=2))
