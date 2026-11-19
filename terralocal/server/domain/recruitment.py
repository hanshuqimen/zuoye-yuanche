"""Durable recruitment state machine. Random policy is explicitly local.

The client tables contain pool/time/tag constraints but no server draw rates.
LOCAL_RECRUIT_V1 must not be advertised as the official probability algorithm.
Persist the selected outcome at start so reads, restarts and retries cannot reroll.
"""

import random
import secrets
from itertools import combinations

from terralocal.server.domain.errors import DomainError, NotImplementedFeature
from terralocal.server.persistence import models as m

POLICY = "LOCAL_RECRUIT_V1"
RARITY_WEIGHTS = {0: 100, 1: 200, 2: 8500, 3: 1000, 4: 200, 5: 0}
STATE = {"LOCK": 0, "IDLE": 1, "BUSY": 2, "FAST_FINISH": 3}


def catalog(ctx):
    return ctx.data.recruitment


def sync_slots(ctx) -> None:
    config = catalog(ctx)
    account = ctx.session.get(m.Account, ctx.account_id)
    stage = ctx.session.get(m.StageProgress, (ctx.account_id, "main_00-02"))
    open_initial = account.preset != "Vanilla" or bool(stage and stage.stars >= 2)
    for slot_id in range(4):
        slot = ctx.session.get(m.RecruitSlot, (ctx.account_id, slot_id))
        if slot is None:
            slot = m.RecruitSlot(account_id=ctx.account_id, slot=slot_id, state="LOCK", available_tags=[])
            ctx.session.add(slot)
            ctx.session.flush()
        if not slot.available_tags:
            if slot.started_at is not None or slot.state not in {"IDLE", "LOCK"}:
                raise DomainError("INVALID_RECRUIT_STATE", "已有招募存档缺少标签，无法自动覆盖", 503)
            slot.available_tags = list(config.initial_tags)
            slot.state = "IDLE" if slot_id < 2 and open_initial else "LOCK"
        elif slot_id < 2 and open_initial and slot.state == "LOCK":
            slot.state = "IDLE"
    ctx.session.flush()


def slot_for(ctx, slot_id: int, expected: set[str]):
    sync_slots(ctx)
    slot = ctx.session.get(m.RecruitSlot, (ctx.account_id, slot_id))
    if slot is None:
        raise DomainError("UNKNOWN_RECRUIT_SLOT", "招募槽位不存在", 404)
    if slot.state not in expected:
        raise DomainError("RECRUIT_SLOT_STATE", "此招募槽位当前不能执行该操作", 409)
    return slot


def snapshot(ctx) -> dict:
    config = catalog(ctx)
    slots = {}
    for slot in ctx.rows(m.RecruitSlot):
        collections = [slot.available_tags, slot.tags, slot.retained_tags]
        if (slot.slot not in range(4) or slot.state not in STATE
                or any(not isinstance(tags, list) or any(type(tag) is not int or tag not in config.tags
                                                         for tag in tags) for tags in collections)
                or any(len(set(tags)) != len(tags) for tags in collections)
                or len(slot.available_tags) not in {0, 5} or len(slot.tags) > 3
                or not set(slot.tags) <= set(slot.available_tags)
                or not set(slot.retained_tags) <= set(slot.tags)):
            raise DomainError("INVALID_RECRUIT_STATE", "招募存档状态或标签非法", 503)
        uninitialized = not slot.available_tags
        state = 0 if uninitialized else STATE[slot.state]
        if slot.state in {"BUSY", "FAST_FINISH"}:
            if (slot.result_char_id not in config.characters
                    or any(type(value) is not int for value in [slot.started_at, slot.finishes_at,
                                                               slot.max_finishes_at, slot.duration_seconds, slot.seed])
                    or slot.started_at < 0 or slot.started_at > slot.finishes_at
                    or slot.max_finishes_at != slot.started_at + slot.duration_seconds
                    or slot.finishes_at > slot.max_finishes_at
                    or slot.duration_seconds <= 0 or slot.duration_seconds % 60
                    or slot.duration_seconds // 60 not in config.prices
                    or not 0 <= slot.seed < 2**63
                    or slot.policy_version != POLICY or slot.gamedata_hash != ctx.data.manifest["hash"]):
                raise DomainError("INVALID_RECRUIT_STATE", "进行中的招募结果或计时缺失", 503)
        elif (any(value is not None for value in [slot.started_at, slot.finishes_at, slot.max_finishes_at,
                                                 slot.seed, slot.result_char_id, slot.policy_version, slot.gamedata_hash])
              or slot.duration_seconds != 0 or slot.tags or slot.retained_tags):
            raise DomainError("INVALID_RECRUIT_STATE", "空闲招募槽位仍包含未清理的招募状态", 503)
        slots[str(slot.slot)] = {"state": state,
                                "tags": slot.available_tags or config.initial_tags,
                                "selectTags": [{"tagId": tag, "pick": tag in slot.retained_tags} for tag in slot.tags],
                                "startTs": slot.started_at if slot.started_at is not None else -1,
                                "maxFinishTs": slot.max_finishes_at if slot.max_finishes_at is not None else -1,
                                "realFinishTs": slot.finishes_at if slot.finishes_at is not None else -1,
                                "durationInSec": slot.duration_seconds}
    return {"normal": {"slots": slots}}


def _choose(config, duration: int, selected: list[int], seed: int) -> tuple[str, list[int]]:
    rng = random.Random(seed)
    low, high = config.rarity_ranges[duration // 60]
    rarities = set(range(low, high + 1))
    # Frozen client instructions guarantee these special tags at nine hours.
    protected = []
    if duration == config.maximum_minutes * 60:
        for tag in sorted(config.special_rarities, key=lambda t: max(config.special_rarities[t]), reverse=True):
            if tag in selected:
                protected = [tag]
                rarities = set(config.special_rarities[tag])
                break
    # Local policy retains feasible selected tags; incompatible combinations
    # lose the smallest number. No undocumented official drop rate is invented.
    options = []
    for size in range(len(selected), -1, -1):
        for subset in combinations(sorted(selected), size):
            if not set(protected) <= set(subset):
                continue
            candidates = config.candidates(list(subset), rarities)
            if candidates:
                options.append((list(subset), candidates))
        if options:
            break
    if not options:
        raise DomainError("NO_RECRUIT_CANDIDATE", "当前时限和标签没有可招募干员")
    kept, candidates = rng.choice(options)
    by_rarity = {}
    for char_id in candidates:
        by_rarity.setdefault(config.characters[char_id][0], []).append(char_id)
    levels = sorted(by_rarity)
    weights = [RARITY_WEIGHTS[level] or (1 if protected else 0) for level in levels]
    if not any(weights):
        raise DomainError("INVALID_RECRUIT_DATA", "招募数据中的普通星级范围没有受支持的抽选权重", 503)
    level = rng.choices(levels, weights=weights, k=1)[0]
    return rng.choice(by_rarity[level]), kept


def start(ctx, slot_id: int, tags: list[int], duration: int, special_tag_id: int = -1) -> dict:
    slot = slot_for(ctx, slot_id, {"IDLE"})
    if special_tag_id != -1:
        raise NotImplementedFeature("特别公开招募活动标签")
    if len(tags) > 3 or len(set(tags)) != len(tags) or not set(tags) <= set(slot.available_tags):
        raise DomainError("INVALID_RECRUIT_TAGS", "只能选择此槽位中最多三个不同标签")
    config = catalog(ctx)
    price = config.cost(duration, tags)
    seed = secrets.randbits(63)
    char_id, retained = _choose(config, duration, tags, seed)
    ctx.consume([{"id": "7001", "count": 1}, {"id": "4001", "count": price}])
    slot.state, slot.tags, slot.retained_tags = "BUSY", sorted(tags), retained
    slot.started_at, slot.finishes_at = ctx.now, ctx.now + duration
    slot.max_finishes_at, slot.duration_seconds = slot.finishes_at, duration
    slot.seed, slot.result_char_id = seed, char_id
    slot.policy_version, slot.gamedata_hash = POLICY, ctx.data.manifest["hash"]
    return {}


def boost(ctx, slot_id: int, buy: int) -> dict:
    slot = slot_for(ctx, slot_id, {"BUSY"})
    if ctx.now >= slot.finishes_at:
        raise DomainError("RECRUIT_ALREADY_READY", "招募已经完成，无需使用加急许可", 409)
    if ctx.now < slot.started_at:
        raise DomainError("CLOCK_PRECEDES_RECRUIT", "服务器时间早于本次招募开始时间", 409)
    if buy != 0:
        raise NotImplementedFeature("用龙门币或源石购买招募加急")
    ctx.change_item("7002", -1)
    slot.state, slot.finishes_at = "FAST_FINISH", ctx.now
    return {}


def _clear(slot) -> None:
    slot.state, slot.tags, slot.retained_tags = "IDLE", [], []
    slot.started_at = slot.finishes_at = slot.max_finishes_at = slot.seed = None
    slot.duration_seconds = 0
    slot.result_char_id = slot.policy_version = slot.gamedata_hash = None


def cancel(ctx, slot_id: int) -> dict:
    slot = slot_for(ctx, slot_id, {"BUSY"})
    if ctx.now >= slot.finishes_at:
        raise DomainError("RECRUIT_ALREADY_READY", "已完成的招募应领取干员，不能取消", 409)
    _clear(slot)  # The consumed permission/cost is not refunded.
    return {}


def finish(ctx, slot_id: int) -> dict:
    from terralocal.server.domain.acquisitions import acquire_standard

    slot = slot_for(ctx, slot_id, {"BUSY", "FAST_FINISH"})
    if slot.finishes_at is None or ctx.now < slot.finishes_at:
        raise DomainError("RECRUIT_NOT_READY", "招募尚未完成", 409)
    if slot.gamedata_hash != ctx.data.manifest["hash"] or slot.policy_version != POLICY:
        raise DomainError("RECRUIT_VERSION_MISMATCH", "请使用开始此招募时的兼容数据和规则领取", 503)
    config = catalog(ctx)
    if slot.result_char_id not in config.characters:
        raise DomainError("INVALID_RECRUIT_STATE", "招募结果不在此版本的公开招募池中", 503)
    char_id = slot.result_char_id
    result = acquire_standard(ctx, char_id)
    ctx.session.add(m.GachaHistory(account_id=ctx.account_id, banner_id="RECRUIT",
                                    char_id=char_id, rarity=config.characters[char_id][0],
                                    is_new=result["isNew"], drawn_at=ctx.now))
    ctx.emit("RecruitCompleted")
    _clear(slot)
    rng = random.Random(secrets.randbits(63))
    possible = sorted(config.tags)
    # Versioned local tag distribution; rare tags are less frequent. This is
    # intentionally separate from headhunting rates and is not official data.
    fresh = []
    while len(fresh) < 5:
        choice = rng.choices(possible, weights=[1 if tag == 11 else 5 if tag == 14 else 1000
                                               for tag in possible], k=1)[0]
        fresh.append(choice)
        possible.remove(choice)
    slot.available_tags = fresh
    return {"charGet": result}
