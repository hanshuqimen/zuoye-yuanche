"""Standard character acquisition, independent of potential and token exchange.

The public gameplay reward schedule is pinned in the implementation notes.
Legacy ownership/draw history provides a lower bound, not an invented exact
five/six-star count. New local grants are recorded from their first acquisition.
"""

from sqlalchemy import func, select

from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence import models as m

POLICY = "TERRALOCAL_STANDARD_ACQUISITION_V1"
EXACT = "recorded-local-grants"
LEGACY = "legacy-owned-and-recorded-draws"
VERIFIED = "verified-local-acquisition-count"


def counter(ctx, char_id: str, *, owned: bool, stream: str = "STANDARD") -> m.OperatorAcquisition:
    if stream not in {"STANDARD", "CLASSIC"}:
        raise DomainError("INVALID_ACQUISITION_STATE", "干员获得来源无效", 503)
    row = ctx.session.get(m.OperatorAcquisition, (ctx.account_id, char_id, stream))
    if row is None:
        # Another stream can own the character without any standard acquisition.
        other_stream = ctx.session.scalar(select(m.OperatorAcquisition.char_id).where(
            m.OperatorAcquisition.account_id == ctx.account_id,
            m.OperatorAcquisition.char_id == char_id, m.OperatorAcquisition.stream != stream))
        # Preserve a legacy standard lower bound before recording a first
        # kernel acquisition. Otherwise that new kernel row would incorrectly
        # make the missing standard history look like an exact zero later.
        if stream == "CLASSIC" and owned and other_stream is None:
            counter(ctx, char_id, owned=True, stream="STANDARD")
        count, basis = 0, EXACT
        if stream == "STANDARD" and owned and other_stream is None:
            duplicates = ctx.session.scalar(select(func.count(m.GachaHistory.id)).where(
                m.GachaHistory.account_id == ctx.account_id, m.GachaHistory.char_id == char_id,
                m.GachaHistory.is_new.is_(False)))
            count, basis = 1 + duplicates, LEGACY
        row = m.OperatorAcquisition(account_id=ctx.account_id, char_id=char_id,
                                    stream=stream, count=count, basis=basis)
        ctx.session.add(row)
        ctx.session.flush()
    if (type(row.count) is not int or not 0 <= row.count < 2_000_000_000
            or row.basis not in {EXACT, LEGACY, VERIFIED}):
        raise DomainError("INVALID_ACQUISITION_STATE", "干员获得次数记录无效", 503)
    return row


def set_verified_count(ctx, char_id: str, count: int, evidence: str | None) -> dict:
    """Correct a known local count through an audited GM operation.

    This changes neither ownership, potential, tokens nor certificates. The
    caller supplies the historical evidence; unknown legacy counts stay unknown.
    """
    if type(count) is not int or not 1 <= count < 2_000_000_000:
        raise DomainError("INVALID_ACQUISITION_COUNT", "获得次数必须为正整数")
    if not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 256:
        raise DomainError("ACQUISITION_EVIDENCE_REQUIRED", "请填写获得次数的记录依据")
    ctx.data.character(char_id)
    owned = ctx.session.scalar(select(m.Operator.id).where(
        m.Operator.account_id == ctx.account_id, m.Operator.char_id == char_id)) is not None
    if not owned:
        raise DomainError("UNKNOWN_OPERATOR", "此账号不拥有该干员", 404)
    row = counter(ctx, char_id, owned=True)
    if count < row.count:
        raise DomainError("ACQUISITION_COUNT_CONFLICT", "次数不能小于已有获得记录", 409)
    before = {"count": row.count, "basis": row.basis}
    row.count, row.basis = count, VERIFIED
    return {"charId": char_id, "stream": "STANDARD", "before": before,
            "count": count, "basis": VERIFIED, "evidence": evidence.strip()}


def record_direct(ctx, char_id: str, *, owned: bool, count: int, stream: str = "STANDARD") -> None:
    row = counter(ctx, char_id, owned=owned, stream=stream)
    if row.count + count > 2_000_000_000:
        raise DomainError("ACQUISITION_LIMIT", "干员获得次数超出范围")
    row.count += count


def acquire_standard(ctx, char_id: str) -> dict:
    definition = ctx.data.character(char_id)
    owned = ctx.session.scalar(select(m.Operator.id).where(
        m.Operator.account_id == ctx.account_id, m.Operator.char_id == char_id)) is not None
    row = counter(ctx, char_id, owned=owned)
    rarity = definition.get("rarity")
    if rarity not in {f"TIER_{value}" for value in range(1, 7)}:
        raise DomainError("GAMEDATA_INVALID", "干员稀有度定义无效", 503)
    tier = int(rarity.removeprefix("TIER_"))
    # Ownership decides whether a token is awarded, but certificate thresholds
    # use the independent source counter (including its first-acquisition bonus).
    if row.count == 0:
        certificate, quantity = "4004", 1
    elif tier <= 4:
        certificate, quantity = "4005", {1: 1, 2: 1, 3: 5, 4: 30}[tier]
    else:
        if row.basis == LEGACY and row.count < 6:
            raise DomainError("ACQUISITION_HISTORY_INCOMPLETE", "旧存档缺少此干员的完整获得次数，不能推算凭证", 503)
        certificate = "4004"
        quantity = (8 if tier == 5 else 15) if row.count >= 6 else (5 if tier == 5 else 10)
    # Validate the certificate before changing the character/token state.
    expected_type = "HGG_SHD" if certificate == "4004" else "LGG_SHD"
    if ctx.data.item(certificate)["itemType"] != expected_type:
        raise DomainError("GAMEDATA_INVALID", "凭证类型定义不匹配", 503)
    op, is_new = ctx.acquire_operator(char_id)
    ctx.change_item(certificate, quantity)
    token = definition.get("potentialItemId")
    item_get = ([] if is_new else [{"id": token, "count": 1, "type": ctx.data.item(token)["itemType"]}])
    item_get.append({"id": certificate, "count": quantity, "type": expected_type})
    ctx.emit("OperatorAcquired", char_id=char_id, stream="STANDARD", policy_version=POLICY,
             acquisition_count=row.count, is_new=is_new)
    return {"charInstId": op.id, "charId": char_id, "isNew": is_new, "itemGet": item_get,
            "potent": {"delta": int(not is_new), "now": ctx.balance(token) if token else 0}}


def acquire_classic(ctx, char_id: str) -> dict:
    """Frozen native CLASSIC_SHD_RULE: 10 on entry; duplicate 1/5/50/100.

    Kernel certificates do not increase after the sixth acquisition. Kernel
    tokens and acquisition source remain separate; ownership is shared.
    """
    definition = ctx.data.character(char_id)
    owned = ctx.session.scalar(select(m.Operator.id).where(
        m.Operator.account_id == ctx.account_id, m.Operator.char_id == char_id)) is not None
    tier = definition.get("rarity")
    if tier not in {"TIER_3", "TIER_4", "TIER_5", "TIER_6"}:
        raise DomainError("GAMEDATA_INVALID", "中坚干员星级定义无效", 503)
    token = definition.get("classicPotentialItemId")
    certificate = "classic_normal_ticket"
    if (not token or ctx.data.item(token)["itemType"] != "MATERIAL"
            or ctx.data.item(certificate)["itemType"] != "CLASSIC_SHD"):
        raise DomainError("GAMEDATA_INVALID", "中坚信物或通用凭证定义无效", 503)
    row = counter(ctx, char_id, owned=owned, stream="CLASSIC")
    quantity = {"TIER_3": 1, "TIER_4": 5, "TIER_5": 50, "TIER_6": 100}[tier] if row.count else 10
    op, is_new = ctx.acquire_operator(char_id, stream="CLASSIC")
    ctx.change_item(certificate, quantity)
    rewards = ([] if is_new else [{"id": token, "count": 1, "type": "MATERIAL"}])
    rewards.append({"id": certificate, "count": quantity, "type": "CLASSIC_SHD"})
    ctx.emit("OperatorAcquired", char_id=char_id, stream="CLASSIC", is_new=is_new,
             policy_version="TERRALOCAL_CLASSIC_ACQUISITION_V1")
    return {"charInstId": op.id, "charId": char_id, "isNew": is_new, "itemGet": rewards,
            "potent": {"delta": int(not is_new), "now": ctx.balance(token)}}
