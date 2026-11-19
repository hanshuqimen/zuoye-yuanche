"""Frozen modern topic preferences and the admitted base initialization flow."""

from copy import deepcopy
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import Field, field_validator

from terralocal.server.api.schemas import Command, Identifier, SquadSlot
from terralocal.server.domain import (
    rogue_battle,
    rogue_map_drafts,
    rogue_recruit,
    rogue_runs,
    rogue_settlement,
    rogue_topics,
)
from terralocal.server.domain.errors import DomainError
from terralocal.server.protocol.rogue_battle_codec import RogueFinishRequest

EXP_VIEW_KEY = "_terralocal_rogue_exp_view"
EXP_VIEW_VERSION = "in-level-v1"


class PinTopic(Command):
    id: str | None = Field(max_length=128)


class CreateGame(Command):
    theme: str = Field(min_length=1, max_length=128)
    mode: Literal["EASY", "NORMAL", "HARD", "MONTH_TEAM", "CHALLENGE", 1, 2, 3, 5, 6]
    modeGrade: int = Field(ge=0, le=2**31 - 1)
    predefinedId: str | None = Field(default=None, max_length=128)
    activityId: str | None = Field(default=None, max_length=128)

    @field_validator("mode", mode="before")
    @classmethod
    def mode_type(cls, value):
        if type(value) not in (str, int):
            raise ValueError("mode 必须为明确的枚举字符串或整数")
        return value


class SelectInitial(Command):
    select: str = Field(min_length=1, max_length=128)


class TicketId(Command):
    id: str = Field(min_length=1, max_length=128)


class RecruitChar(Command):
    ticketIndex: str = Field(min_length=1, max_length=128)
    optionId: str = Field(min_length=1, max_length=128)


class NodePosition(Command):
    x: int = Field(ge=0, lt=32)
    y: int = Field(ge=0, lt=8)


class MoveTo(Command):
    to: NodePosition


class SelectChoice(Command):
    choice: Identifier


class ShopAction(Command):
    """Observed modern request; rewards and prices remain server-owned."""

    buy: list[Identifier] = Field(max_length=32)
    recycle: list[Identifier] = Field(max_length=32)
    leave: int = Field(ge=0, le=1)


class RogueSquad(Command):
    squadId: str | None = Field(default=None, max_length=16)
    name: str | None = Field(default=None, max_length=64)
    slots: list[SquadSlot | None] = Field(min_length=1, max_length=12)


class StartBattle(Command):
    to: NodePosition | None
    stageId: Identifier
    squad: RogueSquad


class ChooseBattleReward(Command):
    index: int = Field(ge=0, le=255)
    sub: int = Field(ge=0, le=255)


def legacy_response(data, envelope):
    """Adapt known old wire contracts without editing immutable receipts.

    M152771 copies property.exp straight into currExp; M152772/152529 display
    that against the next level's individual cost. Older receipts stored the
    cumulative value. New receipts carry an internal version so an already
    converted remainder cannot be mistaken for a cumulative value on retry.
    """
    result = deepcopy(envelope)
    versioned = EXP_VIEW_KEY in result
    version = result.pop(EXP_VIEW_KEY, None)
    if versioned and version != EXP_VIEW_VERSION:
        raise DomainError("ROGUE_EXP_VIEW_INCOMPATIBLE", "探索收据的经验投影版本不匹配；请保留原存档", 503)
    if not rogue_topics.available(data):
        return result
    reserves = {char for rule in data.rogue_recruit.catalog.values() for char in rule.reserves}

    def character(value):
        if (isinstance(value, dict) and value.get("type") == "THIRD_LOW"
                and value.get("voiceLan", "missing") is None and value.get("charId") in reserves
                and rogue_recruit.unvoiced(data, value["charId"])):
            value["voiceLan"] = "NONE"

    for value in result.get("chars", []):
        character(value)
    current = result.get("playerDataDelta", {}).get("modified", {}).get("rlv2", {}).get("current", {}) or {}
    properties = (current.get("player") or {}).get("property")
    if not versioned and isinstance(properties, dict) and "exp" in properties:
        properties["exp"] = rogue_runs.wire_exp(data, properties["exp"])
    # The native default loader reserves zone0 for the empty initialization
    # model. Adapt only the original memberless initial handoff receipt; keep
    # its immutable stored bytes and transaction outcome unchanged.
    zones = (current.get("map") or {}).get("zones")
    if ((current.get("player") or {}).get("state") == "WAIT_MOVE" and isinstance(zones, dict)
            and set(zones) == {"0"} and isinstance(zones["0"], dict) and zones["0"].get("id") == "zone_1"):
        current["map"]["zones"] = {"1": zones["0"]}
        current["player"]["cursor"] = {"zone": 1, "position": None}
        deleted = result["playerDataDelta"].setdefault("deleted", {})
        for name in ("rlv2", "current", "map", "zones"):
            deleted = deleted.setdefault(name, {})
        deleted["0"] = 1
    # Ending/abandoning a run explicitly clears these reference-type members.
    for ticket in (current.get("inventory") or {}).get("recruit", {}).values():
        for value in ticket.get("list", []):
            character(value)
        character(ticket.get("result"))
    for value in (current.get("troop") or {}).get("chars", {}).values():
        character(value)
    return result


def router(runtime):
    api = APIRouter()

    def bank_key(ctx, request, operation):
        from terralocal.server.gamedata.repository import fingerprint

        key = request.headers.get("idempotency-key") or request.headers.get("seqnum", "")
        return f"{operation}:{ctx.local_session.id}:" + fingerprint({"key": key})

    def mutate(request, payload, operation, action):
        from terralocal.server.main import credentials

        def versioned_action(ctx):
            return {**action(ctx), EXP_VIEW_KEY: EXP_VIEW_VERSION}

        envelope = runtime.mutate(*credentials(request),
            request.headers.get("idempotency-key") or request.headers.get("seqnum", ""),
            operation, payload.model_dump(), versioned_action)
        return legacy_response(runtime.require_data(), envelope)

    @api.post("/rlv2/setPinned")
    def pin_topic(payload: PinTopic, request: Request):
        from terralocal.server.main import credentials

        return runtime.mutate(*credentials(request),
            request.headers.get("idempotency-key") or request.headers.get("seqnum", ""),
            "rogue-topic-pin", payload.model_dump(), lambda ctx: rogue_topics.pin(ctx, payload.id))

    @api.post("/rlv2/createGame")
    def create_game(payload: CreateGame, request: Request):
        mode = {1: "EASY", 2: "NORMAL", 3: "HARD", 5: "MONTH_TEAM", 6: "CHALLENGE"}.get(
            payload.mode, payload.mode)
        return mutate(request, payload, "rogue-create", lambda ctx: rogue_runs.create(
            ctx, payload.theme, mode, payload.modeGrade, payload.predefinedId, payload.activityId))

    @api.post("/rlv2/chooseInitialRelic")
    def choose_relic(payload: SelectInitial, request: Request):
        return mutate(request, payload, "rogue-initial-relic", lambda ctx: rogue_runs.choose_band(ctx, payload.select))

    @api.post("/rlv2/chooseInitialRecruitSet")
    def choose_group(payload: SelectInitial, request: Request):
        return mutate(request, payload, "rogue-initial-group", lambda ctx: rogue_runs.choose_group(ctx, payload.select))

    @api.post("/rlv2/giveUpGame")
    def give_up(payload: Command, request: Request):
        return mutate(request, payload, "rogue-give-up", rogue_runs.abandon)

    @api.post("/rlv2/chooseInitialRecruit")
    def initial_recruit(payload: SelectInitial, request: Request):
        return mutate(request, payload, "rogue-initial-recruit", lambda ctx:
                      rogue_recruit.activate(ctx, payload.select) | {"items": []})

    @api.post("/rlv2/activeRecruitTicket")
    def activate_ticket(payload: TicketId, request: Request):
        return mutate(request, payload, "rogue-activate-ticket", lambda ctx: rogue_recruit.activate(ctx, payload.id))

    @api.post("/rlv2/recruitChar")
    def recruit(payload: RecruitChar, request: Request):
        return mutate(request, payload, "rogue-recruit-char", lambda ctx: rogue_recruit.recruit(
            ctx, payload.ticketIndex, payload.optionId))

    @api.post("/rlv2/closeRecruitTicket")
    def close_ticket(payload: TicketId, request: Request):
        return mutate(request, payload, "rogue-close-ticket", lambda ctx: rogue_recruit.close(ctx, payload.id))

    @api.post("/rlv2/finishEvent")
    def finish_event(payload: Command, request: Request):
        return mutate(request, payload, "rogue-finish-initial", rogue_map_drafts.finish_initial)

    @api.post("/rlv2/moveTo")
    def move_to(payload: MoveTo, request: Request):
        from terralocal.server.domain.rogue_visits import move

        return mutate(request, payload, "rogue-move-to-scene", lambda ctx: move(ctx, payload.to.model_dump()))

    @api.post("/rlv2/selectChoice")
    def select_choice(payload: SelectChoice, request: Request):
        from terralocal.server.domain.rogue_visits import choose

        return mutate(request, payload, "rogue-select-choice", lambda ctx: choose(ctx, payload.choice))

    @api.post("/rlv2/shopAction")
    def shop_action(payload: ShopAction, request: Request):
        from terralocal.server.domain.rogue_shops import action

        return mutate(request, payload, "rogue-shop-action", lambda ctx:
                      action(ctx, payload.buy, payload.recycle, payload.leave,
                             bank_key=bank_key(ctx, request, "shop")))

    @api.post("/rlv2/bankPut")
    def bank_put(payload: Command, request: Request):
        from terralocal.server.domain.rogue_banks import action

        return mutate(request, payload, "rogue-bank-put", lambda ctx:
                      action(ctx, "PUT", bank_key(ctx, request, "put")))

    @api.post("/rlv2/bankWithdraw")
    def bank_withdraw(payload: Command, request: Request):
        from terralocal.server.domain.rogue_banks import action

        return mutate(request, payload, "rogue-bank-withdraw", lambda ctx:
                      action(ctx, "WITHDRAW", bank_key(ctx, request, "withdraw")))

    @api.post("/rlv2/moveAndBattleStart")
    def start_battle(payload: StartBattle, request: Request):
        return mutate(request, payload, "rogue-battle-start", lambda ctx: rogue_battle.start(
            ctx, payload.to.model_dump() if payload.to else None, payload.stageId,
            [slot.model_dump() if slot else None for slot in payload.squad.slots]))

    @api.post("/rlv2/battleFinish")
    def finish_battle(payload: RogueFinishRequest, request: Request):
        return mutate(request, payload, "rogue-battle-finish", lambda ctx: rogue_settlement.finish(ctx, payload))

    @api.post("/rlv2/chooseBattleReward")
    def choose_battle_reward(payload: ChooseBattleReward, request: Request):
        return mutate(request, payload, "rogue-battle-reward", lambda ctx:
                      rogue_settlement.claim(ctx, payload.index, payload.sub))

    @api.post("/rlv2/finishBattleReward")
    def close_battle_reward(payload: Command, request: Request):
        return mutate(request, payload, "rogue-battle-reward-close", rogue_settlement.close)

    @api.post("/rlv2/gameSettle")
    def game_settle(payload: Command, request: Request):
        from terralocal.server.domain.rogue_ending import settle

        return mutate(request, payload, "rogue-game-settle", settle)

    return api
