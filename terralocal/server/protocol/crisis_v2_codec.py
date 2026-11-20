"""Crisis V2's inherited finish payload and additional native BattleLog.

REA M101836 obtains a Journal, creates BattleLog with null battleLogMeta, then
calls the same CompressBattleLog used for the established native ZIP format.
Reusing its bounded in-memory decoder does not enable proxy play for this mode.
Authenticate and retrieve the owned version-bound battle before calling here.
"""

from dataclasses import dataclass

from pydantic import Field

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.replays import ReplayRecord
from terralocal.server.protocol.battle_codec import DecodedCrisisFinish, FinishRequest, decode_crisis_payload
from terralocal.server.protocol.replay_codec import decode_replay

# Local admission cap: leaves room for the encrypted base within the default
# 8 MiB HTTP body limit. It is not asserted as an official protocol maximum.
MAX_LOG_WIRE = 6 * 1024 * 1024


class CrisisFinishRequest(FinishRequest):
    # C# string can be absent/null/empty. Absence remains explicit; the domain
    # must decide whether a result has sufficient evidence to award anything.
    battleLog: str | None = Field(default=None, max_length=MAX_LOG_WIRE)


@dataclass(frozen=True)
class CrisisSubmission:
    facts: DecodedCrisisFinish
    battle_log: ReplayRecord | None


def decode_submission(request: CrisisFinishRequest, login_times: list[int]) -> CrisisSubmission:
    facts = decode_crisis_payload(request, login_times)
    record = None
    if request.battleLog:
        try:
            record = decode_replay(request.battleLog, max_wire=MAX_LOG_WIRE)
        except DomainError:
            # Do not expose decoded client telemetry or an exception's input.
            raise DomainError("INVALID_CRISIS_V2_LOG", "危机合约战斗日志格式无效，尚未提交结算") from None
        if record.stage_id != facts.stageId:
            raise DomainError("CRISIS_V2_LOG_STAGE_CONFLICT", "危机合约日志关卡与结算请求不一致", 409)
    return CrisisSubmission(facts, record)
