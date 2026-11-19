"""One current capsule, derived from ordered owned reward receipts and nodes."""

from dataclasses import dataclass

from terralocal.server.gamedata.rogue_capsules import require


@dataclass(frozen=True)
class Grant:
    battle_id: str
    reward_index: int
    item_id: str
    zone: int
    at: int


class History:
    def __init__(self, data, run):
        self.data, self.run = data, run
        self.grants = []
        self.current = None
        self.active_visit = None

    def acquire(self, battle, index, item, at):
        from terralocal.server.domain.rogue_progress import row_index

        run = self.run
        if (run.topic_id != "rogue_1" or run.mode != "NORMAL" or run.grade != 0
                or battle.run_id != run.id or battle.account_id != run.account_id
                or type(index) is not int or index < 0 or type(at) is not int
                or not run.created_at <= at < 2**63 or at < battle.ended_at
                or run.ended_at is not None and at > run.ended_at
                or self.grants and at < self.grants[-1].at or self.active_visit is not None
                or any((g.battle_id, g.reward_index) == (battle.id, index) for g in self.grants)):
            raise ValueError("剧目领取来源、时序或节点屏障不匹配")
        require(self.data, item, at=run.created_at)
        grant = Grant(battle.id, index, item, row_index(battle), at)
        self.grants.append(grant)
        self.current = grant  # Choosing a new capsule replaces the previous one.

    def floor(self, number):
        if type(number) is not int or not 1 <= number <= 5:
            raise ValueError("剧目楼层非法")
        if self.current is not None and number != self.current.zone:
            if number < self.current.zone or self.active_visit is not None:
                raise ValueError("剧目不能回到过去楼层或跨层保留激活节点")
            self.current = None

    def preview(self, number, kind, before):
        definition = self.matching(number, kind)
        if definition is None or self.active_visit is not None:
            return before.copy()
        changed = before | {"hp": before["hp"] + definition.hp, "gold": before["gold"] + definition.gold}
        if any(type(changed[k]) is not int or not 0 <= changed[k] < 2**31 for k in ("hp", "gold")):
            raise ValueError("剧目入场收益超出客户端整数范围")
        return changed

    def matching(self, number, kind):
        self.floor(number)
        if self.current is None:
            return None
        definition = require(self.data, self.current.item_id, at=self.run.created_at)
        return definition if definition.matches(kind) else None

    def enter(self, row, kind, before):
        from terralocal.server.domain.rogue_progress import row_index

        changed = self.preview(row_index(row), kind, before)
        grant = self.current
        if grant is not None and require(self.data, grant.item_id, at=self.run.created_at).matches(kind):
            if type(row.entered_at) is not int or row.entered_at < grant.at:
                raise ValueError("剧目不能在取得前激活")
            self.active_visit = row.id
        return changed

    def battle(self, row, kind):
        from terralocal.server.domain.rogue_progress import row_index

        definition = self.matching(row_index(row), kind)
        if definition is not None:
            if (self.active_visit not in (None, row.id) or type(row.started_at) is not int
                    or row.started_at < self.current.at):
                raise ValueError("剧目战斗与领取或激活顺序不一致")
            self.active_visit = row.id
        return definition.id if definition is not None else None

    def finish(self, row):
        if self.active_visit == row.id and row.state in ("FINISHED", "ABANDONED"):
            self.current, self.active_visit = None, None

    def wire(self):
        grant = self.current
        return None if grant is None else {"id": grant.item_id, "ts": grant.at,
                                          "active": self.active_visit is not None}


def attained(replayed):
    return frozenset(g.item_id for g in getattr(replayed, "capsule_grants", ()))


def project(data, state, found, at):
    """Earned discovery only; never make an unavailable effect a natural pool."""
    saved = state["collect"]["capsule"]
    for key, row in saved.items():
        require(data, key, at=at)
        if row["progress"] or row["state"] == 2 and key not in found:
            raise ValueError("剧目图鉴缺少已核对的获得来源")
    for key in found:
        require(data, key, at=at)
        saved[key] = {"state": 2, "progress": []}
    return state
