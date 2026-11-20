"""Versioned native finish encoding, verified on the owned CN 2.7.71 client.

The public client encoding is not an authentication mechanism. Authenticate the
game session and look up its owned battle before decoding. No decoded telemetry
is logged, stored in receipts, or used to set the server clock.
"""

import base64
import hashlib
import json
import uuid
from typing import Annotated, Any, Literal, TypeVar

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from pydantic import Field, field_validator

from terralocal.server.api.schemas import Command, Identifier
from terralocal.server.domain.errors import DomainError

# Historical protocol clue, subsequently verified against a real encrypted
# voluntary-abort request. Ordinary client code confirms CBC/PKCS7/IV suffix.
KEY_PREFIX = "pM6Umv*^hVQuB6t&"
StatKey = Annotated[str, Field(min_length=1, max_length=96)]
StatValue = Annotated[str, Field(max_length=16_384)]


class BattleDataRequest(Command):
    isCheat: str = Field(min_length=1, max_length=128)
    completeTime: int = Field(ge=0, le=86400)
    stats: dict[StatKey, StatValue] = Field(max_length=512)


class FinishRequest(Command):
    data: str = Field(min_length=64, max_length=1_000_000, pattern=r"^[0-9a-fA-F]+$")
    battleData: BattleDataRequest


class BattleTrace(Command):
    isCheat: str = Field(min_length=1, max_length=128)
    completeTime: int = Field(ge=0, le=86400)
    # BattleLogger.BattleStats is a nested structure, unlike the outer string
    # dictionary. Only its shape/total encrypted size are bounded here. None of
    # its access/package/hash/anti-cheat fields become domain state.
    stats: dict[StatKey, Any] = Field(max_length=512)


class DecodedFinish(Command):
    battleId: str = Field(min_length=36, max_length=36)
    stageId: Identifier
    completeState: Literal[1, 2, 3]
    interrupt: bool
    giveUp: bool
    percent: float = Field(ge=0, le=100, allow_inf_nan=False)
    killCnt: int = Field(ge=0, le=100_000)
    validKillCnt: int = Field(ge=0, le=100_000)
    platform: Literal[1]
    battleData: BattleTrace

    @field_validator("interrupt", "giveUp", mode="before")
    @classmethod
    def wire_boolean(cls, value):
        return bool(value) if type(value) is int and value in {0, 1} else value

    @field_validator("completeState", "platform", mode="before")
    @classmethod
    def integer_enum(cls, value):
        if type(value) is not int:
            raise ValueError("Expected an integer enum")
        return value


class DecodedCampaignFinish(DecodedFinish):
    """Same frozen payload fields, distinct campaign outcome semantics.

    A real voluntary campaign abort sends rank 2 with interrupt=1. Preserve
    that rank and both interruption flags; it is not an ordinary two-star
    clear and must never be passed to the ordinary settlement service.
    """


class DecodedRogueFinish(DecodedFinish):
    """Decoded facts only; rogue ranks are not ordinary stage stars.

    The domain must interpret defeat, retreat and pending rewards against the
    saved exploration. Decoding alone does not admit any outcome or reward.
    """


class DecodedCrisisFinish(DecodedFinish):
    """Inherited wire facts; Crisis V2 outcome admission belongs to its domain.

    In particular, retain interruption flags rather than treating ranks as
    ordinary stage stars or granting progress while decoding.
    """


Decoded = TypeVar("Decoded", bound=DecodedFinish)


def invalid_finish() -> DomainError:
    return DomainError("INVALID_NATIVE_FINISH", "战斗提交数据无效，尚未提交结算")


def signature_battle_id(signature: str) -> str:
    try:
        encoded = base64.b64decode(signature, validate=True)
        if base64.b64encode(encoded).decode("ascii") != signature:
            raise ValueError("Non-canonical signature")
        battle_id = bytes((value - 7) % 256 for value in encoded).decode("utf-8")
        if str(uuid.UUID(battle_id)) != battle_id:
            raise ValueError("Non-canonical battle ID")
        return battle_id
    except (ValueError, UnicodeError):
        raise invalid_finish() from None


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate field")
        result[key] = value
    return result


def nonfinite(_value):
    raise ValueError("Nonfinite JSON number")


def decode_finish(request: FinishRequest, login_times: list[int]) -> DecodedFinish:
    return _decode_finish(request, login_times, DecodedFinish, interrupted_ranks=frozenset({1}))


def decode_campaign_finish(request: FinishRequest, login_times: list[int]) -> DecodedCampaignFinish:
    """Decode owned campaign facts without interpreting rank as stage stars.

    Authentication and the owned, versioned battle lookup belong to the
    calling campaign service, as for decode_finish. This grants no rewards.
    """
    return _decode_finish(request, login_times, DecodedCampaignFinish, interrupted_ranks=frozenset({1, 2}))


def decode_rogue_payload(request: FinishRequest, login_times: list[int]) -> DecodedRogueFinish:
    """Preserve rogue outcome facts without applying ordinary/campaign rules.

    No settlement route calls this yet. Authentication, owned battle lookup
    and mode-specific outcome admission must precede any eventual domain write.
    """
    return _decode_finish(request, login_times, DecodedRogueFinish, interrupted_ranks=frozenset({1, 2, 3}))


def decode_crisis_payload(request: FinishRequest, login_times: list[int]) -> DecodedCrisisFinish:
    """Decode the common base without borrowing ordinary victory semantics.

    The frozen CrisisV2BattleFinishRequest inherits CommonFinishBattleRequest.
    Its additional battleLog is decoded separately, after the owned session
    lookup. No native route or reward operation is registered by this helper.
    """
    return _decode_finish(request, login_times, DecodedCrisisFinish, interrupted_ranks=frozenset({1, 2, 3}))


def _decode_finish(request: FinishRequest, login_times: list[int], decoded_type: type[Decoded], *,
                   interrupted_ranks: frozenset[int]) -> Decoded:
    battle_id = signature_battle_id(request.battleData.isCheat)
    if len(request.data) % 32:
        raise invalid_finish()
    encoded = bytes.fromhex(request.data)
    if len(encoded) < 32 or len(encoded) % 16:
        raise invalid_finish()
    # The start checkpoint also supports resubmitting an old request after a
    # new login. The current delivered flag supports the ordinary client when
    # another local login has changed its log key. Never brute-force timestamps.
    candidates = [value for value in login_times if type(value) is int and 0 <= value <= 253_402_271_999]
    for timestamp in dict.fromkeys(candidates):
        try:
            key = hashlib.md5((KEY_PREFIX + str(timestamp)).encode("utf-8"), usedforsecurity=False).digest()
            decoder = Cipher(algorithms.AES(key), modes.CBC(encoded[-16:])).decryptor()
            padded = decoder.update(encoded[:-16]) + decoder.finalize()
            unpadder = padding.PKCS7(128).unpadder()
            raw = (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")
            body = decoded_type.model_validate(json.loads(
                raw, object_pairs_hook=unique_object, parse_constant=nonfinite))
            if (body.battleId != battle_id or body.battleData.isCheat != request.battleData.isCheat
                    or body.battleData.completeTime != request.battleData.completeTime):
                raise ValueError("Mismatched battle data")
            if body.completeState not in interrupted_ranks and (body.interrupt or body.giveUp):
                raise ValueError("Interrupted success")
            return body
        except (ValueError, UnicodeError, RecursionError):
            continue
    raise invalid_finish()
