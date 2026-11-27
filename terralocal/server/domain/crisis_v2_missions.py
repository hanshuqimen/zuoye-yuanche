"""Atomic native mission batches and version-bound business receipts.

No reward values come from the request. A different batch containing an
already-claimed task is a conflict, never a second grant or partial success.
"""

import json
import sqlite3
from typing import Literal

from sqlalchemy import select

from terralocal.server.api.schemas import Command
from terralocal.server.domain import crisis_v2, crisis_v2_claims, crisis_v2_mission_rewards
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.persistence import models as m
from terralocal.server.protocol.crisis_v2_missions import ConfirmMissions, MissionResponse
from terralocal.server.protocol.crisis_v2_state import BasicMapInfo, Key, PermanentMapInfo, Timestamp

VERSION = "cn-2.7.71-crisis-v2-native-treasure-v1"
COIN_VERSION = "cn-2.7.71-crisis-v2-native-missions-v2"
PREFIX = "crisis-v2-native-missions:"
LOCAL_LEDGER = "crisis-v2-local-shop-ledger"


class ClaimReceipt(Command):
    version: Literal[VERSION, COIN_VERSION]
    account_id: int
    game_data_hash: str
    catalog_hash: str
    season_id: Key
    request: ConfirmMissions
    source_map: PermanentMapInfo | BasicMapInfo
    created_at: Timestamp
    response: MissionResponse
    hash: str


def _version(request):
    # Preserve every existing treasure-only digest and durable receipt.
    return COIN_VERSION if any(mission.type != 2 for mission in request.missions) else VERSION


def binding(data, request):
    return fingerprint(
        {
            "version": _version(request),
            "game_data_hash": data.manifest["hash"],
            "catalog_hash": data.crisis_v2.fingerprint,
            "request": request.canonical().model_dump(),
        }
    )


def _plan(data, season_id, request, source, at):
    entries = {}
    for mission in request.missions:
        rewards = (
            crisis_v2_claims.resolve(data, season_id, request.mapId, mission.id, source, at)
            if mission.type == 2
            else crisis_v2_mission_rewards.resolve(data, season_id, request.mapId, mission, source, at)
        )
        for reward in rewards:
            key = (reward["type"], reward["id"])
            entries[key] = entries.get(key, 0) + reward["count"]
    # Validate the entire batch before any grant, including expanded packs.
    return MissionResponse(
        rewards=[
            {"type": kind, "id": ident, "count": count} for (kind, ident), count in sorted(entries.items())
        ],
        ts=at,
    )


def _claimed(mission, current, source):
    if mission.type == 1:
        return current.challenge.get(mission.id) == 2
    if not isinstance(current, PermanentMapInfo) or not isinstance(source, PermanentMapInfo):
        return False
    if mission.type == 0:
        return current.runePack.get(mission.id) == 2
    return (
        mission.id in current.reward
        and current.reward[mission.id].state == 2
        and current.reward[mission.id].progress >= source.reward[mission.id].progress
    )


def coins(response):
    return sum(item.count for item in response.rewards if item.type == crisis_v2_mission_rewards.COIN)


def validate(data, account_id, record, current):
    receipt = ClaimReceipt.model_validate(record["result"])
    request = receipt.request
    try:
        expected = _plan(data, receipt.season_id, request, receipt.source_map, receipt.created_at)
    except DomainError as exc:
        raise ValueError("任务回执的首次领取资格或奖励不再匹配") from exc
    digest = binding(data, request)
    if (
        receipt.version != _version(request)
        or record["account_id"] != account_id
        or receipt.account_id != account_id
        or record["key"] != PREFIX + digest
        or record["request_hash"] != digest
        or record["created_at"] != receipt.created_at
        or receipt.game_data_hash != data.manifest["hash"]
        or receipt.catalog_hash != data.crisis_v2.fingerprint
        or request != request.canonical()
        or receipt.response != expected
        or receipt.hash != fingerprint(receipt.model_dump(exclude={"hash"}))
    ):
        raise ValueError("危机合约任务回执与账号、版本或奖励不一致")
    if (
        current is None
        or not current.state
        or any(not _claimed(mission, current, receipt.source_map) for mission in request.missions)
    ):
        raise ValueError("危机合约已发奖励缺少已领取任务纪录")
    return receipt.response


def coin_total(ctx):
    """Credits are derived from validated business receipts, never inventory."""
    total = 0
    ctx.session.flush()
    records = ctx.session.execute(
        select(m.Receipt.__table__).where(
            m.Receipt.account_id == ctx.account_id, m.Receipt.key.startswith(PREFIX)
        )
    )
    for record in records:
        saved = ClaimReceipt.model_validate(record.result)
        row = ctx.session.get(m.CrisisV2MapProgress, (ctx.account_id, saved.season_id, saved.request.mapId))
        image = crisis_v2._map(ctx, row) if row is not None else None
        total += coins(validate(ctx.data, ctx.account_id, dict(record._mapping), image))
    return total


def stored_coin_total(connection, account_id):
    """Read sealed credits after Crisis preflight has validated qualifications."""
    total = 0
    for (raw,) in connection.execute(
        "SELECT result FROM receipts WHERE account_id=? AND substr(key,1,?)=?",
        (account_id, len(PREFIX), PREFIX),
    ):
        receipt = ClaimReceipt.model_validate_json(raw)
        if receipt.hash != fingerprint(receipt.model_dump(exclude={"hash"})):
            raise ValueError("任务代币回执校验失败")
        total += coins(receipt.response)
    return total


def _preflight_coins(connection):
    from terralocal.server.domain.crisis_v2_native_shop import stored_spent_total

    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='crisis_v2_accounts'"
    ).fetchone():
        return
    for account_id, coin in connection.execute("SELECT account_id,shop_coin FROM crisis_v2_accounts"):
        local = connection.execute(
            "SELECT 1 FROM receipts WHERE account_id=? AND key=?", (account_id, LOCAL_LEDGER)
        ).fetchone()
        if not local and coin + stored_spent_total(connection, account_id) != stored_coin_total(
            connection, account_id
        ):
            raise ValueError("任务代币余额与已验证领取回执不一致")


def claim(ctx, request, *, shop=None):
    if not crisis_v2.available(ctx.data):
        raise DomainError("CRISIS_V2_NOT_CONFIGURED", "尚未导入匹配的危机合约信息源", 503)
    account = crisis_v2._account(ctx)
    digest = binding(ctx.data, request)
    old = ctx.session.get(m.Receipt, (ctx.account_id, PREFIX + digest))
    try:
        if old is not None:
            saved = ClaimReceipt.model_validate(old.result)
            row = ctx.session.get(m.CrisisV2MapProgress, (ctx.account_id, saved.season_id, request.mapId))
            image = crisis_v2._map(ctx, row) if row is not None else None
            return validate(
                ctx.data,
                ctx.account_id,
                {
                    key: getattr(old, key)
                    for key in ("account_id", "key", "request_hash", "created_at", "result")
                },
                image,
            ).model_dump()
        season_id = ctx.data.crisis_v2.current(ctx.now)
        if not season_id or account.current_season != season_id:
            raise DomainError("CRISIS_V2_CLAIM_CLOSED", "当前没有可领取的危机合约赛季", 409)
        if (season_id, request.mapId) not in ctx.data.crisis_v2.rules:
            raise DomainError("CRISIS_V2_CLAIM_MAP", "该赛季没有此地图", 404)
        row = ctx.session.get(m.CrisisV2MapProgress, (ctx.account_id, season_id, request.mapId))
        image = crisis_v2._map(ctx, row) if row is not None else None
        response = _plan(ctx.data, season_id, request, image, ctx.now)
        earned = coins(response)
        if _version(request) == COIN_VERSION:
            if shop is not None:
                from terralocal.server.domain.crisis_v2_shop import _state

                _state(ctx, shop)
            else:
                from terralocal.server.domain.crisis_v2_native_shop import spent_total

                if ctx.session.get(m.Receipt, (ctx.account_id, LOCAL_LEDGER)) is not None or (
                    account.shop_coin + spent_total(ctx) != coin_total(ctx)
                ):
                    raise ValueError("任务代币缺少匹配的余额账本")
            if account.shop_coin + earned > 2_000_000_000:
                raise DomainError("INVENTORY_LIMIT", "危机合约代币数量超出范围", 409)
        items = [
            item.model_dump() for item in response.rewards if item.type != crisis_v2_mission_rewards.COIN
        ]
        granted = ctx.rewards(items)
        if granted != items:
            raise ValueError("实际发奖与已验证任务奖励不一致")
        # The native shop balance consumer is proven. season.coin semantics
        # remain unresolved, so this adapter does not reinterpret that field.
        account.shop_coin += earned
        for mission in request.missions:
            if mission.type == 2:
                row.rewards = {
                    **row.rewards,
                    mission.id: {"state": 2, "progress": image.reward[mission.id].progress},
                }
            elif mission.type == 1:
                row.challenges = {**row.challenges, mission.id: 2}
            else:
                row.rune_packs = {**row.rune_packs, mission.id: 2}
        body = {
            "version": _version(request),
            "account_id": ctx.account_id,
            "game_data_hash": ctx.data.manifest["hash"],
            "catalog_hash": ctx.data.crisis_v2.fingerprint,
            "season_id": season_id,
            "request": request.model_dump(),
            "source_map": image.model_dump(),
            "created_at": ctx.now,
            "response": response.model_dump(),
        }
        record = {
            "account_id": ctx.account_id,
            "key": PREFIX + digest,
            "request_hash": digest,
            "created_at": ctx.now,
            "result": body | {"hash": fingerprint(body)},
        }
        validate(ctx.data, ctx.account_id, record, crisis_v2._map(ctx, row))
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise DomainError(
            "CRISIS_V2_MISSIONS_INCOMPATIBLE", "危机合约任务或回执未通过验证；本次修改已回滚", 503
        ) from exc
    ctx.session.add(m.Receipt(**record))
    return response.model_dump()


def preflight(connection, data):
    """Validate saved business receipts before a writable startup or restore."""
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='receipts'"
    ).fetchone():
        return
    records = connection.execute(
        "SELECT account_id,key,request_hash,result,created_at FROM receipts WHERE substr(key,1,?)=?",
        (len(PREFIX), PREFIX),
    ).fetchall()
    if not records:
        _preflight_coins(connection)
        return
    if not crisis_v2.available(data):
        raise ValueError("任务回执缺少已绑定的危机合约数据")
    try:
        for account_id, key, digest, raw, created_at in records:
            value = json.loads(raw)
            receipt = ClaimReceipt.model_validate(value)
            source = connection.execute(
                "SELECT rewards,cleared,challenges,rune_packs FROM crisis_v2_maps "
                "WHERE account_id=? AND season_id=? AND map_id=?",
                (account_id, receipt.season_id, receipt.request.mapId),
            ).fetchone()
            # Only the claimed task fields are monotonic; later legitimate
            # battles may improve all other map progress.
            if source is not None and source[1] not in (0, 1):
                raise ValueError("危机合约通关状态无效")
            current = None
            if source is not None:
                fields = {"state": source[1] == 1, "challenge": json.loads(source[2])}
                if isinstance(receipt.source_map, PermanentMapInfo):
                    fields.update(reward=json.loads(source[0]), runePack=json.loads(source[3]))
                current = type(receipt.source_map).model_validate(
                    {**receipt.source_map.model_dump(), **fields}
                )
            validate(
                data,
                account_id,
                {
                    "account_id": account_id,
                    "key": key,
                    "request_hash": digest,
                    "result": value,
                    "created_at": created_at,
                },
                current,
            )
        _preflight_coins(connection)
    except (sqlite3.DatabaseError, ValueError, TypeError, KeyError, AttributeError, DomainError) as exc:
        raise ValueError("危机合约任务回执不兼容；请保留原配置和存档") from exc
