from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from terralocal.server.domain.clock import ServerClock
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata import GameData
from terralocal.server.persistence import models as m

CURRENCY_TYPES = {"GOLD", "DIAMOND", "DIAMOND_SHD", "HGG_SHD", "LGG_SHD", "LMTGS_COIN", "SOCIAL_PT"}


def item_entity(item_type: str):
    if item_type in CURRENCY_TYPES:
        return m.Currency
    return m.OwnedFurniture if item_type == "FURN" else m.InventoryItem


class Context:
    def __init__(self, session: Session, data: GameData, account_id: int, *,
                 local_session: m.LocalSession | None = None):
        self.session, self.data, self.account_id = session, data, account_id
        self.local_session = local_session
        self.profile = session.get(m.PlayerProfile, account_id)
        if self.profile is None:
            raise DomainError("UNKNOWN_ACCOUNT", "本地账号不存在", 404)
        self.clock = ServerClock(session.get(m.ServerClockState, 1))
        self.now = self.clock.now()

    def rows(self, entity):
        return self.session.scalars(select(entity).where(entity.account_id == self.account_id)).all()

    def read_rows(self, entity):
        """Snapshot column values without allocating mutable ORM entities.

        Flush the caller's transaction first: a Core table select does not
        trigger ORM autoflush. Each call queries current membership and values;
        no result survives a transaction or needs invalidation after restore.
        Domain writes continue to use rows(), operator() and session.get().
        """
        self.session.flush()
        return self.session.execute(select(entity.__table__).where(entity.account_id == self.account_id)).all()

    def operator(self, operator_id: int) -> m.Operator:
        op = self.session.get(m.Operator, operator_id)
        if op is None or op.account_id != self.account_id:
            raise DomainError("UNKNOWN_OPERATOR", "此账号不拥有该干员", 404)
        return op

    def balance(self, item_id: str) -> int:
        definition = self.data.item(item_id)
        if definition["itemType"] == "CHAR_SKIN":
            return int(self.session.get(m.OwnedSkin, (self.account_id, item_id)) is not None)
        cls = item_entity(definition["itemType"])
        row = self.session.get(cls, (self.account_id, item_id))
        return (row.balance if cls is m.Currency else row.count) if row else 0

    def change_item(self, item_id: str, amount: int) -> None:
        definition = self.data.item(item_id)
        if definition["itemType"] == "CHAR_SKIN":
            from terralocal.server.domain.skins import grant

            grant(self, item_id, amount)
            return
        if definition["itemType"] == "EXP_PLAYER":
            if amount < 0:
                raise DomainError("INVALID_REWARD", "玩家经验不能扣除")
            self.player_exp(amount)
            return
        cls = item_entity(definition["itemType"])
        field = "balance" if cls is m.Currency else "count"
        row = self.session.get(cls, (self.account_id, item_id))
        old = getattr(row, field) if row else 0
        if old + amount < 0:
            raise DomainError("INSUFFICIENT_ITEM", f"{definition['name']} 不足")
        if old + amount > 2_000_000_000:
            raise DomainError("INVENTORY_LIMIT", "物品数量超出范围")
        if row is None:
            row = cls(account_id=self.account_id, item_id=item_id, **{field: old + amount})
            self.session.add(row)
        else:
            setattr(row, field, old + amount)
        self.session.flush()

    def rewards(self, entries: list[dict], multiplier: int = 1) -> list[dict]:
        granted = []
        for reward in entries:
            if reward["count"] < 0:
                raise DomainError("INVALID_REWARD", "奖励不能为负数")
            definition = self.data.item(reward["id"])
            if definition["itemType"] == "CHAR_SKIN" and (
                    type(reward["count"]) is not int or type(multiplier) is not int):
                raise DomainError("INVALID_REWARD", "外观奖励数量必须为整数")
            if definition["itemType"] == "CHAR":
                from terralocal.server.domain.acquisitions import acquire_standard

                for _ in range(multiplier * reward["count"]):
                    granted.append({"id": reward["id"], "type": "CHAR", "count": 1,
                                    "charGet": acquire_standard(self, reward["id"])})
            else:
                self.change_item(reward["id"], reward["count"] * multiplier)
                granted.append({**reward, "type": definition["itemType"], "count": reward["count"] * multiplier})
        return granted

    def consume(self, entries: list[dict], multiplier: int = 1) -> None:
        totals = {}
        for entry in entries:
            if entry["count"] < 0:
                raise DomainError("INVALID_COST", "消耗不能为负数")
            totals[entry["id"]] = totals.get(entry["id"], 0) + entry["count"] * multiplier
        for item_id, count in totals.items():
            if self.balance(item_id) < count:
                raise DomainError("INSUFFICIENT_ITEM", f"{self.data.item(item_id)['name']} 不足")
        for item_id, count in totals.items():
            self.change_item(item_id, -count)

    def sanity(self) -> m.SanityState:
        state = self.session.get(m.SanityState, self.account_id)
        if self.now < state.last_recovery_at:
            return state  # Rewinding a virtual clock cannot grant repeated recovery.
        if state.current >= state.maximum:
            state.last_recovery_at = self.now
        else:
            recovered = (self.now - state.last_recovery_at) // state.interval
            state.current = min(state.maximum, state.current + recovered)
            state.last_recovery_at = self.now if state.current == state.maximum else (
                state.last_recovery_at + recovered * state.interval
            )
        return state

    def player_exp(self, amount: int) -> None:
        const = self.data.constants
        self.profile.exp += amount
        sanity = self.sanity()
        while self.profile.level < const["maxPlayerLevel"]:
            needed = const["playerExpMap"][self.profile.level - 1]
            if self.profile.exp < needed:
                break
            self.profile.exp -= needed
            self.profile.level += 1
            sanity.maximum = const["playerApMap"][self.profile.level - 1]
            sanity.current += sanity.maximum

    def acquire_operator(self, char_id: str, count: int = 1, *, stream: str = "STANDARD") -> tuple[m.Operator, bool]:
        if type(count) is not int or not 1 <= count <= 100_000:
            raise DomainError("INVALID_REWARD", "干员获得数量无效")
        if stream not in {"STANDARD", "CLASSIC"}:
            raise DomainError("INVALID_REWARD", "干员获得来源无效")
        granted_count = count
        definition = self.data.character(char_id)
        if definition.get("isNotObtainable"):
            raise DomainError("UNOBTAINABLE_OPERATOR", "该角色不是可获取干员")
        op = self.session.scalar(select(m.Operator).where(
            m.Operator.account_id == self.account_id, m.Operator.char_id == char_id))
        is_new = op is None
        if op is None:
            skin = f"{char_id}#1"
            if "skin_table" in self.data.manifest["tables"]:
                defaults = self.data.table("skin_table").get("buildinEvolveMap", {}).get(char_id, {})
                skin = defaults.get("0", skin)
            op = m.Operator(account_id=self.account_id, char_id=char_id, skin=skin,
                            gained_at=self.now)
            if "charword_table" in self.data.manifest["tables"]:
                from terralocal.server.domain.voice import initial_language

                op.voice_language = initial_language(self, char_id)
            self.session.add(op)
            self.session.flush()
            for skill in definition["skills"]:
                if skill.get("skillId"):
                    self.session.add(m.OperatorSkill(operator_id=op.id, skill_id=skill["skillId"]))
            count -= 1
        if count:
            token = definition.get("classicPotentialItemId" if stream == "CLASSIC" else "potentialItemId")
            if not token:
                raise DomainError("GAMEDATA_MISSING", "重复干员的信物定义缺失", 503)
            self.change_item(token, count)
        from terralocal.server.domain.acquisitions import record_direct

        record_direct(self, char_id, owned=not is_new, count=granted_count, stream=stream)
        return op, is_new

    def emit(self, name: str, value: int = 1, **payload) -> None:
        self.session.add(m.DomainEvent(id=str(uuid.uuid4()), account_id=self.account_id,
                                       event_type=name, payload={"value": value, **payload}, occurred_at=self.now))
        if "mission_table" not in self.data.manifest["tables"]:
            return
        if name in {"BattleFinished", "StoryStageFinished"}:
            from terralocal.server.domain.mission_stages import reconcile

            reconcile(self)
        if name in {"OperatorLeveled", "OperatorEvolved"}:
            from terralocal.server.domain.mission_upgrade import progress

            progress(self, name)
            return
        # Only templates with known semantics are subscribed; others remain explicitly unsupported.
        mapping = {"BattleFinished": "CompleteStage",
                   "RecruitCompleted": "RecruitChar", "ShopPurchased": "BuyItem", "Login": "Login"}
        template = mapping.get(name)
        if not template:
            return
        for mission_id, definition in self.data.table("mission_table")["missions"].items():
            if name == "BattleFinished":
                from terralocal.server.domain.mission_rules import BATTLE_TEMPLATES, matches_battle

                if (definition["template"] not in BATTLE_TEMPLATES or not matches_battle(
                        definition, self.data.stage(payload["stage_id"]), stars=payload["stars"],
                        practice=payload["practice"])):
                    continue
            elif definition["template"] != template:
                continue
            kind = {"DAILY": "daily", "WEEKLY": "weekly"}.get(definition["type"], "permanent")
            period = self.clock.period(kind, at=self.now)
            row = self.session.get(m.MissionProgress, (self.account_id, mission_id, period))
            if kind in {"daily", "weekly"} and row is None:
                # Only assigned periodic missions may progress. Assigning an
                # entire catalog here would activate every daily pool variant.
                continue
            if row is None:
                row = m.MissionProgress(account_id=self.account_id, mission_id=mission_id,
                                        period=period, progress=0, claimed=False)
                self.session.add(row)
            if not row.claimed:
                row.progress += value
