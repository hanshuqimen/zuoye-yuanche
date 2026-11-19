"""Modern standard/kernel draws, shared pity and immutable special selections."""

import random
import secrets
from dataclasses import dataclass

from sqlalchemy import func, select

from terralocal.server.domain.acquisitions import acquire_standard
from terralocal.server.domain.errors import DomainError, NotImplementedFeature
from terralocal.server.domain.headhunting_payments import charge
from terralocal.server.persistence import models as m

POLICY = "TERRALOCAL_MODERN_HEADHUNTING_V1"


@dataclass
class SingleGuarantee:
    target: str
    misses: int = 0
    used: bool = False

    @property
    def pending(self):
        return self.misses == 150 and not self.used

    def record(self, rarity, char_id):
        if self.used:
            return
        if self.pending and rarity == 5:
            if char_id != self.target:
                raise DomainError("INVALID_HEADHUNTING_STATE", "定向选调后的首个六星与本期目标不符", 503)
            self.used = True
        self.misses = 0 if char_id == self.target else min(self.misses + 1, 150)


def require_pool(ctx, pool_id):
    pool = ctx.data.headhunting.pools.get(pool_id)
    if pool is None:
        if pool_id in ctx.data.headhunting.normal:
            raise NotImplementedFeature("此寻访卡池的完整名单与规则")
        raise DomainError("UNKNOWN_GACHA_POOL", "寻访卡池不在当前版本中", 404)
    if not pool["start"] <= ctx.now <= pool["end"]:
        raise DomainError("GACHA_POOL_CLOSED", "寻访尚未开放或已经结束", 409)
    return pool


def validate_banner(ctx, pool_id, pool, banner):
    if (banner.rules_hash != pool["hash"] or type(banner.total_pulls) is not int
            or not 0 <= banner.total_pulls < 2_000_000_000
            or type(banner.double_guarantees) is not int or banner.double_guarantees not in {0, 1, 2}):
        raise DomainError("HEADHUNTING_VERSION_MISMATCH", "卡池存档缺少匹配的寻访规则", 503)
    history = list(ctx.session.scalars(select(m.GachaHistory).where(
        m.GachaHistory.account_id == ctx.account_id, m.GachaHistory.banner_id == pool_id)
        .order_by(m.GachaHistory.id)))
    characters = pool["characters"]
    selected = banner.selected_up
    if pool["rule_type"] == "SPECIAL" and selected is not None:
        validate_selection(pool, selected)
        characters = {**characters, 5: selected["5"]}
    guarantee = pool["first_guarantee"]
    if (len(history) != banner.total_pulls or any(
            row.char_id not in characters.get(row.rarity, []) for row in history)
            or banner.guarantee_used != any(row.rarity >= 4 for row in history)
            or guarantee is not None and len(history) >= guarantee
            and not any(row.rarity >= 4 for row in history[:guarantee])):
        raise DomainError("INVALID_HEADHUNTING_STATE", "寻访历史与计数或首轮五星保底不一致", 503)
    if pool["rule_type"] == "SINGLE":
        if banner.selected_up is not None or banner.double_guarantees or banner.first_target is not None:
            raise DomainError("INVALID_HEADHUNTING_STATE", "定向选调存档含有其他卡池的选择", 503)
        progress = SingleGuarantee(pool["up"][5][0])
        for row in history:
            progress.record(row.rarity, row.char_id)
        return progress
    if pool["rule_type"] == "SPECIAL":
        if history and not selected or banner.double_guarantees or banner.first_target:
            raise DomainError("INVALID_HEADHUNTING_STATE", "甄选历史缺少对应选择", 503)
    else:
        forced = [row.char_id for index, row in enumerate(history, 1) if index > 150 and row.rarity == 5]
        first = forced[0] if forced else None
        # The second guarantee is the first six-star after both the first
        # guarantee and draw 300. Natural earlier UP results do not consume it.
        first_index = next((i for i, row in enumerate(history, 1) if i > 150 and row.rarity == 5), None)
        second = next((row.char_id for i, row in enumerate(history, 1)
                       if i > 300 and first_index is not None and i > first_index and row.rarity == 5), None)
        expected = int(first is not None) + int(second is not None)
        if (banner.selected_up or banner.double_guarantees != expected or banner.first_target != first
                or first is not None and first not in pool["up"][5]
                or second is not None and second not in set(pool["up"][5]) - {first}):
            raise DomainError("INVALID_HEADHUNTING_STATE", "选调状态与历史不一致", 503)


def banner_state(ctx, pool_id, pool):
    legacy = ctx.session.get(m.GachaPity, (ctx.account_id, pool_id))
    if legacy is not None and legacy.total_pulls:
        raise DomainError("ACQUISITION_HISTORY_INCOMPLETE", "旧卡池进度缺少跨池保底依据", 503)
    banner = ctx.session.get(m.HeadHuntingBanner, (ctx.account_id, pool_id))
    if banner is None:
        banner = m.HeadHuntingBanner(account_id=ctx.account_id, pool_id=pool_id, rules_hash=pool["hash"])
        ctx.session.add(banner)
        ctx.session.flush()
    return banner, validate_banner(ctx, pool_id, pool, banner)


def validate_selection(pool, selected):
    if not isinstance(selected, dict) or set(selected) != {"4", "5"}:
        raise DomainError("INVALID_GACHA_SELECTION", "须分别选择三名五星和三名六星干员")
    candidates = pool["definition"]["dynMeta"]["rarityPickCharDict"]
    for rarity in (4, 5):
        ids = selected[str(rarity)]
        if (not isinstance(ids, list) or len(ids) != 3 or any(not isinstance(v, str) for v in ids)
                or len(set(ids)) != 3 or not set(ids) <= set(candidates[f"TIER_{rarity + 1}"])):
            raise DomainError("INVALID_GACHA_SELECTION", "甄选包含重复、越界或数量不符的干员")


def choose(ctx, pool_id: str, selected: dict) -> dict:
    pool = require_pool(ctx, pool_id)
    if pool["rule_type"] != "SPECIAL":
        raise DomainError("INVALID_GACHA_SELECTION", "此卡池不能自选概率提升干员")
    validate_selection(pool, selected)
    selection = {k: sorted(v) for k, v in selected.items()}
    banner, _ = banner_state(ctx, pool_id, pool)
    if banner.selected_up is not None:
        if banner.selected_up == selection:
            return {}
        raise DomainError("GACHA_SELECTION_LOCKED", "本期已锁定的干员不能变更", 409)
    if banner.total_pulls:
        raise DomainError("INVALID_HEADHUNTING_STATE", "开始寻访后不能补选概率提升干员", 503)
    banner.selected_up = selection
    ctx.emit("HeadHuntingSelected", pool_id=pool_id, selected_up=selection)
    return {}


def group_state(ctx, pool):
    group = pool["group"]
    state = ctx.session.get(m.GachaPity, (ctx.account_id, group))
    if state is None:
        state = m.GachaPity(account_id=ctx.account_id, group_id=group, seed=secrets.randbits(63),
                            policy_version=POLICY, gamedata_hash=ctx.data.manifest["hash"])
        ctx.session.add(state)
        ctx.session.flush()
    if (state.policy_version != POLICY or state.gamedata_hash != ctx.data.manifest["hash"]
            or type(state.seed) is not int or not 0 <= state.seed < 2**63
            or type(state.total_pulls) is not int or not 0 <= state.total_pulls < 2_000_000_000
            or state.rng_counter != state.total_pulls
            or type(state.pulls_without_six) is not int or not 0 <= state.pulls_without_six <= 98):
        raise DomainError("HEADHUNTING_VERSION_MISMATCH", "跨池保底的规则或随机计数非法", 503)
    banners = ctx.rows(m.HeadHuntingBanner)
    pools = ctx.data.headhunting.pools
    if any(b.pool_id not in pools or b.rules_hash != pools[b.pool_id]["hash"] for b in banners):
        raise DomainError("HEADHUNTING_VERSION_MISMATCH", "已抽卡池不在当前寻访快照中", 503)
    ids = [pid for pid, definition in pools.items() if definition["group"] == group]
    query = select(m.GachaHistory.id).where(m.GachaHistory.account_id == ctx.account_id,
                                           m.GachaHistory.banner_id.in_(ids))
    count = ctx.session.scalar(select(func.count()).select_from(query.subquery()))
    last_six = ctx.session.scalar(query.where(m.GachaHistory.rarity == 5).order_by(
        m.GachaHistory.id.desc()).limit(1))
    trailing = (ctx.session.scalar(select(func.count()).select_from(
        query.where(m.GachaHistory.id > last_six).subquery())) if last_six is not None else count)
    if (count != state.total_pulls or trailing != state.pulls_without_six
            or sum(b.total_pulls for b in banners if pools[b.pool_id]["group"] == group) != count):
        raise DomainError("INVALID_HEADHUNTING_STATE", "跨池保底与寻访历史不一致", 503)
    return state


def six_rate(without_six: int) -> int:
    return min(10000, 200 + max(0, without_six - 49) * 200)


def roll_rarity(rng, without_six: int) -> int:
    if rng.randrange(10000) < six_rate(without_six):
        return 5
    return rng.choices([2, 3, 4], weights=[4000, 5000, 800], k=1)[0]


def draw(ctx, pool_id: str, mode: int, count: int, item_id=None, items=None) -> dict:
    pool = require_pool(ctx, pool_id)
    if count not in {1, 10}:
        raise DomainError("INVALID_GACHA_COUNT", "寻访次数必须为一次或十次")
    banner, single = banner_state(ctx, pool_id, pool)
    if pool["rule_type"] == "SPECIAL" and banner.selected_up is None:
        raise DomainError("GACHA_SELECTION_REQUIRED", "请先锁定概率提升的干员", 409)
    state = group_state(ctx, pool)
    if state.total_pulls + count >= 2_000_000_000 or banner.total_pulls + count >= 2_000_000_000:
        raise DomainError("HEADHUNTING_LIMIT", "寻访计数超出范围")
    charge(ctx, count, mode, classic=pool["group"] == "CLASSIC",
           price=pool["price"], item_id=item_id, items=items)
    results = []
    for _ in range(count):
        rng = random.Random(f"{POLICY}:{state.gamedata_hash}:{pool['group']}:{state.seed}:{state.rng_counter}")
        rarity = roll_rarity(rng, state.pulls_without_six)
        if banner.total_pulls + 1 == pool["first_guarantee"] and not banner.guarantee_used and rarity < 4:
            rarity = 4
        if pool["rule_type"] == "SPECIAL" and rarity in {4, 5}:
            up = banner.selected_up[str(rarity)]
            rate = 10000 if rarity == 5 else 6000
        else:
            up, rate = pool["up"].get(rarity, []), pool["up_rates"].get(rarity, 0)
        forced = (rarity == 5 and pool["rule_type"] in {"DOUBLE", "CLASSIC_DOUBLE"}
                  and (banner.double_guarantees == 0 and banner.total_pulls >= 150
                       or banner.double_guarantees == 1 and banner.total_pulls >= 300))
        if single is not None and single.pending and rarity == 5:
            char_id = single.target
        elif forced:
            available = [c for c in up if c != banner.first_target]
            char_id = rng.choice(available)
        elif up and rng.randrange(10000) < rate:
            char_id = rng.choice(up)
        else:
            available = [c for c in pool["characters"][rarity] if c not in up]
            char_id = rng.choice(available)
        if single is not None:
            single.record(rarity, char_id)
        if pool["group"] == "CLASSIC":
            from terralocal.server.domain.acquisitions import acquire_classic

            result = acquire_classic(ctx, char_id)
        else:
            result = acquire_standard(ctx, char_id)
        if forced:
            if banner.double_guarantees == 0:
                banner.first_target = char_id
            banner.double_guarantees += 1
        results.append(result)
        ctx.session.add(m.GachaHistory(account_id=ctx.account_id, banner_id=pool_id, char_id=char_id,
                                        rarity=rarity, is_new=result["isNew"], drawn_at=ctx.now))
        ctx.emit("HeadHuntCompleted", pool_id=pool_id, char_id=char_id, group=pool["group"])
        banner.total_pulls += 1
        banner.guarantee_used = banner.guarantee_used or rarity >= 4
        state.total_pulls += 1
        state.rng_counter += 1
        state.pulls_without_six = 0 if rarity == 5 else state.pulls_without_six + 1
    return {"charGet": results[0]} if count == 1 else {"gachaResultList": results}
