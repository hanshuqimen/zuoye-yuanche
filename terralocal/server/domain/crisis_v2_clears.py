"""Atomic Crisis V2 clear records, separate from the native response adapter.

Record policy v1 retains each axis maximum and the first highest-total single
run, merges earned comments and preserves claimed objectives. These are explicit
local persistence rules, not a claim to have recovered the official backend's
record algorithm. The receipt contains selected counters and a journal digest;
it never archives the encrypted payload, unused telemetry or an original replay.
"""

from copy import deepcopy
from typing import Literal

from pydantic import Field

from terralocal.server.api.schemas import Command
from terralocal.server.domain import (
    crisis_v2,
    crisis_v2_battles,
    crisis_v2_clear,
    crisis_v2_exits,
    crisis_v2_objectives,
)
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.persistence import models as m
from terralocal.server.protocol.crisis_v2_battle import ScoreAxes
from terralocal.server.protocol.crisis_v2_counters import decode_counters, restore_counters
from terralocal.server.protocol.crisis_v2_state import (
    BasicMapInfo,
    Count,
    Key,
    PermanentMapInfo,
    Scores,
    Timestamp,
)

VERSION = "cn-2.7.71-crisis-v2-local-clear-receipt-v1"


class ClearResult(Command):
    battleId: str = Field(min_length=36, max_length=36)
    outcome: Literal["CLEARED"]
    mapId: Key
    finishedAt: Timestamp
    scoreCurrent: ScoreAxes
    axisRecordsBefore: Scores
    axisRecordsAfter: Scores
    singleRecordBefore: Scores | None
    singleRecordAfter: Scores | None
    newSingleRecord: bool
    earnedComments: list[Key]
    newComments: list[Key]
    previouslyEarnedComments: list[Key]
    completedRuneCountBefore: Count
    completedRuneCountAfter: Count
    objectives: dict


class Receipt(Command):
    version: Literal[VERSION]
    start_hash: crisis_v2_exits.Digest
    comments_hash: crisis_v2_exits.Digest
    objectives_hash: crisis_v2_exits.Digest
    journal_hash: crisis_v2_exits.Digest
    facts: crisis_v2_exits.FinishFacts
    counters: dict
    map_before: dict
    map_after: dict
    record_ts_before: Timestamp
    record_ts_after: Timestamp
    result: ClearResult
    hash: crisis_v2_exits.Digest


def request_hash(facts, counters):
    return fingerprint({"facts": facts.model_dump(), "counters": counters.canonical()})


def _map_image(catalog, key, value):
    permanent = key[1] == catalog.permanent[key[0]]
    schema = PermanentMapInfo if permanent else BasicMapInfo
    result = schema.model_validate(value).model_dump()
    rule = catalog.rules[key]
    references = (("rune", rule.nodes, lambda node: node.kind == "NORMAL"),
                  ("challenge", rule.nodes, lambda node: node.kind == "KEYPOINT"))
    if permanent:
        references += (("exRunes", rule.nodes, lambda node: node.kind == "NORMAL" and node.lockable),
                       ("runePack", rule.bags, lambda bag: True),
                       ("reward", rule.nodes, lambda node: node.kind == "TREASURE"))
        known = catalog.comments(*key).conditions
        if len(set(result["comment"])) != len(result["comment"]) or any(v not in known for v in result["comment"]):
            raise ValueError("危机合约纪录评语引用无效")
    if any(ident not in definitions or not predicate(definitions[ident])
           for field, definitions, predicate in references for ident in result[field]):
        raise ValueError("危机合约纪录地图引用无效")
    return result


def _completed(value):
    return len({k for field in ("rune", "exRunes") for k, state in value.get(field, {}).items() if state == 3})


def project(data, saved, parent, evaluation, facts, counters, before, record_ts, at):
    """Pure replay of the versioned policy, also used by readonly preflight."""
    if crisis_v2_exits.outcome(facts) != "CLEAR_CANDIDATE":
        raise ValueError("危机合约通关回执不能保存失败或退出结果")
    key = (saved["season_id"], saved["map_id"])
    catalog = data.crisis_v2
    before = _map_image(catalog, key, before)
    objectives = catalog.objectives(*key)
    qualified = objectives.evaluate(evaluation, cleared=True)
    professions = tuple(data.character(row["charId"])["profession"] for row in parent["squad_snapshot"])
    comments = catalog.comments(*key).evaluate(evaluation, counters, professions, cleared=True)
    if comments.unavailable:
        raise ValueError("危机合约通关回执缺少必要计数")
    after = crisis_v2_objectives.project(before, objectives, qualified, cleared=True)
    current = list(evaluation.dimension_scores)
    # The existing state protocol admits nonnegative records. Negative axes
    # require a separately verified state contract; never silently clamp them.
    if any(v < 0 for v in current):
        raise ValueError("危机合约负分纪录尚未适配保存合同")
    after["scoreTotal"] = [max(old, new) for old, new in zip(before["scoreTotal"], current, strict=True)]
    permanent = "scoreSingle" in before
    better = permanent and sum(current) > sum(before["scoreSingle"])
    new_comments = [ident for ident in comments.earned if ident not in before.get("comment", [])]
    if permanent:
        if better:
            after["scoreSingle"] = current
        after["comment"] += new_comments
    elif comments.earned:
        raise ValueError("临时地图评语尚未适配保存合同")
    after = _map_image(catalog, key, after)
    updated = better or after["scoreTotal"] != before["scoreTotal"]
    record_at = max(record_ts, at) if updated else record_ts
    result = ClearResult(battleId=parent["id"], outcome="CLEARED", mapId=key[1], finishedAt=at,
        scoreCurrent=current, axisRecordsBefore=before["scoreTotal"], axisRecordsAfter=after["scoreTotal"],
        singleRecordBefore=before.get("scoreSingle"), singleRecordAfter=after.get("scoreSingle"),
        newSingleRecord=better, earnedComments=list(comments.earned), newComments=new_comments,
        previouslyEarnedComments=[v for v in comments.earned if v not in new_comments],
        completedRuneCountBefore=_completed(before), completedRuneCountAfter=_completed(after),
        objectives=crisis_v2_objectives.summary(key[1], qualified))
    return after, record_at, result


def validate_terminal(data, parent, saved, evaluation):
    receipt = Receipt.model_validate(parent["settlement"])
    facts = receipt.facts
    counters = restore_counters(receipt.counters)
    key = (saved["season_id"], saved["map_id"])
    after, record_at, result = project(data, saved, parent, evaluation, facts, counters,
        receipt.map_before, receipt.record_ts_before, parent["finished_at"])
    if (parent["state"] != "FINISHED" or receipt.start_hash != saved["start_hash"]
            or facts.battleId != parent["id"] or facts.stageId != parent["stage_id"]
            or receipt.comments_hash != data.crisis_v2.comments(*key).fingerprint
            or receipt.objectives_hash != data.crisis_v2.objectives(*key).fingerprint
            or receipt.map_after != after or receipt.record_ts_after != record_at or receipt.result != result
            or parent["request_hash"] != request_hash(facts, counters)
            or receipt.hash != fingerprint(receipt.model_dump(exclude={"hash"}))):
        raise ValueError("危机合约通关回执、进度、结果或请求指纹不一致")


def finish(ctx, request):
    return finish_prepared(ctx, *crisis_v2_battles.prepare_finish(ctx, request))


def finish_prepared(ctx, pending, submission):
    """Internal participant after the common owned/versioned admission step."""
    facts = crisis_v2_exits.normalize(submission.facts)
    parent = pending.battle
    if parent.state != "STARTED":
        if parent.settlement.get("version") != VERSION:
            raise DomainError("CRISIS_V2_FINISH_CONFLICT", "此战斗已按其他结果结算", 409)
        # The first settlement fixes the codec. Replaying old receipts must not
        # reinterpret fields that their original decoder deliberately ignored.
        counters = decode_counters(submission.facts.battleData.stats, codec=parent.settlement["counters"]["codec"])
        if parent.request_hash != request_hash(facts, counters):
            raise DomainError("CRISIS_V2_FINISH_CONFLICT", "危机合约战斗已按不同结果或计数结算", 409)
        return deepcopy(parent.settlement["result"])
    inputs = crisis_v2_clear.admit(ctx.data, pending, submission)
    key = (pending.crisis.season_id, pending.crisis.map_id)
    row = ctx.session.get(m.CrisisV2MapProgress, (ctx.account_id, *key))
    account = crisis_v2._account(ctx)
    try:
        before = crisis_v2._map(ctx, row).model_dump()
        after, record_at, result = project(ctx.data, crisis_v2_battles._values(pending.crisis),
            crisis_v2_battles._values(parent), pending.evaluation, facts, inputs.counters,
            before, account.new_record_ts, ctx.now)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise DomainError("CRISIS_V2_CLEAR_UNSUPPORTED", "危机合约地图纪录或通关条件尚未完成适配", 503) from exc
    body = {"version": VERSION, "start_hash": pending.crisis.start_hash,
        "comments_hash": ctx.data.crisis_v2.comments(*key).fingerprint,
        "objectives_hash": ctx.data.crisis_v2.objectives(*key).fingerprint,
        "journal_hash": inputs.journal_hash, "facts": facts.model_dump(), "counters": inputs.counters.canonical(),
        "map_before": before, "map_after": after, "record_ts_before": account.new_record_ts,
        "record_ts_after": record_at, "result": result.model_dump()}
    # Validate the complete candidate before applying any row mutations.
    candidate = crisis_v2_battles._values(parent) | {"state": "FINISHED", "finished_at": ctx.now,
        "request_hash": request_hash(facts, inputs.counters), "settlement": body | {"hash": fingerprint(body)}}
    validate_terminal(ctx.data, candidate, crisis_v2_battles._values(pending.crisis), pending.evaluation)
    crisis_v2_objectives.apply(row, after)
    account.new_record_ts = record_at
    for field in ("state", "finished_at", "request_hash", "settlement"):
        setattr(parent, field, candidate[field])
    return deepcopy(result.model_dump())
