"""Atomic native treasure batches and version-bound business receipts.

No reward values come from the request. A different batch containing an
already-claimed task is a conflict, never a second grant or partial success.
"""

import json
import sqlite3
from typing import Literal

from terralocal.server.api.schemas import Command
from terralocal.server.domain import crisis_v2, crisis_v2_claims
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.persistence import models as m
from terralocal.server.protocol.crisis_v2_missions import ConfirmMissions, MissionResponse
from terralocal.server.protocol.crisis_v2_state import Key, PermanentMapInfo, Timestamp

VERSION = "cn-2.7.71-crisis-v2-native-treasure-v1"
PREFIX = "crisis-v2-native-missions:"


class ClaimReceipt(Command):
    version: Literal[VERSION]
    account_id: int
    game_data_hash: str
    catalog_hash: str
    season_id: Key
    request: ConfirmMissions
    source_map: PermanentMapInfo
    created_at: Timestamp
    response: MissionResponse
    hash: str


def binding(data, request):
    return fingerprint(
        {
            "version": VERSION,
            "game_data_hash": data.manifest["hash"],
            "catalog_hash": data.crisis_v2.fingerprint,
            "request": request.canonical().model_dump(),
        }
    )


def _plan(data, season_id, request, source, at):
    entries = {}
    for mission in request.missions:
        if mission.type != 2:
            raise DomainError("CRISIS_V2_MISSION_UNSUPPORTED", "符文组和挑战代币领奖尚未完成适配", 501)
        for reward in crisis_v2_claims.resolve(data, season_id, request.mapId, mission.id, source, at):
            key = (reward["type"], reward["id"])
            entries[key] = entries.get(key, 0) + reward["count"]
    # Validate the entire batch before any grant, including expanded packs.
    return MissionResponse(
        rewards=[
            {"type": kind, "id": ident, "count": count} for (kind, ident), count in sorted(entries.items())
        ],
        ts=at,
    )


def validate(data, account_id, record, current):
    receipt = ClaimReceipt.model_validate(record["result"])
    request = receipt.request
    try:
        expected = _plan(data, receipt.season_id, request, receipt.source_map, receipt.created_at)
    except DomainError as exc:
        raise ValueError("任务回执的首次领取资格或奖励不再匹配") from exc
    digest = binding(data, request)
    if (
        record["account_id"] != account_id
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
        or any(
            mission.id not in current.reward
            or current.reward[mission.id].state != 2
            or current.reward[mission.id].progress < receipt.source_map.reward[mission.id].progress
            for mission in request.missions
        )
    ):
        raise ValueError("危机合约已发奖励缺少已领取任务纪录")
    return receipt.response


def claim(ctx, request):
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
        if ctx.data.crisis_v2.permanent.get(season_id) != request.mapId:
            raise DomainError("CRISIS_V2_CLAIM_MAP", "该赛季没有已适配的永久地图领奖", 404)
        row = ctx.session.get(m.CrisisV2MapProgress, (ctx.account_id, season_id, request.mapId))
        image = crisis_v2._map(ctx, row) if row is not None else None
        response = _plan(ctx.data, season_id, request, image, ctx.now)
        granted = ctx.rewards([item.model_dump() for item in response.rewards])
        if granted != [item.model_dump() for item in response.rewards]:
            raise ValueError("实际发奖与已验证任务奖励不一致")
        row.rewards = {
            **row.rewards,
            **{
                mission.id: {"state": 2, "progress": image.reward[mission.id].progress}
                for mission in request.missions
            },
        }
        body = {
            "version": VERSION,
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
        return
    if not crisis_v2.available(data):
        raise ValueError("任务回执缺少已绑定的危机合约数据")
    try:
        for account_id, key, digest, raw, created_at in records:
            value = json.loads(raw)
            receipt = ClaimReceipt.model_validate(value)
            source = connection.execute(
                "SELECT rewards,cleared FROM crisis_v2_maps WHERE account_id=? AND season_id=? AND map_id=?",
                (account_id, receipt.season_id, receipt.request.mapId),
            ).fetchone()
            # Only the claimed task fields are monotonic; later legitimate
            # battles may improve all other map progress.
            if source is not None and source[1] not in (0, 1):
                raise ValueError("危机合约通关状态无效")
            current = (
                PermanentMapInfo.model_validate(
                    {
                        **receipt.source_map.model_dump(),
                        "reward": json.loads(source[0]),
                        "state": source[1] == 1,
                    }
                )
                if source is not None
                else None
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
    except (sqlite3.DatabaseError, ValueError, TypeError, KeyError, AttributeError, DomainError) as exc:
        raise ValueError("危机合约任务回执不兼容；请保留原配置和存档") from exc
