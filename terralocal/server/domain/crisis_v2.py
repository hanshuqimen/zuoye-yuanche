"""Account/season/map records for Crisis V2 information and sync.

Fresh local progression is empty/zero, never copied from a captured player.
Calendar reconciliation changes the current view and preserves prior seasons.
Battle, challenge, unlock and reward transactions are separate operations.
"""

import sqlite3
from contextlib import closing

from pydantic import ValidationError

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.crisis_v2_catalog import POLICY, SERVER_TABLE
from terralocal.server.persistence import models as m
from terralocal.server.protocol.crisis_v2_state import (
    BasicMapInfo,
    CrisisV2State,
    PermanentMapInfo,
    SeasonState,
    ShopState,
    SocialInfo,
)


def available(data):
    return data is not None and SERVER_TABLE in data.manifest["tables"]


def preflight(data, path):
    from terralocal.server.persistence.migrations import CRISIS_V2_REVISION, REVISION

    catalog = data.crisis_v2 if available(data) else None
    if not path.exists():
        return
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        expected = {"crisis_v2_accounts", "crisis_v2_seasons", "crisis_v2_maps"}
        present = tables & expected
        has_battles = "crisis_v2_battles" in tables
        revisions = (connection.execute("SELECT version_num FROM alembic_version").fetchall()
                     if "alembic_version" in tables else [])
        # An older save without this feature can migrate additively. A current
        # or partially damaged save must fail before any writable initialization.
        if ((present and present != expected) or (has_battles and present != expected)
                or (not present and any((version,) in revisions for version in (CRISIS_V2_REVISION, REVISION)))
                or ((REVISION,) in revisions and not has_battles)):
            raise ValueError("危机合约存档表不完整；请保留原存档并从已验证备份恢复")
        if not present:
            return
        rows = connection.execute("SELECT gamedata_hash,catalog_hash,policy_version FROM crisis_v2_accounts").fetchall()
        for digest, binding, policy in rows:
            if (catalog is None or digest != data.manifest["hash"] or binding != catalog.fingerprint or policy != POLICY):
                raise ValueError("危机合约保存绑定了其他数据或信息源；请保留原配置和存档")
        if has_battles:
            from terralocal.server.domain.crisis_v2_battles import preflight as preflight_battles

            preflight_battles(connection, data)


def _account(ctx):
    row = ctx.session.get(m.CrisisV2Account, ctx.account_id)
    catalog = ctx.data.crisis_v2
    if (row is None or row.gamedata_hash != ctx.data.manifest["hash"]
            or row.catalog_hash != catalog.fingerprint or row.policy_version != POLICY):
        raise DomainError("CRISIS_V2_STATE_INCOMPATIBLE", "危机合约存档未初始化或版本不匹配", 503)
    return row


def initialize(ctx):
    if not available(ctx.data):
        return False
    catalog = ctx.data.crisis_v2
    # Resolve before any insertion. A missing active source must roll back,
    # not become a fabricated empty season or an automatic unlock.
    current = catalog.current(ctx.now)
    refresh = catalog.next_refresh(ctx.now)
    account = ctx.session.get(m.CrisisV2Account, ctx.account_id)
    changed = account is None
    if account is None:
        account = m.CrisisV2Account(account_id=ctx.account_id, gamedata_hash=ctx.data.manifest["hash"],
            catalog_hash=catalog.fingerprint, policy_version=POLICY, current_season="", initialized_at=ctx.now)
        ctx.session.add(account)
        ctx.session.flush()
    _account(ctx)
    if current and ctx.session.get(m.CrisisV2Season, (ctx.account_id, current)) is None:
        ctx.session.add(m.CrisisV2Season(account_id=ctx.account_id, season_id=current))
        ctx.session.flush()
        maps = [(catalog.permanent[current], "PERMANENT"),
                *((key, "TEMPORARY") for key in catalog.temporary[current])]
        for map_id, kind in maps:
            rule = catalog.rules[(current, map_id)]
            ctx.session.add(m.CrisisV2MapProgress(account_id=ctx.account_id, season_id=current, map_id=map_id,
                kind=kind, rewards={key: {"state": 0, "progress": 0}
                                    for key, node in rule.nodes.items()
                                    if kind == "PERMANENT" and node.kind == "TREASURE"}))
        changed = True
    if account.current_season != current or account.next_refresh_ts != refresh:
        account.current_season, account.next_refresh_ts = current, refresh
        changed = True
    ctx.session.flush()
    return changed


def _map(ctx, row):
    catalog = ctx.data.crisis_v2
    rules = catalog.rules.get((row.season_id, row.map_id))
    if rules is None:
        raise DomainError("CRISIS_V2_STATE_INCOMPATIBLE", "危机合约纪录引用未知地图", 503)
    if (any(k not in rules.nodes or rules.nodes[k].kind != "NORMAL" for k in row.runes)
            or any(k not in rules.nodes or rules.nodes[k].kind != "KEYPOINT" for k in row.challenges)
            or any(k not in rules.nodes or not rules.nodes[k].lockable for k in row.extra_runes)
            or any(k not in rules.bags for k in row.rune_packs)
            or any(k not in rules.nodes or rules.nodes[k].kind != "TREASURE" for k in row.rewards)):
        raise DomainError("CRISIS_V2_STATE_INCOMPATIBLE", "危机合约进度引用与地图不匹配", 503)
    values = {"state": row.cleared, "scoreTotal": row.score_total, "rune": row.runes, "challenge": row.challenges}
    permanent = row.map_id == catalog.permanent[row.season_id]
    if row.kind != ("PERMANENT" if permanent else "TEMPORARY"):
        raise DomainError("CRISIS_V2_STATE_INCOMPATIBLE", "危机合约地图类别与保存不匹配", 503)
    if permanent:
        return PermanentMapInfo(**values, scoreSingle=row.score_single, comment=row.comments,
            exRunes=row.extra_runes, runePack=row.rune_packs, reward=row.rewards)
    if row.extra_runes or row.rune_packs or row.rewards or row.comments or row.score_single != [0] * 6:
        raise DomainError("CRISIS_V2_STATE_INCOMPATIBLE", "危机合约临时地图混入永久地图专用进度", 503)
    return BasicMapInfo(**values)


def snapshot(ctx):
    account = _account(ctx)
    catalog = ctx.data.crisis_v2
    maps = {(row.season_id, row.map_id): row for row in ctx.read_rows(m.CrisisV2MapProgress)}
    seasons = {}
    try:
        for row in ctx.read_rows(m.CrisisV2Season):
            if row.season_id not in catalog.permanent:
                raise DomainError("CRISIS_V2_STATE_INCOMPATIBLE", "危机合约赛季信息源缺失", 503)
            expected = {catalog.permanent[row.season_id], *catalog.temporary[row.season_id]}
            actual = {key for season, key in maps if season == row.season_id}
            if expected != actual:
                raise DomainError("CRISIS_V2_STATE_INCOMPATIBLE", "危机合约赛季地图纪录不完整", 503)
            seasons[row.season_id] = SeasonState(coin=row.coin,
                permanent=_map(ctx, maps[(row.season_id, catalog.permanent[row.season_id])]),
                temporary={key: _map(ctx, maps[(row.season_id, key)]) for key in catalog.temporary[row.season_id]},
                social=SocialInfo(assistCnt=row.assist_count, maxPnt=row.assist_max_points, chars=row.assist_chars))
        if account.current_season and account.current_season not in seasons:
            raise DomainError("CRISIS_V2_STATE_INCOMPATIBLE", "危机合约当前赛季未初始化", 503)
        return CrisisV2State(currentSeason=account.current_season, seasons=seasons,
            shop=ShopState(coin=account.shop_coin, info=account.shop_info, progressInfo=account.shop_progress),
            newRecordTs=account.new_record_ts, nextRefreshTs=account.next_refresh_ts).model_dump(by_alias=True)
    except (ValidationError, TypeError) as exc:
        raise DomainError("CRISIS_V2_STATE_INCOMPATIBLE", "危机合约保存字段不符合已绑定协议", 503) from exc


def get_info(ctx):
    if not available(ctx.data):
        raise DomainError("CRISIS_V2_NOT_CONFIGURED", "尚未导入匹配的危机合约信息源", 503)
    initialize(ctx)
    state = snapshot(ctx)
    return {"info": ctx.data.crisis_v2.info(state["current"])}
