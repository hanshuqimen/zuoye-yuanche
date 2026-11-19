"""Account-scoped newcomer draws and views, distinct from public recruitment.

Static rates and the first-ten six-star guarantee follow the frozen client.
The seeded draw policy is locally implemented and versioned, not official RNG.
"""

import random
import secrets
from copy import deepcopy

from sqlalchemy import select

from terralocal.server.domain.acquisitions import acquire_standard
from terralocal.server.domain.errors import DomainError, NotImplementedFeature
from terralocal.server.persistence import models as m

POLICY = "TERRALOCAL_BOOT_V1"


def pool_detail(ctx, pool_id: str, group_type: int) -> dict:
    """Use the same frozen roster/rates as the draw, with no save mutation.

    GetDetailGachaResponse is not a PlayerDeltaResponse. In particular, viewing
    the list must not spend a draw or reset an exhausted newcomer's progress.
    """
    catalog = ctx.data.headhunting
    if pool_id in catalog.pools:
        pool = catalog.pools[pool_id]
        valid_groups = {0, 3, 4} if pool["rule_type"] == "SPECIAL" else {0}
        if type(group_type) is not int or group_type not in valid_groups:
            raise DomainError("INVALID_GACHA_GROUP", "寻访详情分组与卡池类型不匹配")
        response = deepcopy(pool["detail"])
        response["gachaObjGroupType"] = group_type
        # The public catalog includes server-side group ranges. This frozen
        # client has no gachaObjGroups field and renders every supplied object;
        # send only the requested range rather than both pre/post-selection UI.
        info = response["detailInfo"]
        groups = info.pop("gachaObjGroups", [])
        if group_type:
            group = next((g for g in groups if g["groupType"] == group_type), None)
            if group is None:
                raise DomainError("INVALID_HEADHUNTING_DATA", "寻访详情缺少匹配的显示分组", 503)
            info["gachaObjList"] = info["gachaObjList"][group["startIndex"]:group["endIndex"]]
        if pool["rule_type"] == "SPECIAL":
            from terralocal.server.domain.standard_headhunting import validate_selection

            banner = ctx.session.get(m.HeadHuntingBanner, (ctx.account_id, pool_id))
            selected = banner.selected_up if banner else None
            if group_type == 4 and selected is None:
                raise DomainError("GACHA_SELECTION_REQUIRED", "请先锁定概率提升的干员", 409)
            if selected is not None and group_type != 3:
                validate_selection(pool, selected)
                info = response["detailInfo"]
                for entry in info["availCharInfo"]["perAvailList"]:
                    if entry["rarityRank"] == 5:
                        entry["charIdList"] = list(selected["5"])
                info["upCharInfo"]["perCharList"] = [
                    {"rarityRank": rarity, "charIdList": list(selected[str(rarity)]),
                     "percent": (1 if rarity == 5 else .6) / 3, "count": 3}
                    for rarity in (5, 4)]
        return response
    if pool_id not in catalog.newcomer:
        if pool_id in catalog.normal:
            raise DomainError("GACHA_DETAIL_NOT_READY", "当前卡池缺少匹配版本的完整寻访名单和规则", 503)
        raise DomainError("UNKNOWN_GACHA_POOL", "寻访卡池不在当前版本中", 404)
    if type(group_type) is not int or group_type != 0:
        raise DomainError("INVALID_GACHA_GROUP", "新手寻访只支持全部干员详情")
    pool = catalog.newcomer[pool_id]
    return {"detailInfo": {
        "availCharInfo": {"perAvailList": [
            {"rarityRank": rarity, "charIdList": list(pool["characters"][rarity]),
             "totalPercent": pool["weights"][rarity] / 10000}
            for rarity in sorted(pool["characters"], reverse=True)]},
        "upCharInfo": {"perCharList": []}, "weightUpCharInfoList": [], "limitedChar": [],
        "gachaObjList": [
            {"gachaObject": "TEXT", "type": 3, "imageType": 0, "param": pool["name"]},
            *([{"gachaObject": "TEXT", "type": 4, "imageType": 0, "param": pool["intro"]}]
              if pool["intro"] else []),
            {"gachaObject": "AVAIL_CHAR", "type": 0, "imageType": 0, "param": None},
            *([{"gachaObject": "TEXT", "type": 5, "imageType": 0, "param": pool["description"]}]
              if pool["description"] else []),
        ],
    }, "gachaObjGroupType": group_type, "hasRateUp": False}


def snapshot(ctx) -> dict:
    config = ctx.data.headhunting
    states = {row.group_id: row for row in ctx.rows(m.GachaPity)}
    begun = [key for key in states if key.startswith("BOOT_")]
    if len(begun) > 1:
        raise DomainError("INVALID_HEADHUNTING_STATE", "账号存在多个新手卡池进度", 503)
    pool_id = begun[0] if begun else config.default_newcomer
    if pool_id is not None and pool_id not in config.newcomer:
        raise DomainError("HEADHUNTING_VERSION_MISMATCH", "此版本不包含账号已使用的新手卡池", 503)
    remaining = 0
    if pool_id is not None:
        limit = config.newcomer[pool_id]["limit"]
        state = states.get(pool_id)
        used = state.total_pulls if state else 0
        if type(used) is not int or not 0 <= used <= limit:
            raise DomainError("INVALID_HEADHUNTING_STATE", "新手卡池剩余次数非法", 503)
        remaining = limit - used
    normal = {}
    banners = {row.pool_id: row for row in ctx.rows(m.HeadHuntingBanner)}
    for key, definition in config.normal.items():
        state = states.get(key)
        banner = banners.get(key)
        used = banner.total_pulls if banner else (state.total_pulls if state else 0)
        if type(used) is not int or used < 0:
            raise DomainError("INVALID_HEADHUNTING_STATE", "寻访计数非法", 503)
        normal[key] = {"cnt": min(used, definition["maximum"]), "maxCnt": definition["maximum"],
                       "avail": definition["available"] and not bool(
                           banner.guarantee_used if banner else state and state.guarantee_used)}
    from terralocal.server.domain.standard_headhunting import SingleGuarantee

    single_progress = {key: SingleGuarantee(pool["up"][5][0]) for key, pool in config.pools.items()
                       if pool["rule_type"] == "SINGLE"}
    played = single_progress.keys() & banners.keys()
    if played:
        history = select(m.GachaHistory.banner_id, m.GachaHistory.rarity, m.GachaHistory.char_id).where(
            m.GachaHistory.account_id == ctx.account_id, m.GachaHistory.banner_id.in_(played)
        ).order_by(m.GachaHistory.id)
        for key, rarity, char_id in ctx.session.execute(history):
            single_progress[key].record(rarity, char_id)
    single = {}
    double = {}
    special = {}
    for key, pool in config.pools.items():
        banner = banners.get(key)
        if pool["rule_type"] == "SPECIAL":
            special[key] = {"upChar": banner.selected_up if banner and banner.selected_up else {}}
        elif pool["rule_type"] == "SINGLE":
            progress = single_progress[key]
            single[key] = {**normal[key], "singleEnsureCnt": -1 if progress.pending else progress.misses,
                           "singleEnsureUse": progress.used, "singleEnsureChar": progress.target}
        else:
            count = banner.total_pulls if banner else 0
            hits = banner.double_guarantees if banner else 0
            pending = 1 if hits == 0 and count >= 150 else (2 if hits == 1 and count >= 300 else 0)
            double[key] = {"showCnt": min(count, 300), "hitCharState": pending,
                           "hitCharId": banner.first_target if banner and pending == 2 else ""}
    # PlayerGacha.doubleGacha uses JsonProperty(PropertyName="double") in the
    # frozen client. Its C# member name is ignored on the wire, including deltas.
    return {"newbee": {"openFlag": remaining > 0, "cnt": remaining, "poolId": pool_id or ""},
            "normal": normal, "limit": {}, "linkage": {}, "attain": {}, "single": single,
            "double": double, "fesClassic": {}, "special": special, "backflow": {}}


def draw_newcomer(ctx, pool_id: str, use_ticket: int, count: int, item_id: str | None = None,
                  item_list: list | None = None) -> dict:
    config = ctx.data.headhunting
    if pool_id not in config.newcomer:
        if pool_id in config.normal:
            raise NotImplementedFeature("此寻访卡池的抽选、保底与选择规则")
        raise DomainError("UNKNOWN_GACHA_POOL", "寻访卡池不在当前版本中", 404)
    if count not in {1, 10}:
        raise DomainError("INVALID_GACHA_COUNT", "寻访次数必须为一次或十次")
    pool = config.newcomer[pool_id]
    if use_ticket == 9:
        # Frozen 2.7.71 sends CombineTenTicket even when the only cost is
        # discounted orundum: [{id: "4003", count: 3800}]. This declares the
        # cost; it never authorizes the client to choose the server's price.
        if count != 10 or item_id or item_list != [{"id": "4003", "count": pool["price"] * count}]:
            raise DomainError("INVALID_GACHA_PAYMENT", "寻访支付明细与卡池价格不一致")
    elif use_ticket != 0 or item_id or item_list:
        raise NotImplementedFeature("新手卡池的其他寻访支付方式")
    current = snapshot(ctx)["newbee"]
    if current["poolId"] != pool_id:
        raise DomainError("GACHA_COHORT_MISMATCH", "账号不能改用另一组新手卡池", 409)
    if current["cnt"] < count:
        raise DomainError("GACHA_POOL_EXHAUSTED", "新手卡池剩余次数不足", 409)
    state = ctx.session.get(m.GachaPity, (ctx.account_id, pool_id))
    if state is None:
        state = m.GachaPity(account_id=ctx.account_id, group_id=pool_id, seed=secrets.randbits(63),
                            policy_version=POLICY, gamedata_hash=ctx.data.manifest["hash"])
        ctx.session.add(state)
        ctx.session.flush()
    if (state.policy_version != POLICY or state.gamedata_hash != ctx.data.manifest["hash"]
            or type(state.seed) is not int or not 0 <= state.seed < 2**63
            or type(state.rng_counter) is not int or type(state.pulls_without_six) is not int
            or state.rng_counter != state.total_pulls or not 0 <= state.pulls_without_six <= state.total_pulls):
        raise DomainError("HEADHUNTING_VERSION_MISMATCH", "寻访进度缺少匹配的数据、规则或随机计数依据", 503)
    history = list(ctx.session.scalars(select(m.GachaHistory).where(
        m.GachaHistory.account_id == ctx.account_id, m.GachaHistory.banner_id == pool_id)
        .order_by(m.GachaHistory.id)))
    if (len(history) != state.total_pulls or any(
            row.char_id not in pool["characters"].get(row.rarity, []) for row in history)):
        raise DomainError("INVALID_HEADHUNTING_STATE", "寻访次数与已保存历史不一致", 503)
    trailing = next((index for index, row in enumerate(reversed(history)) if row.rarity == 5), len(history))
    if (state.pulls_without_six != trailing
            or state.guarantee_used != any(row.rarity >= 4 for row in history)):
        raise DomainError("INVALID_HEADHUNTING_STATE", "寻访保底进度与已保存历史不一致", 503)
    six_seen = any(row.rarity == 5 for row in history)
    if state.total_pulls >= 10 and not any(row.rarity == 5 for row in history[:10]):
        raise DomainError("INVALID_HEADHUNTING_STATE", "新手前十次记录缺少已保证的六星干员", 503)
    ctx.change_item("4003", -pool["price"] * count)
    results = []
    for _ in range(count):
        rng = random.Random(f"{POLICY}:{ctx.data.manifest['hash']}:{state.seed}:{state.rng_counter}")
        # The actual BOOT_0_1_3 banner states that the first ten draws contain
        # a six-star. The branch remains durable across separate single pulls.
        if state.total_pulls >= 9 and not six_seen:
            rarity = 5
        else:
            levels = sorted(pool["characters"])
            rarity = rng.choices(levels, weights=[pool["weights"][level] for level in levels], k=1)[0]
        char_id = rng.choice(pool["characters"][rarity])
        result = acquire_standard(ctx, char_id)
        results.append(result)
        ctx.session.add(m.GachaHistory(account_id=ctx.account_id, banner_id=pool_id, char_id=char_id,
                                        rarity=rarity, is_new=result["isNew"], drawn_at=ctx.now))
        ctx.emit("HeadHuntCompleted", pool_id=pool_id, char_id=char_id)
        state.total_pulls += 1
        state.rng_counter += 1
        state.guarantee_used = state.guarantee_used or rarity >= 4
        state.pulls_without_six = 0 if rarity == 5 else state.pulls_without_six + 1
        six_seen = six_seen or rarity == 5
    return {"charGet": results[0]} if count == 1 else {"gachaResultList": results}
