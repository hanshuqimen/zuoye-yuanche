from __future__ import annotations

import hashlib
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from sqlalchemy import select

from terralocal.server.domain.clock import ServerClock
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.operator_limits import maximum_trust
from terralocal.server.persistence import models as m

PASSWORDS = PasswordHasher()


def _full_roster_target(definition: dict) -> dict:
    """Compute valid GM targets from this character's actual upgrade conditions."""
    potential = definition.get("maxPotentialLevel")
    phases = definition.get("phases")
    upgrades = definition.get("allSkillLvlup")
    skills_definition = definition.get("skills")
    if (type(potential) is not int or potential < 0 or not isinstance(upgrades, list) or
            not isinstance(phases, list) or not phases or not isinstance(skills_definition, list)):
        raise DomainError("GAMEDATA_INVALID", "干员潜能或技能上限定义非法", 503)
    requirements = [(0, 1)]

    def require(condition: dict) -> None:
        try:
            phase = condition["phase"]
            phase = int(phase.removeprefix("PHASE_")) if isinstance(phase, str) else phase
            level = condition["level"]
            if (type(phase) is not int or type(level) is not int or
                    phase not in range(len(phases)) or not 1 <= level <= phases[phase]["maxLevel"]):
                raise ValueError("invalid condition")
        except (KeyError, ValueError, TypeError) as exc:
            raise DomainError("GAMEDATA_INVALID", "干员技能解锁条件非法", 503) from exc
        requirements.append((phase, level))

    for upgrade in upgrades:
        require(upgrade.get("unlockCond") if isinstance(upgrade, dict) else None)
    skills = []
    for skill in skills_definition:
        if not isinstance(skill, dict) or not isinstance(skill.get("skillId"), str) or not skill["skillId"]:
            raise DomainError("GAMEDATA_INVALID", "干员技能定义非法", 503)
        require(skill.get("unlockCond"))
        tree = skill.get("levelUpCostCond") or []
        if not isinstance(tree, list):
            raise DomainError("GAMEDATA_INVALID", "干员专精树定义非法", 503)
        mastery = min(3, len(tree))
        for upgrade in tree[:mastery]:
            require(upgrade.get("unlockCond") if isinstance(upgrade, dict) else None)
        skills.append((skill["skillId"], mastery))
    phase = max(p for p, _ in requirements)
    level = max(level for p, level in requirements if p == phase)
    return {"potential": potential, "skill_level": len(upgrades) + 1,
            "phase": phase, "level": level, "skills": skills}


def complete_roster(ctx: Context) -> dict:
    """Grant all obtainable characters and maximum requested training in one caller transaction.

    Repeated applications update existing instances and never grant duplicate tokens.
    Levels advance only as far as required to unlock the requested skill training.
    """
    trust_limit = maximum_trust(ctx.data)
    targets = {cid: _full_roster_target(char) for cid, char in ctx.data.characters.items()
               if cid.startswith("char_") and not char.get("isNotObtainable")}
    if not targets:
        raise DomainError("GAMEDATA_INVALID", "当前数据没有可获得干员", 503)
    owned = {op.char_id: op for op in ctx.rows(m.Operator)}
    skill_rows = {op.id: {} for op in owned.values()}
    if skill_rows:
        for row in ctx.session.scalars(select(m.OperatorSkill).where(
                m.OperatorSkill.operator_id.in_(list(skill_rows)))):
            skill_rows[row.operator_id][row.skill_id] = row
    granted, changed, mastered, unsupported = 0, 0, 0, 0
    for char_id, target in targets.items():
        op = owned.get(char_id)
        if op is None:
            op, _ = ctx.acquire_operator(char_id)
            granted += 1
            # acquire_operator has already created skill rows; load them after flushing.
            ctx.session.flush()
            skill_rows[op.id] = {r.skill_id: r for r in ctx.session.scalars(
                select(m.OperatorSkill).where(m.OperatorSkill.operator_id == op.id))}
        before = (op.potential, op.trust, op.skill_level, op.evolve_phase, op.level, op.exp)
        op.potential, op.trust, op.skill_level = target["potential"], trust_limit, target["skill_level"]
        if op.evolve_phase < target["phase"]:
            op.evolve_phase, op.level, op.exp = target["phase"], target["level"], 0
        elif op.evolve_phase == target["phase"] and op.level < target["level"]:
            op.level, op.exp = target["level"], 0
        after = (op.potential, op.trust, op.skill_level, op.evolve_phase, op.level, op.exp)
        operator_changed = before != after
        for skill_id, mastery in target["skills"]:
            row = skill_rows[op.id].get(skill_id)
            if row is None:
                row = m.OperatorSkill(operator_id=op.id, skill_id=skill_id)
                ctx.session.add(row)
                operator_changed = True
            if row.mastery != mastery or row.training_complete_at is not None:
                operator_changed = True
            row.mastery, row.training_complete_at = mastery, None
            mastered += int(mastery == 3)
            unsupported += int(mastery == 0)
        changed += int(operator_changed)
    ctx.session.flush()
    return {"totalOperators": len(targets), "grantedOperators": granted, "updatedOperators": changed,
            "masteredSkills": mastered, "skillsWithoutMastery": unsupported, "maxTrust": trust_limit}


def create_account(session, data, name: str, preset: str = "Vanilla", password: str | None = None) -> m.Account:
    if preset not in {"Vanilla", "Progressed", "Sandbox"}:
        raise DomainError("INVALID_PRESET", "未知账号预设")
    if not name.strip() or len(name) > 64 or len(password or "") > 256:
        raise DomainError("INVALID_ACCOUNT", "名称或密码长度非法")
    if session.scalar(select(m.Account.id).where(m.Account.name == name)):
        raise DomainError("ACCOUNT_EXISTS", "账号名称已存在", 409)
    now = ServerClock(session.get(m.ServerClockState, 1)).now()
    account = m.Account(uid=secrets.token_hex(12), name=name, preset=preset, created_at=now,
                        password_hash=PASSWORDS.hash(password) if password else None)
    session.add(account)
    session.flush()
    initial = data.constants["initCharIdList"]
    profile = m.PlayerProfile(account_id=account.id, nickname=name, secretary=initial[0],
                              secretary_skin=f"{initial[0]}#1", registered_at=now, last_online_at=now)
    session.add(profile)
    maximum = data.constants["playerApMap"][0]
    session.add(m.SanityState(account_id=account.id, current=maximum, maximum=maximum,
                             last_recovery_at=now, interval=data.constants["playerApRegenSpeed"] * 60))
    session.flush()
    ctx = Context(session, data, account.id)
    for char_id in initial:
        ctx.acquire_operator(char_id)
    for i in range(4):
        session.add(m.Squad(account_id=account.id, squad_id=str(i), name=f"编队 {i + 1}"))
        session.add(m.RecruitSlot(account_id=account.id, slot=i, available_tags=[]))
    for slot, op in enumerate(ctx.rows(m.Operator)):
        session.add(m.SquadSlot(account_id=account.id, squad_id="0", slot=slot,
                               operator_id=op.id, skill_index=0))
    ctx.change_item("4001", data.constants["initPlayerGold"])
    ctx.change_item("4003", data.constants["initPlayerDiamondShard"])
    if preset != "Vanilla":
        if preset == "Sandbox":
            complete_roster(ctx)
        else:
            candidates = [cid for cid, c in data.characters.items() if cid.startswith("char_")
                          and not c.get("isNotObtainable")]
            for char_id in candidates[:20]:
                if session.scalar(select(m.Operator.id).where(
                    m.Operator.account_id == account.id, m.Operator.char_id == char_id)):
                    continue
                op, _ = ctx.acquire_operator(char_id)
                phase = min(1, len(data.characters[char_id]["phases"]) - 1)
                op.evolve_phase = phase
                op.level = min(30, data.characters[char_id]["phases"][phase]["maxLevel"])
        for item_id in ("4001", "4002", "4003"):
            ctx.change_item(item_id, (1_000_000 if preset == "Sandbox" else 100_000))
        profile.level = min(50, data.constants["maxPlayerLevel"], len(data.constants["playerApMap"]))
        ctx.sanity().maximum = data.constants["playerApMap"][profile.level - 1]
        ctx.sanity().current = ctx.sanity().maximum
    session.add(m.Mail(account_id=account.id, title="欢迎来到 TerraLocal", sender="TerraLocal",
                       body="这是独立的本地存档。进度保存在你的电脑中。", rewards=[], created_at=now))
    session.flush()
    from terralocal.server.domain.home_rotation import initialize

    initialize(ctx)
    from terralocal.server.domain.campaign import initialize as initialize_campaign

    initialize_campaign(ctx)
    from terralocal.server.domain.rogue_topics import initialize as initialize_rogue

    initialize_rogue(ctx)
    return account


def login(session, settings, *, name: str | None = None, uid: str | None = None,
          password: str | None = None, token: str | None = None, kind: str = "game") -> dict:
    account = session.scalar(select(m.Account).where(m.Account.uid == uid if uid else m.Account.name == name))
    if account is None:
        raise DomainError("LOGIN_FAILED", "本地账号或密码错误", 401)
    if token:
        existing = authenticate(session, token, uid)
        if existing.id != account.id:
            raise DomainError("LOGIN_FAILED", "本地账号或密码错误", 401)
    elif account.password_hash:
        try:
            PASSWORDS.verify(account.password_hash, password or "")
        except VerificationError as exc:
            raise DomainError("LOGIN_FAILED", "本地账号或密码错误", 401) from exc
    secret = secrets.token_urlsafe(32)
    session.add(m.LocalSession(account_id=account.id, token_hash=hashlib.sha256(secret.encode()).hexdigest(),
                               kind=kind, expires_at=int(time.time()) + settings.session_ttl))
    profile = session.get(m.PlayerProfile, account.id)
    profile.last_online_at = ServerClock(session.get(m.ServerClockState, 1)).now()
    profile.flags = {**profile.flags, "loginTime": profile.last_online_at}
    return {"uid": account.uid, "secret": secret, "serviceLicenseVersion": 0, "result": 0}


def authenticate(session, token: str, uid: str | None = None) -> m.Account:
    row = session.scalar(select(m.LocalSession).where(
        m.LocalSession.token_hash == hashlib.sha256(token.encode()).hexdigest(),
        m.LocalSession.expires_at > int(time.time())))
    account = session.get(m.Account, row.account_id) if row else None
    if account is None or (uid is not None and account.uid != uid):
        raise DomainError("INVALID_SESSION", "本地登录已过期，请重新登录", 401)
    return account
