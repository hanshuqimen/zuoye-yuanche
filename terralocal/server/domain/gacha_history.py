"""Read-only, account-scoped headhunting records with stable keyset pagination.

The frozen WebView treats category IDs and `pos` as opaque. Category grouping
is a local display policy based on GameData rule types; positions use durable
history row IDs. Public recruitment belongs to a different game system.
"""

from sqlalchemy import and_, or_, select

from terralocal.server.domain.clock import MAX_TIMESTAMP, ServerClock
from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence import models as m

PAGE_SIZE = 10
HISTORY_WINDOW = 90 * 86400
CATEGORIES = {"standard": "标准寻访", "limited": "限定寻访", "classic": "中坚寻访", "archived": "历史寻访"}
RULE_CATEGORIES = {
    "NORMAL": "standard", "SINGLE": "standard", "DOUBLE": "standard", "SPECIAL": "standard",
    "ATTAIN": "standard", "BACKFLOW": "standard", "LIMITED": "limited", "LINKAGE": "limited",
    "CLASSIC": "classic", "FESCLASSIC": "classic", "CLASSIC_ATTAIN": "classic", "CLASSIC_DOUBLE": "classic",
}


def catalogue(data) -> dict[str, tuple[str, str]]:
    table = data.table("gacha_table")
    pools = {}
    for key, newcomer in (("gachaPoolClient", False), ("newbeeGachaPoolClient", True)):
        for row in table.get(key, []):
            pool_id = row["gachaPoolId"]
            category = "standard" if newcomer else RULE_CATEGORIES.get(row.get("gachaRuleType"), "archived")
            name = row.get("gachaPoolName") or pool_id
            pools[pool_id] = (category, name)
    return pools


def categories(session, data, account_id: int, pool_id: str | None) -> list[dict]:
    pools = catalogue(data)
    owned = set(session.scalars(select(m.GachaHistory.banner_id).where(
        m.GachaHistory.account_id == account_id, m.GachaHistory.banner_id != "RECRUIT").distinct()))
    available = {category for category, _ in pools.values()}
    if owned - pools.keys():
        available.add("archived")
    if pool_id is not None and pool_id not in pools and pool_id not in owned:
        raise DomainError("UNKNOWN_GACHA_POOL", "寻访卡池不在当前版本或本账号历史中", 404)
    active = pools.get(pool_id, ("archived", ""))[0] if pool_id else (
        next((key for key in CATEGORIES if key in available), None))
    return [{"id": key, "name": name, "active": key == active}
            for key, name in CATEGORIES.items() if key in available]


def _scope(account_id, category, pools):
    matched = [key for key, (kind, _) in pools.items() if kind == category]
    belongs = m.GachaHistory.banner_id.in_(matched)
    if category == "archived":
        belongs = or_(belongs, m.GachaHistory.banner_id.not_in(list(pools)))
    return (m.GachaHistory.account_id == account_id, m.GachaHistory.banner_id != "RECRUIT", belongs)


def history(session, data, account_id: int, category: str,
            gacha_ts: int | None = None, position: int | None = None) -> dict:
    if category not in CATEGORIES:
        raise DomainError("INVALID_GACHA_CATEGORY", "寻访记录分组不存在")
    if (gacha_ts is None) != (position is None):
        raise DomainError("INVALID_GACHA_CURSOR", "寻访记录游标必须同时包含时间和位置")
    pools = catalogue(data)
    scope = _scope(account_id, category, pools)
    # The original page advertises 90 days. Hide older valid records without
    # deleting saved draw truth, and never conceal corrupt records as empty success.
    corrupt = session.scalar(select(m.GachaHistory.id).where(*scope, or_(
        m.GachaHistory.rarity < 0, m.GachaHistory.rarity > 5, m.GachaHistory.drawn_at < 0,
        m.GachaHistory.drawn_at > MAX_TIMESTAMP, m.GachaHistory.id < 1)).limit(1))
    if corrupt is not None:
        raise DomainError("INVALID_GACHA_HISTORY", "本地寻访记录的稀有度、时间或位置非法", 503)
    clock = session.get(m.ServerClockState, 1)
    if clock is None:
        raise DomainError("INVALID_CLOCK_STATE", "服务器时间尚未准备", 503)
    cutoff = max(0, ServerClock(clock).now() - HISTORY_WINDOW)
    query = select(m.GachaHistory).where(*scope, m.GachaHistory.drawn_at >= cutoff)
    if gacha_ts is not None:
        if not 0 <= gacha_ts <= 2**63 - 1 or gacha_ts % 1000 or not 1 <= position <= 2**63 - 1:
            raise DomainError("INVALID_GACHA_CURSOR", "寻访记录游标无效")
        cursor = session.scalar(select(m.GachaHistory).where(*scope, m.GachaHistory.id == position))
        if cursor is None or cursor.drawn_at * 1000 != gacha_ts:
            raise DomainError("INVALID_GACHA_CURSOR", "寻访记录游标与本账号分组或时间不匹配")
        seconds = gacha_ts // 1000
        query = query.where(or_(m.GachaHistory.drawn_at < seconds, and_(
            m.GachaHistory.drawn_at == seconds, m.GachaHistory.id < position)))
    rows = list(session.scalars(query.order_by(m.GachaHistory.drawn_at.desc(), m.GachaHistory.id.desc())
                               .limit(PAGE_SIZE + 1)))
    records = []
    for row in rows[:PAGE_SIZE]:
        if (not 0 <= row.rarity <= 5 or not 0 <= row.drawn_at <= MAX_TIMESTAMP or row.id < 1):
            raise DomainError("INVALID_GACHA_HISTORY", "本地寻访记录的稀有度、时间或位置非法", 503)
        character = data.characters.get(row.char_id, {})
        records.append({"poolName": pools.get(row.banner_id, ("archived", row.banner_id))[1],
                        "charName": character.get("name") or row.char_id, "rarity": row.rarity,
                        "isNew": row.is_new, "gachaTs": str(row.drawn_at * 1000), "pos": str(row.id)})
    return {"list": records, "hasMore": len(rows) > PAGE_SIZE}
