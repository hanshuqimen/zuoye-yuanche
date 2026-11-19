"""Small synthetic ARM64 and registration fixtures, without game code."""

import hashlib
import json
import sqlite3
import struct
from pathlib import Path

import pytest


def miniature_index(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "tools/research"))
    import index_client

    monkeypatch.setattr(index_client, "CACHE", tmp_path)
    path = tmp_path / "index.sqlite3"
    with sqlite3.connect(path) as con:
        con.executescript("""
            CREATE TABLE types(id INTEGER, full_name TEXT);
            CREATE TABLE methods(id INTEGER, owner INTEGER, name TEXT, returns TEXT,
                parameters TEXT, native_rva INTEGER, address_status TEXT);
            CREATE TABLE method_specs(id INTEGER, method_id INTEGER, class_inst INTEGER, method_inst INTEGER);
            CREATE TABLE generic_functions(spec_id INTEGER, native_rva INTEGER);
            CREATE TABLE generic_instantiations(id INTEGER, arguments TEXT);
            INSERT INTO types VALUES(1,'Synthetic.Type');
            INSERT INTO methods VALUES(1,1,'CallTarget','void','[]',8192,'static-address-body-protected');
            INSERT INTO methods VALUES(2,1,'GenericTarget','void','[]',0,'unresolved');
            INSERT INTO methods VALUES(3,1,'BranchTarget','void','[]',12288,'static-address-body-protected');
            INSERT INTO method_specs VALUES(1,2,0,0);
            INSERT INTO generic_instantiations VALUES(0,'["object"]');
            INSERT INTO generic_functions VALUES(1,16384);
        """)
    return index_client, path


def test_query_distinguishes_generic_registration_from_unresolved_declarations(tmp_path, monkeypatch):
    module, path = miniature_index(tmp_path, monkeypatch)
    row = module.query(path, "GenericTarget", 1)[0]
    assert row["native_rva"] == 0 and row["address_status"] == "unresolved"
    assert row["native_address_resolution"] == "registered-generic-address"
    assert row["generic_bodies_sample"][0]["native_rva"] == 16384
    assert module.query(path, "CallTarget", 1)[0]["native_address_resolution"] == "registered-static-address"


def test_trace_reports_external_branches_and_rejects_tampered_captures(tmp_path, monkeypatch):
    module, path = miniature_index(tmp_path, monkeypatch)
    start = 0x1000

    def branch(opcode, at, target):
        return opcode | (((target - at) // 4) & 0x3FFFFFF)

    words = [branch(0x94000000, start, 0x2000),
             branch(0x14000000, start + 4, start + 16),
             branch(0x14000000, start + 8, 0x3000), 0xD61F0120] + [0xD503201F] * 4
    body = struct.pack("<8I", *words)
    capture = tmp_path / "capture.bin"
    capture.write_bytes(body)
    capture.with_suffix(".json").write_text(json.dumps({
        "rva": start, "size": len(body), "file_start_rva": start,
        "file_size": len(body), "sha256": hashlib.sha256(body).hexdigest()}))
    report = module.calls(path, capture, start, len(body))
    assert [row["target"] for row in report["direct_calls"]] == [0x2000]
    assert [row["target"] for row in report["direct_branches"]] == [0x3000]
    assert report["direct_branches"][0]["methods"][0]["name"] == "BranchTarget"
    assert report["indirect_branches"] == [{"at": start + 12, "register": "x9"}]
    capture.write_bytes(bytes([body[0] ^ 1]) + body[1:])
    with pytest.raises(ValueError, match="fingerprint"):
        module.calls(path, capture, start, len(body))
