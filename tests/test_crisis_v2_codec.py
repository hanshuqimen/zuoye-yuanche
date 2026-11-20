"""Authored encrypted submissions and ZIP logs, not captured player telemetry."""

import copy
import uuid
import zipfile

import pytest
from pydantic import ValidationError
from test_native_battle_finish import encoded
from test_native_replay import journal, packed

from terralocal.server.domain.errors import DomainError
from terralocal.server.protocol.battle_codec import FinishRequest, decode_finish
from terralocal.server.protocol.crisis_v2_codec import MAX_LOG_WIRE, CrisisFinishRequest, decode_submission
from terralocal.server.protocol.replay_codec import MAX_WIRE, decode_replay

STAGE = "authored_crisis_stage_not_in_normal_table"


def wire(*, rank=3, flags=None, stage=STAGE):
    battle_id = str(uuid.uuid4())
    data = encoded(battle_id, state=rank, changes={"stageId": stage, **(flags or {})})
    log = journal()
    log["journal"]["metadata"]["stageId"] = stage
    data["battleLog"] = packed(log)
    return battle_id, data


def test_inherited_body_and_native_zip_log_are_linked_without_normal_stage_lookup():
    ident, value = wire()
    source = copy.deepcopy(value)
    parsed = decode_submission(CrisisFinishRequest.model_validate(value), [1_800_000_000])
    assert parsed.facts.battleId == ident and parsed.facts.stageId == STAGE
    assert parsed.battle_log.stage_id == STAGE
    assert parsed.battle_log.encoded == value["battleLog"]
    assert parsed.battle_log.squad[0].operator_id == 1
    assert value == source


@pytest.mark.parametrize("rank", [1, 2, 3])
@pytest.mark.parametrize("flag", ["interrupt", "giveUp"])
def test_wire_decoder_preserves_rank_and_flags_without_classifying_a_clear(rank, flag):
    _, value = wire(rank=rank, flags={flag: True})
    parsed = decode_submission(CrisisFinishRequest.model_validate(value), [1_800_000_000])
    assert parsed.facts.completeState == rank and getattr(parsed.facts, flag) is True
    # No synthesized 'cleared' or reward/progression object comes from decoding.
    assert not hasattr(parsed, "cleared") and not hasattr(parsed, "rewards")
    if rank in {2, 3}:
        ordinary = {key: item for key, item in value.items() if key != "battleLog"}
        with pytest.raises(DomainError):
            decode_finish(FinishRequest.model_validate(ordinary), [1_800_000_000])


@pytest.mark.parametrize("missing", ["absent", None, ""])
def test_missing_log_stays_explicit_and_never_becomes_an_empty_successful_journal(missing):
    _, value = wire()
    if missing == "absent":
        value.pop("battleLog")
    else:
        value["battleLog"] = missing
    parsed = decode_submission(CrisisFinishRequest.model_validate(value), [1_800_000_000])
    assert parsed.battle_log is None and parsed.facts.completeState == 3


def test_log_from_another_stage_is_rejected_after_both_wire_layers_decode():
    _, value = wire()
    wrong = journal()
    wrong["journal"]["metadata"]["stageId"] = "other_authored_crisis_stage"
    value["battleLog"] = packed(wrong)
    with pytest.raises(DomainError) as failure:
        decode_submission(CrisisFinishRequest.model_validate(value), [1_800_000_000])
    assert failure.value.code == "CRISIS_V2_LOG_STAGE_CONFLICT" and failure.value.status == 409


@pytest.mark.parametrize("problem", ["invalid-base64", "two-entries", "duplicate-json", "expanded-size"])
def test_malformed_or_oversized_log_does_not_expose_telemetry(problem, monkeypatch):
    _, value = wire()
    if problem == "invalid-base64":
        value["battleLog"] = "AUTHORED-PRIVATE-LOG-DO-NOT-RETURN"
    elif problem == "two-entries":
        value["battleLog"] = packed(extra=True)
    elif problem == "duplicate-json":
        value["battleLog"] = packed(raw='{"journal":{},"journal":{}}')
    else:
        monkeypatch.setattr("terralocal.server.protocol.replay_codec.MAX_JSON", 32)
    with pytest.raises(DomainError) as failure:
        decode_submission(CrisisFinishRequest.model_validate(value), [1_800_000_000])
    assert failure.value.code == "INVALID_CRISIS_V2_LOG"
    assert "AUTHORED-PRIVATE-LOG" not in str(failure.value)
    assert failure.value.__suppress_context__


@pytest.mark.parametrize("value", [True, {}, "x" * (MAX_LOG_WIRE + 1)], ids=["boolean", "object", "oversize"])
def test_wire_log_type_and_length_are_bounded_before_decompression(value):
    _, body = wire()
    body["battleLog"] = value
    with pytest.raises(ValidationError):
        CrisisFinishRequest.model_validate(body)


def test_login_key_candidates_are_explicit_and_ciphertext_stays_out_of_fact_model():
    _, value = wire()
    request = CrisisFinishRequest.model_validate(value)
    with pytest.raises(DomainError):
        decode_submission(request, [1_800_000_001])
    parsed = decode_submission(request, [1_800_000_001, 1_800_000_000])
    assert parsed.facts.stageId == STAGE
    assert "data" not in parsed.facts.model_dump()
    assert "battleLog" not in parsed.facts.model_dump()


def test_mode_log_can_exceed_proxy_limit_without_widening_the_proxy_route():
    _, value = wire()
    log = journal()
    log["journal"]["metadata"]["stageId"] = STAGE
    log["journal"]["logs"] = ["x" * MAX_WIRE]
    value["battleLog"] = packed(log, compression=zipfile.ZIP_STORED)
    assert MAX_WIRE < len(value["battleLog"]) < MAX_LOG_WIRE
    with pytest.raises(DomainError):
        decode_replay(value["battleLog"])
    assert decode_submission(CrisisFinishRequest.model_validate(value), [1_800_000_000]).battle_log.stage_id == STAGE
