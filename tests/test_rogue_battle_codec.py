"""Authored ZIP/AES fixtures for frozen rogue records, not native settlement."""

import base64
import hashlib
import zipfile
from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError
from test_native_battle_finish import encoded
from test_native_replay import journal, packed

from terralocal.server.domain.errors import DomainError
from terralocal.server.protocol import rogue_battle_codec as codec
from terralocal.server.protocol.battle_codec import (
    DecodedRogueFinish,
    FinishRequest,
    decode_campaign_finish,
    decode_finish,
    decode_rogue_payload,
)

BATTLE = "20000000-0000-0000-0000-000000000009"
OTHER = "20000000-0000-0000-0000-000000000008"
LOGIN = 1_800_000_000


def snapshot(rows=None, **kwargs):
    return packed({"actionKill": [] if rows is None else rows}, **kwargs)


def request(*, rows=None, stage="test_1", log=True, state=3, changes=None, trace_changes=None):
    payload = encoded(BATTLE, state=state, changes={"stageId": stage, **(changes or {})},
                      trace_changes=trace_changes)
    value = journal()
    value["journal"]["metadata"]["stageId"] = stage
    value["journal"]["squad"][0]["skillIndex"] = -1
    payload.update(battleLog=packed(value) if log else None, rlv2Data={"battleSnapshot": snapshot(rows)})
    return codec.RogueFinishRequest.model_validate(payload)


def decode(payload):
    return codec.decode_finish_records(payload, [LOGIN], expected_battle_id=BATTLE, expected_stage_id="test_1")


@pytest.mark.parametrize("compression", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
def test_snapshot_preserves_order_wire_and_signed_action_coordinates(compression):
    # Different sub-schedulers may project the same three coordinates. Codec
    # admission must not invent a uniqueness/eligibility rule from one example.
    rows = [[0, 2, 3, 5], [0, 2, 3, 1], [-1, -2, -3, 2]]
    wire = snapshot(rows, compression=compression)
    result = codec.decode_snapshot(wire)
    assert [(r.wave, r.fragment, r.action, r.count) for r in result.actions] == [tuple(r) for r in rows]
    assert result.encoded == wire and result.sha256 == hashlib.sha256(wire.encode("ascii")).hexdigest()
    assert codec.decode_snapshot(wire) == result
    assert wire not in repr(result)
    with pytest.raises(FrozenInstanceError):
        result.sha256 = "changed"


def test_empty_snapshot_and_three_linked_finish_records():
    payload = request()
    result = decode(payload)
    assert result.snapshot.actions == () and result.snapshot.encoded == payload.rlv2Data.battleSnapshot
    assert isinstance(result.facts, DecodedRogueFinish)
    assert result.facts.battleId == BATTLE and result.journal.stage_id == "test_1"
    assert result.journal.squad[0].skill_index == -1
    assert payload.battleLog == result.journal.encoded
    assert "synthetic-not-an-auth-token" not in repr(result)
    assert payload.battleLog not in repr(result)


def test_snapshot_deaths_are_not_assumed_equal_to_weighted_valid_kills():
    result = decode(request(rows=[[0, 0, 0, 2]], changes={"killCnt": 7, "validKillCnt": 9}))
    assert result.snapshot.actions[0].count == 2
    assert result.facts.killCnt == 7 and result.facts.validKillCnt == 9


@pytest.mark.parametrize("rank", [1, 2, 3])
def test_rogue_rank_flags_remain_facts_while_existing_mode_guards_stay_strict(rank):
    payload = request(state=rank, changes={"interrupt": 1, "giveUp": 1})
    parsed = decode(payload)
    assert parsed.facts.completeState == rank and parsed.facts.interrupt and parsed.facts.giveUp
    common = FinishRequest(data=payload.data, battleData=payload.battleData)
    if rank != 1:
        with pytest.raises(DomainError):
            decode_finish(common, [LOGIN])
    else:
        assert decode_finish(common, [LOGIN]).completeState == 1
    if rank == 3:
        with pytest.raises(DomainError):
            decode_campaign_finish(common, [LOGIN])
    else:
        assert decode_campaign_finish(common, [LOGIN]).completeState == rank


def test_explicit_null_journal_is_distinct_from_omitted_field_and_grants_nothing():
    payload = request(log=False)
    assert decode(payload).journal is None
    for missing in ("battleLog", "rlv2Data"):
        value = payload.model_dump()
        del value[missing]
        with pytest.raises(ValidationError):
            codec.RogueFinishRequest.model_validate(value)


@pytest.mark.parametrize("damage", ["outer-signature", "inner-id", "stage", "journal-stage", "time", "key"])
def test_record_associations_checked_without_returning_partial_success(damage):
    payload = request()
    times = [LOGIN]
    expected = BATTLE
    if damage == "outer-signature":
        expected = OTHER
    elif damage == "inner-id":
        payload = request(changes={"battleId": OTHER})
    elif damage == "stage":
        payload = request(stage="foreign")
    elif damage == "journal-stage":
        value = journal()
        value["journal"]["metadata"]["stageId"] = "foreign"
        payload.battleLog = packed(value)
    elif damage == "time":
        payload.battleData.completeTime += 1
    else:
        times = [LOGIN + 1]
    with pytest.raises(DomainError):
        codec.decode_finish_records(payload, times, expected_battle_id=expected, expected_stage_id="test_1")


def test_signature_mismatch_is_rejected_before_archive_expansion(monkeypatch):
    payload = request()
    def forbidden(_):
        pytest.fail("Unowned signature reached archive decoder")
    monkeypatch.setattr(codec, "decode_snapshot", forbidden)
    with pytest.raises(DomainError):
        codec.decode_finish_records(payload, [LOGIN], expected_battle_id=OTHER, expected_stage_id="test_1")


def test_two_explicit_key_candidates_keep_original_payload_association():
    payload = request()
    assert decode_rogue_payload(payload, [LOGIN + 1, LOGIN]).battleId == BATTLE


@pytest.mark.parametrize("raw", [
    '[]', 'null', '{}', '{"actionKill":null}', '{"actionKill":{},"other":0}',
    '{"actionKill":[],"actionKill":[]}', '{"actionKill":[],"other":0}',
    '{"actionKill":[[0,0,0,1.0]]}', '{"actionKill":[[0,0,0,true]]}',
    '{"actionKill":[[0,0,0,0]]}', '{"actionKill":[[0,0,0,-1]]}',
    '{"actionKill":[[0,0,0,1,2]]}', '{"actionKill":[[0,0,1]]}',
    '{"actionKill":[[0,0,2147483648,1]]}', '{"actionKill":[[-2147483649,0,0,1]]}',
    '{"actionKill":[[0,0,0,NaN]]}', '{"actionKill":[[0,0,0,"1"]]}',
])
def test_unknown_duplicate_coerced_or_out_of_range_snapshot_fields_fail(raw):
    with pytest.raises(DomainError) as exc:
        codec.decode_snapshot(packed(raw=raw))
    assert exc.value.code == "INVALID_ROGUE_FINISH"


@pytest.mark.parametrize("damage", ["not-base64", "whitespace", "not-zip", "extra-entry", "prefix", "trailer", "crc", "bzip"])
def test_untrusted_archive_forms_fail_without_disk_extraction(damage):
    wire = snapshot([[0, 0, 0, 1]])
    if damage == "not-base64":
        wire = "*"
    elif damage == "whitespace":
        wire += "\n"
    elif damage == "not-zip":
        wire = base64.b64encode(b"json is not a zip").decode()
    elif damage == "extra-entry":
        wire = snapshot(extra=True)
    elif damage in ("prefix", "trailer"):
        raw = base64.b64decode(wire)
        raw = b"prefix" + raw if damage == "prefix" else raw + b"trailer"
        wire = base64.b64encode(raw).decode()
    elif damage == "crc":
        raw = bytearray(base64.b64decode(snapshot([[0, 0, 0, 1]], compression=zipfile.ZIP_STORED)))
        raw[30 + len("journal") + 3] ^= 1
        wire = base64.b64encode(raw).decode()
    else:
        wire = snapshot(compression=zipfile.ZIP_BZIP2)
    with pytest.raises(DomainError):
        codec.decode_snapshot(wire)


def test_declared_size_budget_rejects_zip_bomb_before_opening_member(monkeypatch):
    wire = packed(raw="x" * 1000)
    monkeypatch.setattr(codec, "MAX_SNAPSHOT_JSON", 500)
    def forbidden(*args, **kwargs):
        pytest.fail("Oversize member was opened")
    monkeypatch.setattr(zipfile.ZipFile, "open", forbidden)
    with pytest.raises(DomainError):
        codec.decode_snapshot(wire)


def test_row_total_and_wire_budgets_are_explicit_not_silent_truncation(monkeypatch):
    wire = snapshot([[0, 0, 0, 1], [0, 0, 1, 1]])
    monkeypatch.setattr(codec, "MAX_ACTION_ROWS", 1)
    with pytest.raises(DomainError):
        codec.decode_snapshot(wire)
    monkeypatch.setattr(codec, "MAX_ACTION_ROWS", 2)
    monkeypatch.setattr(codec, "MAX_DEATHS", 1)
    with pytest.raises(DomainError):
        codec.decode_snapshot(wire)
    monkeypatch.setattr(codec, "MAX_SNAPSHOT_WIRE", len(wire) - 1)
    with pytest.raises(DomainError):
        codec.decode_snapshot(wire)


@pytest.mark.parametrize("change", [{"battleLog": ""}, {"battleLog": 1}, {"rlv2Data": None},
    {"rlv2Data": {"battleSnapshot": "", "extra": 1}}, {"extra": 0}])
def test_outer_rogue_request_keeps_inherited_strictness(change):
    payload = request().model_dump() | change
    with pytest.raises(ValidationError):
        codec.RogueFinishRequest.model_validate(payload)
