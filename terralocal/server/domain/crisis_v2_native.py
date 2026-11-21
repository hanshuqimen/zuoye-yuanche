"""Frozen-client adapter and per-battle first-response receipt.

Wire field consumers are REA-backed; record/display choices follow the explicit
local record policy. A failed run displays its selected challenge score without
awarding it. No original replay or telemetry enters this response cache.
"""

from typing import Literal

from terralocal.server.api.schemas import Command
from terralocal.server.domain import crisis_v2, crisis_v2_battles, crisis_v2_clears, crisis_v2_exits
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.persistence import models as m
from terralocal.server.protocol.crisis_v2_battle import FinishResponse
from terralocal.server.protocol.crisis_v2_state import Timestamp

VERSION = "cn-2.7.71-crisis-v2-native-finish-v1"
PREFIX = "crisis-v2-native-finish:"


class NativeReceipt(Command):
    version: Literal[VERSION]
    start_hash: crisis_v2_exits.Digest
    settlement_hash: crisis_v2_exits.Digest
    created_at: Timestamp
    source_map: dict | None
    response: FinishResponse
    hash: crisis_v2_exits.Digest


def _binding(parent, saved):
    return fingerprint({"version": VERSION, "battle_id": parent["id"], "start_hash": saved["start_hash"],
                        "settlement_hash": parent["settlement"]["hash"]})


def _runes(data, saved, evaluation):
    detail = data.crisis_v2.info(saved["season_id"])["mapDetailDataMap"][saved["map_id"]]
    result = []
    for ident in evaluation.rune_slots:
        rune_id = detail["nodeDataMap"][ident]["runeId"]
        if not isinstance(rune_id, str) or rune_id not in detail["runeDataMap"]:
            raise ValueError("危机合约结算符文引用未适配")
        rune = detail["runeDataMap"][rune_id]
        # Native PackedRuneData.id (field 29443, +0x10), also used by the
        # settle-item predicate. There is no `key` alias in this contract.
        if not isinstance(rune.get("packedRune"), dict) or rune["packedRune"].get("id") != rune_id:
            raise ValueError("危机合约结算缺少与开战匹配的符文效果")
        result.append(rune_id)
    return result


def project(data, parent, saved, evaluation, source_map):
    settlement = parent["settlement"]
    if parent["state"] == "STARTED" or settlement is None:
        raise ValueError("待结算战斗不能生成原生结算回执")
    if settlement["version"] == crisis_v2_clears.VERSION:
        if source_map is not None:
            raise ValueError("通关响应应使用固定的通关纪录")
        result = crisis_v2_clears.ClearResult.model_validate(settlement["result"])
        before, current = result.axisRecordsBefore, result.scoreCurrent
        improved = result.newSingleRecord or result.axisRecordsAfter != before
        comments_new, comments_old = result.newComments, result.previouslyEarnedComments
        counts = [result.completedRuneCountBefore, result.completedRuneCountAfter]
    elif settlement["version"] == crisis_v2_exits.VERSION:
        before_map = crisis_v2_clears._map_image(data.crisis_v2, (saved["season_id"], saved["map_id"]), source_map)
        before, current = before_map["scoreTotal"], list(evaluation.dimension_scores)
        improved, comments_new, comments_old = False, [], []
        completed = crisis_v2_clears._completed(before_map)
        counts = [completed, completed]
    else:
        raise ValueError("危机合约结算回执版本尚未适配")
    return FinishResponse(mapId=saved["map_id"], scoreRecord=before, scoreCurrent=current,
        isNewRecord=improved, commentNew=comments_new, commentOld=comments_old, runeCount=counts,
        ts=parent["finished_at"], runeIds=_runes(data, saved, evaluation))


def validate(data, parent, saved, evaluation, record):
    receipt = NativeReceipt.model_validate(record["result"])
    expected = project(data, parent, saved, evaluation, receipt.source_map)
    if (record["account_id"] != parent["account_id"] or record["key"] != PREFIX + parent["id"]
            or record["request_hash"] != _binding(parent, saved) or record["created_at"] != receipt.created_at
            or receipt.start_hash != saved["start_hash"] or receipt.settlement_hash != parent["settlement"]["hash"]
            or receipt.response != expected or receipt.hash != fingerprint(receipt.model_dump(exclude={"hash"}))):
        raise ValueError("危机合约原生响应回执与所属战斗不一致")
    return receipt.response


def finish(ctx, request):
    pending, submission = crisis_v2_battles.prepare_finish(ctx, request)
    facts = crisis_v2_exits.normalize(submission.facts)
    if crisis_v2_exits.outcome(facts) == "CLEAR_CANDIDATE":
        crisis_v2_clears.finish_prepared(ctx, pending, submission)
    else:
        crisis_v2_exits.finish_prepared(ctx, pending, submission)
    parent, saved = crisis_v2_battles._values(pending.battle), crisis_v2_battles._values(pending.crisis)
    old = ctx.session.get(m.Receipt, (ctx.account_id, PREFIX + parent["id"]))
    try:
        if old is not None:
            return validate(ctx.data, parent, saved, pending.evaluation,
                            {key: getattr(old, key) for key in ("account_id", "key", "request_hash", "result", "created_at")}).model_dump()
        source_map = None
        if parent["settlement"]["version"] == crisis_v2_exits.VERSION:
            row = ctx.session.get(m.CrisisV2MapProgress, (ctx.account_id, saved["season_id"], saved["map_id"]))
            source_map = crisis_v2._map(ctx, row).model_dump()
        response = project(ctx.data, parent, saved, pending.evaluation, source_map)
        body = {"version": VERSION, "start_hash": saved["start_hash"], "settlement_hash": parent["settlement"]["hash"],
                "created_at": ctx.now, "source_map": source_map, "response": response.model_dump()}
        record = {"account_id": ctx.account_id, "key": PREFIX + parent["id"], "request_hash": _binding(parent, saved),
                  "created_at": ctx.now, "result": body | {"hash": fingerprint(body)}}
        validate(ctx.data, parent, saved, pending.evaluation, record)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise DomainError("CRISIS_V2_RESPONSE_UNSUPPORTED", "危机合约原生响应或保存尚未完成适配；本次修改已回滚", 503) from exc
    ctx.session.add(m.Receipt(**record))
    return response.model_dump()
