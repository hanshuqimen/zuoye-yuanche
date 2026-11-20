"""Versioned non-clear Crisis V2 receipts; clear settlement remains separate.

The common native rank producer distinguishes FAIL=1 from PASS=2/COMPLETE=3.
Flags take precedence under this local admission policy. Positive ranks do not
authorize progression here: comments, records and rewards must first be wired
into the same transaction. Neither ciphertext nor telemetry is archived.
"""

from copy import deepcopy
from typing import Annotated, Literal

from pydantic import Field

from terralocal.server.api.schemas import Command, Identifier
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.protocol.crisis_v2_state import Timestamp

VERSION = "cn-2.7.71-crisis-v2-exit-receipt-v1"
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Exit = Literal["FAILED", "ABORTED"]


class FinishFacts(Command):
    battleId: str = Field(min_length=36, max_length=36)
    stageId: Identifier
    rank: int = Field(ge=1, le=3)
    interrupt: bool
    giveUp: bool
    percent: float = Field(ge=0, le=100, allow_inf_nan=False)
    kills: int = Field(ge=0, le=100_000)
    validKills: int = Field(ge=0, le=100_000)
    duration: int = Field(ge=0, le=86400)


class ExitResult(Command):
    battleId: str = Field(min_length=36, max_length=36)
    outcome: Exit
    finishedAt: Timestamp


class Receipt(Command):
    version: Literal[VERSION]
    start_hash: Digest
    facts: FinishFacts
    result: ExitResult
    hash: Digest


def normalize(facts):
    return FinishFacts(battleId=facts.battleId, stageId=facts.stageId, rank=facts.completeState,
        interrupt=facts.interrupt, giveUp=facts.giveUp, percent=facts.percent, kills=facts.killCnt,
        validKills=facts.validKillCnt, duration=facts.battleData.completeTime)


def outcome(facts: FinishFacts):
    if facts.interrupt or facts.giveUp:
        return "ABORTED"
    return "FAILED" if facts.rank == 1 else "CLEAR_CANDIDATE"


def _result(facts, at):
    kind = outcome(facts)
    if kind == "CLEAR_CANDIDATE":
        raise DomainError("CRISIS_V2_CLEAR_UNSUPPORTED", "危机合约通关结算尚未完成；待结算战斗已保留", 501)
    return ExitResult(battleId=facts.battleId, outcome=kind, finishedAt=at)


def validate_terminal(parent, saved):
    """Startup/restore integrity check, after the immutable start is verified."""
    if parent["state"] == "STARTED":
        if any(parent[field] is not None for field in ("finished_at", "request_hash", "settlement")):
            raise ValueError("危机合约待结算战斗混入终态字段")
        return
    if parent["state"] not in {"FINISHED", "ABORTED"}:
        raise ValueError("危机合约战斗终态尚未适配")
    receipt = Receipt.model_validate(parent["settlement"])
    facts = receipt.facts
    if outcome(facts) == "CLEAR_CANDIDATE":
        raise ValueError("危机合约通关不得冒充无奖励退出回执")
    expected = _result(facts, parent["finished_at"])
    body = receipt.model_dump(exclude={"hash"})
    if (receipt.start_hash != saved["start_hash"] or facts.battleId != parent["id"]
            or facts.stageId != parent["stage_id"] or receipt.result != expected
            or parent["state"] != ("ABORTED" if expected.outcome == "ABORTED" else "FINISHED")
            or parent["request_hash"] != fingerprint(facts.model_dump()) or receipt.hash != fingerprint(body)):
        raise ValueError("危机合约退出回执、终态或请求指纹不一致")


def finish(ctx, request):
    from terralocal.server.domain import crisis_v2_battles

    bound, submission = crisis_v2_battles.prepare_finish(ctx, request)
    facts = normalize(submission.facts)
    digest = fingerprint(facts.model_dump())
    parent = bound.battle
    if parent.state != "STARTED":
        if parent.request_hash != digest:
            raise DomainError("CRISIS_V2_FINISH_CONFLICT", "危机合约战斗已按不同结果结算", 409)
        return deepcopy(parent.settlement["result"])
    result = _result(facts, ctx.now)
    body = {"version": VERSION, "start_hash": bound.crisis.start_hash,
        "facts": facts.model_dump(), "result": result.model_dump()}
    parent.finished_at, parent.request_hash = ctx.now, digest
    parent.state = "ABORTED" if result.outcome == "ABORTED" else "FINISHED"
    parent.settlement = body | {"hash": fingerprint(body)}
    validate_terminal(crisis_v2_battles._values(parent), crisis_v2_battles._values(bound.crisis))
    return deepcopy(parent.settlement["result"])
