"""Index the owned, frozen official APK's complete IL2CPP definitions.

The SQLite index is research data, not a server dependency. No official service,
authentication file or player heap is read. Protected bodies and unresolved
generic/virtual calls remain explicit gaps; an address is not an implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import struct
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

if __package__:
    from .inspect_client_native_types import ELF_HASH, METADATA_HASH, NativeTypes
else:
    from inspect_client_native_types import ELF_HASH, METADATA_HASH, NativeTypes

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache/client-metadata"
APK_HASH = "0b79b85383e21a6343283bc6bfd7a9d24eb4134abf901115f757da6a5d50f6db"
DATABASE = CACHE / "official-index.sqlite3"
CODE_REGISTRATION = 0xBAD2390
ROUTE = re.compile(
    r"^/?(?:account|quest|charBuild|gacha|shop|mail|mission|building|social|story|activity|"
    r"roguelike|sandbox|tower|campaign|pay|crisisV2|crisis|user|businessCard|medal|recruit)/[\w/.-]{1,160}$"
)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_output(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(CACHE.resolve()):
        raise ValueError("Research outputs must stay in the private workspace cache")
    return resolved


class Indexer:
    def __init__(self):
        self.native = NativeTypes(CACHE / "libil2cpp.so", ROOT / "data/research/cached-global-metadata.dat")
        self.header = self.native.header
        self.metadata_pages = self.native.metadata_pages
        self.unresolved = Counter()
        self.native_names = {}
        self.loaded_receipt = None
        receipt_path = CACHE / "loaded-tables/receipt.json"
        if receipt_path.is_file():
            receipt = json.loads(receipt_path.read_bytes())
            if receipt["elf_sha256"] != ELF_HASH or receipt["metadata_sha256"] != METADATA_HASH:
                raise ValueError("Loaded static table receipt belongs to a different client")
            patched = bytearray(self.native.blob)
            for item in receipt["slices"]:
                path = (receipt_path.parent / item["file"]).resolve()
                if not path.is_relative_to(receipt_path.parent.resolve()):
                    raise ValueError("Static table slice path escapes the research cache")
                body = path.read_bytes()
                if (len(body) != item["bytes"] or len(body) > 65536 or
                        hashlib.sha256(body).hexdigest() != item["sha256"]):
                    raise ValueError("Loaded static table slice fingerprint differs")
                address = item["rva"]
                segment = self.native.segments[0]
                if not 4096 <= address < address + len(body) <= segment[5]:
                    raise ValueError("Loaded static table slice exceeds the frozen segment")
                patched[address:address + len(body)] = body
            self.native.blob = patched
            self.loaded_receipt = digest(receipt_path)

    def row(self, section: int, index: int, fmt: str, token_at: int | None = None, prefix: int = 0):
        stride = struct.calcsize(fmt)
        start, size = self.header[section:section + 2]
        if size % stride or not 0 <= index < size // stride:
            raise ValueError(f"Section {section} row is outside the frozen layout")
        raw = self.native.meta[start + index * stride:start + (index + 1) * stride]
        row = struct.unpack(fmt, raw)
        if token_at is not None and row[token_at] & 0xFF000000 != prefix:
            raise ValueError(f"Section {section} token decoding failed at row {index}")
        return row

    def type_name(self, index: int) -> str | None:
        if index == -1 or index == 0xFFFFFFFF:
            return None
        if index not in self.native_names:
            try:
                self.native_names[index] = self.native.index_name(index)
            except (ValueError, UnicodeError, struct.error) as exc:
                self.unresolved[type(exc).__name__ + ": " + str(exc)] += 1
                self.native_names[index] = f"<unresolved-native-type:{index}>"
        return self.native_names[index]

    def native_string(self, address: int) -> str:
        for segment in self.native.segments:
            if segment[3] <= address < segment[3] + segment[5]:
                pos = segment[2] + address - segment[3]
                end = self.native.blob.find(b"\0", pos, min(pos + 512, segment[2] + segment[5]))
                if end < 0:
                    break
                return self.native.blob[pos:end].decode("ascii")
        raise ValueError("Native module name is outside the frozen file-backed ELF")

    def modules(self):
        registration = self.native.read(CODE_REGISTRATION, "<15Q")
        if registration[13] != 88:
            raise ValueError("Code registration module count differs")
        pointers = self.native.read(registration[14], "<88Q")
        result = {}
        for pointer in pointers:
            name_ptr, count, methods_ptr = self.native.read(pointer, "<3Q")
            name = self.native_string(name_ptr)
            if name in result or (not name.endswith(".dll") and name != "__Generated") or count > self.header[13] // 32:
                raise ValueError("Code generation module identity differs")
            try:
                methods = self.native.read(methods_ptr, "<" + str(count) + "Q") if count else ()
            except ValueError:
                if not any(s[3] <= methods_ptr and methods_ptr + count * 8 <= s[3] + s[6]
                           for s in self.native.segments):
                    raise
                self.unresolved["module pointer array in zero-filled ELF region: " + name] += count
                methods = (0,) * count
            result[name] = (pointer, methods)
        return result

    def routes(self):
        found = []
        for index in range(self.header[3] // 8):
            start = self.header[2] + index * 8
            raw = self.native.meta[start:start + 8]
            length, offset = struct.unpack("<2I", raw)
            if not (length <= self.header[5] and offset + length <= self.header[5]):
                length, offset = struct.unpack("<2I", bytes(value ^ 0x66 for value in raw))
            if offset + length > self.header[5]:
                self.unresolved["managed literal definition has additional protection"] += 1
                continue
            if not 3 <= length <= 180:
                continue
            data = self.native.meta[self.header[4] + offset:self.header[4] + offset + length]
            for candidate in (data, bytes(value ^ 0x66 for value in data)):
                try:
                    value = candidate.decode("ascii")
                except UnicodeError:
                    continue
                if ROUTE.fullmatch(value):
                    found.append((index, value))
                    break
        return found

    def index_generics(self, con):
        if not self.loaded_receipt:
            return {"status": "loaded static tables required"}
        registration = self.native.read(0xBE31388, "<16Q")
        code = self.native.read(CODE_REGISTRATION, "<15Q")
        con.executescript("""
            CREATE TABLE generic_instantiations(id INTEGER PRIMARY KEY, arguments TEXT);
            CREATE TABLE method_specs(id INTEGER PRIMARY KEY, method_id INTEGER REFERENCES methods(id),
                class_inst INTEGER, method_inst INTEGER);
            CREATE TABLE generic_functions(id INTEGER PRIMARY KEY, spec_id INTEGER REFERENCES method_specs(id),
                native_rva INTEGER, method_pointer_index INTEGER, invoker_index INTEGER,
                adjustor_index INTEGER);
        """)
        instantiations = []
        for index, pointer in enumerate(self.native.read(registration[3], "<" + str(registration[2]) + "Q")):
            count, arguments = self.native.read(pointer, "<2Q")
            if not 1 <= count <= 32:
                raise ValueError("Generic argument count differs")
            names = [self.native.pointer_name(p) for p in self.native.read(arguments, "<" + str(count) + "Q")]
            instantiations.append((index, json.dumps(names, ensure_ascii=False)))
        con.executemany("INSERT INTO generic_instantiations VALUES(?,?)", instantiations)
        specs = self.native.read(registration[9], "<" + str(registration[8] * 3) + "i")
        spec_rows = []
        for index in range(registration[8]):
            method, owner, arguments = specs[index * 3:index * 3 + 3]
            if (not 0 <= method < self.header[13] // 32 or
                    not all(-1 <= i < registration[2] for i in (owner, arguments))):
                raise ValueError("Loaded method-spec indices differ")
            spec_rows.append((index, method, owner, arguments))
        con.executemany("INSERT INTO method_specs VALUES(?,?,?,?)", spec_rows)
        pointers = self.native.read(code[3], "<" + str(code[2]) + "Q")
        functions = self.native.read(registration[5], "<" + str(registration[4] * 4) + "i")
        rows = []
        for index in range(registration[4]):
            spec, method, invoker, adjustor = functions[index * 4:index * 4 + 4]
            if (not 0 <= spec < registration[8] or not 0 <= method < len(pointers) or
                    not -1 <= invoker < code[5] or adjustor < -1):
                raise ValueError("Loaded generic function indices differ")
            pointer = pointers[method]
            if pointer % 4 or not any(s[1] & 1 and s[3] <= pointer < s[3] + s[5]
                                      for s in self.native.segments):
                raise ValueError("Generic function address exceeds the frozen executable segments")
            rows.append((index, spec, pointer, method, invoker, adjustor))
        con.executemany("INSERT INTO generic_functions VALUES(?,?,?,?,?,?)", rows)
        con.executescript("""
            CREATE INDEX spec_method ON method_specs(method_id);
            CREATE INDEX generic_spec ON generic_functions(spec_id);
            CREATE INDEX generic_rva ON generic_functions(native_rva);
        """)
        return {"instantiations": len(instantiations), "method_specs": len(spec_rows), "functions": len(rows),
                "distinct_method_definitions": con.execute("SELECT COUNT(DISTINCT method_id) FROM method_specs "
                                                           "JOIN generic_functions ON spec_id=method_specs.id").fetchone()[0]}

    def build(self, output: Path):
        modules = self.modules()
        images, owners = [], {}
        for index in range(self.header[43] // 40):
            row = self.row(42, index, "<10I", 7, 0)
            name = self.native.string(row[0])
            if name not in modules or (row[3] and row[2] + row[3] > 49382):
                raise ValueError("Metadata image and native module do not match")
            images.append((index, name, row[2], row[3], len(modules[name][1])))
            for owner in range(row[2], row[2] + row[3]):
                if owner in owners:
                    raise ValueError("Metadata type belongs to two images")
                owners[owner] = name
        if len(owners) != 49382:
            raise ValueError("Metadata image coverage differs")
        con = sqlite3.connect(output)
        try:
            con.executescript("""
                PRAGMA journal_mode=DELETE;
                CREATE TABLE images(id INTEGER PRIMARY KEY, name TEXT UNIQUE, type_start INTEGER,
                    type_count INTEGER, method_pointer_count INTEGER);
                CREATE TABLE types(id INTEGER PRIMARY KEY, assembly TEXT, namespace TEXT, name TEXT,
                    full_name TEXT, parent_native_index INTEGER, parent TEXT, flags INTEGER,
                    token INTEGER, field_start INTEGER, field_count INTEGER, method_start INTEGER,
                    method_count INTEGER, generic_container INTEGER);
                CREATE TABLE fields(id INTEGER PRIMARY KEY, owner INTEGER REFERENCES types(id),
                    name TEXT, native_type_index INTEGER, type TEXT, token INTEGER, offset INTEGER);
                CREATE TABLE methods(id INTEGER PRIMARY KEY, owner INTEGER REFERENCES types(id),
                    name TEXT, token INTEGER, native_rva INTEGER, return_native_index INTEGER,
                    returns TEXT, parameters TEXT, flags INTEGER, iflags INTEGER, slot INTEGER,
                    generic_container INTEGER, address_status TEXT);
                CREATE TABLE route_literals(id INTEGER PRIMARY KEY, route TEXT);
                CREATE TABLE receipts(key TEXT PRIMARY KEY, value TEXT);
            """)
            con.executemany("INSERT INTO images VALUES(?,?,?,?,?)", images)
            registration = self.native.read(0xBE31388, "<16Q")
            offsets = self.native.read(registration[11], "<49382Q")
            types, fields, methods = [], [], []
            for index in range(49382):
                row = self.row(40, index, "<16I8H2I", 25, 0x02000000)
                name, namespace = self.native.string(row[0]), self.native.string(row[1])
                full_name = self.native.class_name(index)
                parent, container = (v if v < 0x80000000 else v - 0x100000000 for v in (row[4], row[6]))
                types.append((index, owners[index], namespace, name, full_name, parent,
                              self.type_name(parent), row[7], row[25], row[8], row[18], row[9], row[16], container))
                field_offsets = self.native.read(offsets[index], "<" + str(row[18]) + "i") if row[18] else ()
                for local, field_id in enumerate(range(row[8], row[8] + row[18])):
                    field = self.row(24, field_id, "<3I", 2, 0x04000000)
                    fields.append((field_id, index, self.native.string(field[0]), field[1],
                                   self.type_name(field[1]), field[2], field_offsets[local]))
                pointers = modules[owners[index]][1]
                for method_id in range(row[9], row[9] + row[16]):
                    method = self.row(12, method_id, "<5iI4H", 5, 0x06000000)
                    if method[1] != index:
                        raise ValueError("Method declaring type differs")
                    parameters = []
                    for parameter_id in range(method[3], method[3] + method[9]):
                        parameter = self.row(22, parameter_id, "<3I", 1, 0x08000000)
                        parameters.append({"name": self.native.string(parameter[0]), "native_index": parameter[2],
                                           "type": self.type_name(parameter[2])})
                    pointer_index = (method[5] & 0xFFFFFF) - 1
                    if not 0 <= pointer_index < len(pointers):
                        raise ValueError("Method token is outside its native module")
                    pointer = pointers[pointer_index]
                    if not pointer:
                        status = "generic-or-abstract-unresolved"
                    elif pointer % 4 == 0 and any(s[1] & 1 and s[3] <= pointer < s[3] + s[5]
                                                 for s in self.native.segments):
                        status = "static-address-body-protected"
                    else:
                        status = "invalid-static-pointer"
                        pointer = 0
                    methods.append((method_id, index, self.native.string(method[0]), method[5], pointer,
                                    method[2], self.type_name(method[2]), json.dumps(parameters, ensure_ascii=False),
                                    method[6], method[7], method[8], method[4], status))
                if index % 1000 == 999 or index == 49381:
                    con.executemany("INSERT INTO types VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", types)
                    con.executemany("INSERT INTO fields VALUES(?,?,?,?,?,?,?)", fields)
                    con.executemany("INSERT INTO methods VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", methods)
                    types, fields, methods = [], [], []
            con.executemany("INSERT INTO route_literals VALUES(?,?)", self.routes())
            generics = self.index_generics(con)
            con.executescript("""
                CREATE INDEX method_owner ON methods(owner);
                CREATE INDEX method_name ON methods(name);
                CREATE INDEX method_rva ON methods(native_rva);
                CREATE INDEX field_owner ON fields(owner);
                CREATE INDEX type_name ON types(full_name);
                CREATE INDEX type_short_name ON types(name);
            """)
            counts = {table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("images", "types", "fields", "methods", "route_literals")}
            if counts["fields"] != self.header[25] // 12 or counts["methods"] != self.header[13] // 32:
                raise ValueError("Full field or method coverage differs")
            report = {"created_at": datetime.now(UTC).isoformat(), "apk_sha256": APK_HASH,
                      "elf_sha256": ELF_HASH, "metadata_sha256": METADATA_HASH, "counts": counts,
                      "addresses": dict(con.execute("SELECT address_status, COUNT(*) FROM methods "
                                                    "GROUP BY address_status")),
                      "unresolved_type_names": dict(self.unresolved),
                      "loaded_static_tables_receipt_sha256": self.loaded_receipt,
                      "metadata_page_view": self.metadata_pages,
                      "generic_catalog": generics,
                      "limitations": ["Protected bodies need bounded loaded-code validation",
                                      "Generic bodies, hotfixes and virtual calls are not fully resolved",
                                      "Literal routes are candidates, not validated request contracts"]}
            for key, value in report.items():
                con.execute("INSERT INTO receipts VALUES(?,?)", (key, json.dumps(value, ensure_ascii=False)))
            con.commit()
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Research index integrity check failed")
            return report
        finally:
            con.close()


def build(output: Path, refresh: bool):
    output = safe_output(output)
    if output.exists() and not refresh:
        raise ValueError("An index exists; use --refresh to rebuild it after verification")
    apk = ROOT / "data/client/base.apk"
    if digest(apk) != APK_HASH:
        raise ValueError("Official APK differs from the frozen owned baseline")
    with ZipFile(apk) as archive:
        for member, expected in (("lib/arm64-v8a/libil2cpp.so", ELF_HASH),
                                 ("assets/bin/Data/Managed/Metadata/global-metadata.dat", METADATA_HASH)):
            with archive.open(member) as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                    raise ValueError("Official APK member fingerprint differs")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".building.sqlite3")
    if temporary.exists():
        raise ValueError("A previous incomplete index exists; inspect it before retrying")
    try:
        report = Indexer().build(temporary)
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    report["index_sha256"] = digest(output)
    output.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    return report


def query(path: Path, pattern: str, limit: int):
    path = safe_output(path)
    if not path.is_file():
        raise ValueError("Build the index first")
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("""SELECT m.id,t.full_name AS owner,m.name,m.returns,m.parameters,
                              m.native_rva,m.address_status FROM methods m JOIN types t ON t.id=m.owner
                              WHERE t.full_name LIKE ? OR m.name LIKE ? ORDER BY t.id,m.id LIMIT ?""",
                           ("%" + pattern + "%", "%" + pattern + "%", limit))
        result = []
        for row in rows:
            bodies = con.execute("""SELECT DISTINCT g.native_rva,ci.arguments AS class_arguments,
                mi.arguments AS method_arguments FROM method_specs s JOIN generic_functions g ON g.spec_id=s.id
                LEFT JOIN generic_instantiations ci ON ci.id=s.class_inst
                LEFT JOIN generic_instantiations mi ON mi.id=s.method_inst WHERE s.method_id=? LIMIT 8""", (row["id"],))
            samples = [dict(body) for body in bodies]
            resolution = ("registered-static-address" if row["native_rva"] else
                          "registered-generic-address" if any(body["native_rva"] for body in samples) else
                          "no-registered-address")
            result.append(dict(row) | {"parameters": json.loads(row["parameters"]),
                                       "native_address_resolution": resolution,
                                       "generic_bodies_sample": samples})
        return result


def calls(path: Path, capture: Path, start: int, size: int) -> dict:
    from capstone import CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN, Cs

    path, capture = safe_output(path), safe_output(capture)
    receipt = json.loads(capture.with_suffix(".json").read_bytes())
    body = capture.read_bytes()
    if len(body) != receipt["file_size"] or hashlib.sha256(body).hexdigest() != receipt["sha256"]:
        raise ValueError("Loaded code capture fingerprint differs")
    if not receipt["rva"] <= start < start + size <= receipt["rva"] + receipt["size"]:
        raise ValueError("Trace range must remain inside the originally requested code range")
    offset = start - receipt["file_start_rva"]
    disassembler = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    result = {"capture_sha256": receipt["sha256"], "rva": start, "size": size, "direct_calls": [],
              "indirect_calls": [], "direct_branches": [], "indirect_branches": [],
              "limitations": "Linear ARM64 sites; external branches are not proof of tail calls; dynamic dispatch and hotfix bodies unresolved"}
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        for instruction in disassembler.disasm(body[offset:offset + size], start):
            if instruction.mnemonic == "blr":
                result["indirect_calls"].append({"at": instruction.address, "register": instruction.op_str})
            if instruction.mnemonic == "br":
                result["indirect_branches"].append({"at": instruction.address, "register": instruction.op_str})
            if instruction.mnemonic not in {"bl", "b"}:
                continue
            target = int(instruction.op_str.removeprefix("#"), 16)
            if instruction.mnemonic == "b" and start <= target < start + size:
                continue
            names = [dict(row) for row in con.execute("""
                SELECT t.full_name AS owner,m.name,m.id FROM methods m JOIN types t ON t.id=m.owner
                WHERE m.native_rva=? UNION
                SELECT t.full_name,m.name,m.id FROM generic_functions g JOIN method_specs s ON s.id=g.spec_id
                JOIN methods m ON m.id=s.method_id JOIN types t ON t.id=m.owner WHERE g.native_rva=? LIMIT 12
            """, (target, target))]
            category = "direct_calls" if instruction.mnemonic == "bl" else "direct_branches"
            result[category].append({"at": instruction.address, "target": target, "methods": names})
    return result


def contracts(path: Path, output: Path) -> dict:
    path, output = safe_output(path), safe_output(output)
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        candidates = list(con.execute("""SELECT * FROM types WHERE assembly IN
            ('Assembly-CSharp.dll','Torappu.Common.dll') AND (name LIKE '%Request' OR
            name LIKE '%Response' OR name LIKE '%Result' OR name IN
            ('PlayerDataModel','PlayerDataDelta','PlayerPushFlags','PlayerResponseMeta')) ORDER BY id"""))
        definitions = []
        for candidate in candidates:
            fields = [dict(row) for row in con.execute(
                "SELECT name,type,native_type_index,offset FROM fields WHERE owner=? ORDER BY id", (candidate["id"],))]
            definitions.append({"type_id": candidate["id"], "name": candidate["full_name"],
                                "parent": candidate["parent"], "declared_fields": fields,
                                "generic_container": candidate["generic_container"]})
        report = {"apk_sha256": APK_HASH, "metadata_sha256": METADATA_HASH, "index_sha256": digest(path),
                  "verification": "compiled-type-candidate", "types": definitions,
                  "route_candidates": [dict(row) for row in con.execute("SELECT * FROM route_literals ORDER BY id")],
                  "limitations": ["Suffix matches include some non-network types",
                                  "CLR names do not establish JSON aliases, defaults or business rules",
                                  "ELF field offsets include static-relative entries and generic placeholders",
                                  "Parent fields are listed on their own declaring type"]}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    return {"types": len(definitions), "declared_fields": sum(len(row["declared_fields"]) for row in definitions),
            "routes": len(report["route_candidates"]), "output": str(output), "sha256": digest(output)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DATABASE)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("build", help="Verify the official APK and index every metadata definition")
    prepare.add_argument("--refresh", action="store_true")
    search = commands.add_parser("query", help="Read function signatures and native addresses")
    search.add_argument("pattern")
    search.add_argument("--limit", type=int, default=30, choices=range(1, 501), metavar="1..500")
    trace = commands.add_parser("calls", help="Resolve direct calls in a fingerprinted loaded-code capture")
    trace.add_argument("capture", type=Path)
    trace.add_argument("--rva", type=lambda value: int(value, 0), required=True)
    trace.add_argument("--size", type=lambda value: int(value, 0), required=True)
    export = commands.add_parser("contracts", help="Export versioned request/response type candidates")
    export.add_argument("--output", type=Path, default=CACHE / "protocol-contracts.json")
    args = parser.parse_args()
    if args.command == "build":
        result = build(args.database, args.refresh)
    elif args.command == "calls":
        result = calls(args.database, args.capture, args.rva, args.size)
    elif args.command == "contracts":
        result = contracts(args.database, args.output)
    else:
        result = query(args.database, args.pattern, args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))
