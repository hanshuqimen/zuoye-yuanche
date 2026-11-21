"""Read-only complete inputs for the eventual atomic clear transaction."""

from dataclasses import dataclass

from terralocal.server.domain import crisis_v2_battles, crisis_v2_exits
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.crisis_v2_comments import CommentResult
from terralocal.server.protocol.crisis_v2_counters import CounterFacts, decode_counters


@dataclass(frozen=True)
class ClearInputs:
    bound: crisis_v2_battles.PendingBattle
    facts: crisis_v2_exits.FinishFacts
    counters: CounterFacts
    comments: CommentResult
    journal_hash: str


def prepare(ctx, request):
    bound, submission = crisis_v2_battles.prepare_finish(ctx, request)
    return admit(ctx.data, bound, submission)


def admit(data, bound, submission):
    if bound.battle.state != "STARTED":
        raise DomainError("CRISIS_V2_BATTLE_ALREADY_FINISHED", "已结束战斗不能重新写入通关进度", 409)
    facts = crisis_v2_exits.normalize(submission.facts)
    if crisis_v2_exits.outcome(facts) != "CLEAR_CANDIDATE":
        raise DomainError("CRISIS_V2_NOT_A_CLEAR", "此请求不是危机合约通关结果")
    if submission.battle_log is None:
        raise DomainError("CRISIS_V2_LOG_REQUIRED", "通关结算需要与开战编队匹配的战斗记录")
    try:
        rules = data.crisis_v2.comments(bound.crisis.season_id, bound.crisis.map_id)
        professions = tuple(data.character(row["charId"])["profession"] for row in bound.battle.squad_snapshot)
    except (ValueError, TypeError, KeyError) as exc:
        raise DomainError("CRISIS_V2_COMMENTS_UNSUPPORTED", "危机合约评语定义或编队职业尚未完成适配", 503) from exc
    counters = decode_counters(submission.facts.battleData.stats)
    try:
        comments = rules.evaluate(bound.evaluation, counters, professions, cleared=True)
    except (ValueError, TypeError, KeyError) as exc:
        raise DomainError("CRISIS_V2_COMMENTS_UNSUPPORTED", "危机合约评语输入与当前地图不一致", 503) from exc
    if comments.unavailable:
        raise DomainError("CRISIS_V2_COUNTERS_REQUIRED", "战斗记录缺少本次评语所需的计数，尚未提交通关结算")
    return ClearInputs(bound, facts, counters, comments, submission.battle_log.sha256)
