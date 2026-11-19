"""Normalized state. JSON columns are bounded per-object attributes, never the entire player."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from terralocal.server.json_values import same_json_value


class ProfileFlagsJSON(TypeDecorator):
    impl = JSON
    cache_ok = True

    def compare_values(self, value, previous):
        return same_json_value(value, previous)

    def coerce_compared_value(self, op, value):
        return self.impl.coerce_compared_value(op, value)


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    uid: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    preset: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[int] = mapped_column(Integer)


class PlayerProfile(Base):
    __tablename__ = "player_profiles"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    nickname: Mapped[str] = mapped_column(String(64))
    level: Mapped[int] = mapped_column(default=1)
    exp: Mapped[int] = mapped_column(default=0)
    revision: Mapped[int] = mapped_column(default=0)
    secretary: Mapped[str] = mapped_column(String(96))
    secretary_skin: Mapped[str] = mapped_column(String(128))
    resume: Mapped[str] = mapped_column(String(256), default="")
    registered_at: Mapped[int] = mapped_column(Integer)
    last_online_at: Mapped[int] = mapped_column(Integer)
    flags: Mapped[dict[str, Any]] = mapped_column(ProfileFlagsJSON, default=dict)
    avatar: Mapped[dict[str, Any]] = mapped_column(JSON, default=lambda: {"type": "DEFAULT", "id": "0"})


class HomePreset(Base):
    __tablename__ = "home_presets"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    inst_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    background: Mapped[str] = mapped_column(String(128))
    theme: Mapped[str] = mapped_column(String(128))
    profile_skin: Mapped[str] = mapped_column(String(128))
    profile_sp: Mapped[bool] = mapped_column(Boolean, default=False)


class HomePresetSlot(Base):
    __tablename__ = "home_preset_slots"
    __table_args__ = (ForeignKeyConstraint(["account_id", "inst_id"],
                                         ["home_presets.account_id", "home_presets.inst_id"],
                                         ondelete="CASCADE"), CheckConstraint("position >= 0"))
    account_id: Mapped[int] = mapped_column(primary_key=True)
    inst_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    char_id: Mapped[str] = mapped_column(String(96))
    skin_id: Mapped[str] = mapped_column(String(128))
    skin_sp: Mapped[bool] = mapped_column(Boolean, default=False)


class HomeRotation(Base):
    __tablename__ = "home_rotation"
    __table_args__ = (ForeignKeyConstraint(["account_id", "current_id"],
                                         ["home_presets.account_id", "home_presets.inst_id"]),)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    current_id: Mapped[str] = mapped_column(String(128))


class LocalSession(Base):
    __tablename__ = "local_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[int] = mapped_column(Integer)
    last_sequence: Mapped[int] = mapped_column(default=0)


class AgreementConsent(Base):
    """Acceptance of TerraLocal's own local-storage notice, never official consent."""

    __tablename__ = "agreement_consents"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    accepted_at: Mapped[int] = mapped_column(Integer)


class StoryCompletion(Base):
    __tablename__ = "story_completions"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    story_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    completed_at: Mapped[int] = mapped_column(Integer)


class Currency(Base):
    __tablename__ = "currencies"
    __table_args__ = (CheckConstraint("balance >= 0"),)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    balance: Mapped[int] = mapped_column(default=0)


class InventoryItem(Base):
    __tablename__ = "inventory_items"
    __table_args__ = (CheckConstraint("count >= 0"),)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    count: Mapped[int] = mapped_column(default=0)


class OwnedFurniture(Base):
    __tablename__ = "owned_furniture"
    __table_args__ = (CheckConstraint("count >= 0"),)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    count: Mapped[int] = mapped_column(default=0)


class Consumable(Base):
    __tablename__ = "consumables"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[str] = mapped_column(String(96))
    count: Mapped[int] = mapped_column(default=0)
    expires_at: Mapped[int | None] = mapped_column(Integer)


class SanityState(Base):
    __tablename__ = "sanity_states"
    __table_args__ = (CheckConstraint("current >= 0"), CheckConstraint("maximum > 0"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    current: Mapped[int] = mapped_column(default=82)
    maximum: Mapped[int] = mapped_column(default=82)
    last_recovery_at: Mapped[int] = mapped_column(Integer)
    interval: Mapped[int] = mapped_column(default=360)


class Operator(Base):
    __tablename__ = "operators"
    __table_args__ = (UniqueConstraint("account_id", "char_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    char_id: Mapped[str] = mapped_column(String(96))
    level: Mapped[int] = mapped_column(default=1)
    exp: Mapped[int] = mapped_column(default=0)
    evolve_phase: Mapped[int] = mapped_column(default=0)
    potential: Mapped[int] = mapped_column(default=0)
    skill_level: Mapped[int] = mapped_column(default=1)
    trust: Mapped[int] = mapped_column(default=0)
    default_skill: Mapped[int] = mapped_column(default=0)
    skin: Mapped[str] = mapped_column(String(128))
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    current_module: Mapped[str | None] = mapped_column(String(96))
    voice_language: Mapped[str] = mapped_column(String(32), default="JP", server_default="JP")
    gained_at: Mapped[int] = mapped_column(Integer)


class OperatorSkill(Base):
    __tablename__ = "operator_skills"
    __table_args__ = (UniqueConstraint("operator_id", "skill_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id", ondelete="CASCADE"), index=True)
    skill_id: Mapped[str] = mapped_column(String(96))
    mastery: Mapped[int] = mapped_column(default=0)
    training_complete_at: Mapped[int | None] = mapped_column(Integer)


class OperatorModule(Base):
    __tablename__ = "operator_modules"
    __table_args__ = (UniqueConstraint("operator_id", "module_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id", ondelete="CASCADE"), index=True)
    module_id: Mapped[str] = mapped_column(String(96))
    level: Mapped[int] = mapped_column(default=0)
    unlocked: Mapped[bool] = mapped_column(Boolean, default=False)


class OwnedSkin(Base):
    __tablename__ = "owned_skins"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    skin_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    obtained_at: Mapped[int] = mapped_column(Integer)


class Squad(Base):
    __tablename__ = "squads"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    squad_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))


class SquadSlot(Base):
    __tablename__ = "squad_slots"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    squad_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    slot: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id", ondelete="CASCADE"))
    skill_index: Mapped[int] = mapped_column(default=0)
    module_id: Mapped[str | None] = mapped_column(String(96))


class StageProgress(Base):
    __tablename__ = "stage_progress"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    stage_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    stars: Mapped[int] = mapped_column(default=0)
    start_count: Mapped[int] = mapped_column(default=0)
    clear_count: Mapped[int] = mapped_column(default=0)
    first_clear_claimed: Mapped[bool] = mapped_column(Boolean, default=False)
    unlocked: Mapped[bool] = mapped_column(Boolean, default=False)


class CampaignAccount(Base):
    __tablename__ = "campaign_accounts"
    __table_args__ = (CheckConstraint("initial_fee >= 0 AND initial_fee <= 2147483647"),
                      CheckConstraint("current_fee >= 0 AND current_fee <= 2147483647"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    gamedata_hash: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(64))
    initial_fee: Mapped[int] = mapped_column(Integer)
    current_fee: Mapped[int] = mapped_column(default=0)
    initialized_at: Mapped[int] = mapped_column(Integer)


class CampaignWeek(Base):
    __tablename__ = "campaign_weeks"
    __table_args__ = (CheckConstraint("length(period) = 10"),
                      CheckConstraint("earned_fee >= 0 AND earned_fee <= 2147483647"),
                      CheckConstraint("closed_at IS NULL OR (closed_at >= 0 AND closed_at <= 253402271999)"))
    account_id: Mapped[int] = mapped_column(ForeignKey("campaign_accounts.account_id", ondelete="CASCADE"), primary_key=True)
    period: Mapped[str] = mapped_column(String(10), primary_key=True)
    policy_version: Mapped[str] = mapped_column(String(64))
    earned_fee: Mapped[int] = mapped_column(default=0)
    closed_at: Mapped[int | None] = mapped_column(Integer)


class CampaignStageProgress(Base):
    __tablename__ = "campaign_stage_progress"
    __table_args__ = (CheckConstraint("max_kills >= 0 AND max_kills <= 2147483647"),
                      CheckConstraint("sweep_max_kills IS NULL OR (sweep_max_kills >= 0 AND sweep_max_kills <= 2147483647)"))
    account_id: Mapped[int] = mapped_column(ForeignKey("campaign_accounts.account_id", ondelete="CASCADE"), primary_key=True)
    stage_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    max_kills: Mapped[int] = mapped_column(default=0)
    # A missing sweep entry differs from an independently recorded zero.
    sweep_max_kills: Mapped[int | None] = mapped_column(Integer)


class CampaignBreakClaim(Base):
    __tablename__ = "campaign_break_claims"
    __table_args__ = (ForeignKeyConstraint(["account_id", "stage_id"],
                        ["campaign_stage_progress.account_id", "campaign_stage_progress.stage_id"], ondelete="CASCADE"),
                      CheckConstraint("ladder_index >= 0"),
                      CheckConstraint("fee_add >= 0 AND fee_add <= 2147483647"))
    account_id: Mapped[int] = mapped_column(primary_key=True)
    stage_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    ladder_index: Mapped[int] = mapped_column(primary_key=True)
    fee_add: Mapped[int] = mapped_column(Integer)
    rewards: Mapped[list[dict]] = mapped_column(JSON)
    claimed_at: Mapped[int] = mapped_column(Integer)


class CampaignMission(Base):
    __tablename__ = "campaign_missions"
    __table_args__ = (CheckConstraint("state IN (0, 1, 2)"),
                      CheckConstraint("(state = 2 AND fee_add IS NOT NULL AND claimed_at IS NOT NULL) OR "
                                      "(state != 2 AND fee_add IS NULL AND claimed_at IS NULL)"),
                      CheckConstraint("fee_add IS NULL OR (fee_add >= 0 AND fee_add <= 2147483647)"))
    account_id: Mapped[int] = mapped_column(ForeignKey("campaign_accounts.account_id", ondelete="CASCADE"), primary_key=True)
    mission_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    state: Mapped[int] = mapped_column(default=0)
    fee_add: Mapped[int | None] = mapped_column(Integer)
    claimed_at: Mapped[int | None] = mapped_column(Integer)


class BattleSession(Base):
    __tablename__ = "battle_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    stage_id: Mapped[str] = mapped_column(String(96))
    state: Mapped[str] = mapped_column(String(16))
    sanity_cost: Mapped[int] = mapped_column(Integer)
    practice: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[int] = mapped_column(Integer)
    finished_at: Mapped[int | None] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(Integer)
    squad_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    request_hash: Mapped[str | None] = mapped_column(String(64))
    settlement: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    native_context: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class StageReplay(Base):
    __tablename__ = "stage_replays"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    stage_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    battle_id: Mapped[str] = mapped_column(ForeignKey("battle_sessions.id"))
    replay: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[int] = mapped_column(Integer)


class MissionProgress(Base):
    __tablename__ = "mission_progress"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    mission_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    period: Mapped[str] = mapped_column(String(32), primary_key=True)
    progress: Mapped[int] = mapped_column(default=0)
    claimed: Mapped[bool] = mapped_column(Boolean, default=False)


class RecruitSlot(Base):
    __tablename__ = "recruit_slots"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    slot: Mapped[int] = mapped_column(primary_key=True)
    state: Mapped[str] = mapped_column(String(16), default="IDLE")
    tags: Mapped[list[int]] = mapped_column(JSON, default=list)
    available_tags: Mapped[list[int]] = mapped_column(JSON, default=list)
    started_at: Mapped[int | None] = mapped_column(Integer)
    finishes_at: Mapped[int | None] = mapped_column(Integer)
    seed: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_finishes_at: Mapped[int | None] = mapped_column(Integer)
    retained_tags: Mapped[list[int]] = mapped_column(JSON, default=list, server_default="[]")
    result_char_id: Mapped[str | None] = mapped_column(String(96))
    policy_version: Mapped[str | None] = mapped_column(String(64))
    gamedata_hash: Mapped[str | None] = mapped_column(String(64))


class GachaPity(Base):
    __tablename__ = "gacha_pity"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    pulls_without_six: Mapped[int] = mapped_column(default=0)
    total_pulls: Mapped[int] = mapped_column(default=0)
    guarantee_used: Mapped[bool] = mapped_column(Boolean, default=False)
    rng_counter: Mapped[int] = mapped_column(default=0)
    seed: Mapped[int] = mapped_column(Integer)
    policy_version: Mapped[str | None] = mapped_column(String(64))
    gamedata_hash: Mapped[str | None] = mapped_column(String(64))


class GachaHistory(Base):
    __tablename__ = "gacha_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    banner_id: Mapped[str] = mapped_column(String(96))
    char_id: Mapped[str] = mapped_column(String(96))
    rarity: Mapped[int] = mapped_column(Integer)
    is_new: Mapped[bool] = mapped_column(Boolean)
    drawn_at: Mapped[int] = mapped_column(Integer)


class HeadHuntingBanner(Base):
    __tablename__ = "headhunting_banners"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    pool_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    rules_hash: Mapped[str] = mapped_column(String(64))
    total_pulls: Mapped[int] = mapped_column(default=0)
    guarantee_used: Mapped[bool] = mapped_column(Boolean, default=False)
    double_guarantees: Mapped[int] = mapped_column(default=0)
    first_target: Mapped[str | None] = mapped_column(String(96))
    selected_up: Mapped[dict | None] = mapped_column(JSON)


class OperatorAcquisition(Base):
    __tablename__ = "operator_acquisitions"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    char_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    stream: Mapped[str] = mapped_column(String(16), primary_key=True)
    count: Mapped[int] = mapped_column(default=0)
    basis: Mapped[str] = mapped_column(String(64))


class Building(Base):
    __tablename__ = "buildings"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    control_level: Mapped[int] = mapped_column(default=1)
    last_settled_at: Mapped[int] = mapped_column(Integer)
    clues: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)


class BuildingRoom(Base):
    __tablename__ = "building_rooms"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    room_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    room_type: Mapped[str] = mapped_column(String(32))
    level: Mapped[int] = mapped_column(default=1)
    recipe_id: Mapped[str | None] = mapped_column(String(96))
    accumulated: Mapped[int] = mapped_column(default=0)
    partial_work: Mapped[int] = mapped_column(default=0)
    last_settled_at: Mapped[int] = mapped_column(Integer)
    decoration: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class BuildingOperatorAssignment(Base):
    __tablename__ = "building_assignments"
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id", ondelete="CASCADE"), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    room_id: Mapped[str] = mapped_column(String(32))
    slot: Mapped[int] = mapped_column(Integer)
    morale: Mapped[int] = mapped_column(default=24000000)
    updated_at: Mapped[int] = mapped_column(Integer)


class Mail(Base):
    __tablename__ = "mails"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text)
    sender: Mapped[str] = mapped_column(String(64), default="TerraLocal")
    rewards: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int | None] = mapped_column(Integer)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    claimed: Mapped[bool] = mapped_column(Boolean, default=False)


class Friend(Base):
    __tablename__ = "friends"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    friend_uid: Mapped[str] = mapped_column(String(32), primary_key=True)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SupportUnit(Base):
    __tablename__ = "support_units"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    slot: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id", ondelete="CASCADE"))
    skill_index: Mapped[int] = mapped_column(default=0)


class ShopState(Base):
    __tablename__ = "shop_states"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    offer_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    period: Mapped[str] = mapped_column(String(32), primary_key=True)
    bought: Mapped[int] = mapped_column(default=0)


class ShopCatalogCycle(Base):
    """Immutable admitted supply definition, independent of account purchases."""

    __tablename__ = "shop_catalog_cycles"
    shop_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    period: Mapped[str] = mapped_column(String(32), primary_key=True)
    definition_hash: Mapped[str] = mapped_column(String(64))


class ShopProgress(Base):
    __tablename__ = "shop_progress"
    __table_args__ = (CheckConstraint('"order" >= 1'), CheckConstraint('count IN (0, 1)'))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    progress_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    period: Mapped[str] = mapped_column(String(32), primary_key=True)
    order: Mapped[int] = mapped_column(default=1)
    count: Mapped[int] = mapped_column(default=0)


class LowShopProgress(Base):
    __tablename__ = "low_shop_progress"
    __table_args__ = (CheckConstraint('lgg_cost_total >= 0 AND lgg_cost_total <= 2000000000'),)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    period: Mapped[str] = mapped_column(String(32), primary_key=True)
    cur_group_id: Mapped[str] = mapped_column(String(96))
    lgg_cost_total: Mapped[int] = mapped_column(default=0)


class PurchaseHistory(Base):
    __tablename__ = "purchase_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    shop_id: Mapped[str] = mapped_column(String(96))
    offer_id: Mapped[str] = mapped_column(String(96))
    count: Mapped[int] = mapped_column(Integer)
    cost: Mapped[dict[str, Any]] = mapped_column(JSON)
    purchased_at: Mapped[int] = mapped_column(Integer)


class LocalOrder(Base):
    """Local fulfillment queue. No financial authorization or official order IDs."""

    __tablename__ = "local_orders"
    __table_args__ = (CheckConstraint("state IN ('READY', 'CONFIRMED', 'CANCELLED')"),)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    product_id: Mapped[str] = mapped_column(String(96))
    state: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[int] = mapped_column(Integer)
    confirmed_at: Mapped[int | None] = mapped_column(Integer)


class LocalCashOrder(Base):
    """Server-authored virtual quote; a client callback never sets rewards."""

    __tablename__ = "local_cash_orders"
    __table_args__ = (ForeignKeyConstraint(
        ["account_id", "order_id"], ["local_orders.account_id", "local_orders.order_id"],
        ondelete="CASCADE"),)
    account_id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    gamedata_hash: Mapped[str] = mapped_column(String(64))
    client_profile: Mapped[str] = mapped_column(String(96))
    catalog_hash: Mapped[str] = mapped_column(String(64))
    offer: Mapped[dict[str, Any]] = mapped_column(JSON)
    quote_hash: Mapped[str] = mapped_column(String(64))
    callback_secret_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[int] = mapped_column(Integer)
    approved_at: Mapped[int | None] = mapped_column(Integer)
    fulfillment: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class LocalCashClaim(Base):
    """Client acknowledgment is separate from durable originite fulfillment."""

    __tablename__ = "local_cash_claims"
    __table_args__ = (ForeignKeyConstraint(
        ["account_id", "order_id"], ["local_cash_orders.account_id", "local_cash_orders.order_id"],
        ondelete="CASCADE"),)
    account_id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    acknowledged_at: Mapped[int] = mapped_column(Integer)


class LocalPackOrder(Base):
    """GP quote snapshot and fulfillment, separate from originite bonuses."""

    __tablename__ = "local_pack_orders"
    __table_args__ = (ForeignKeyConstraint(
        ["account_id", "order_id"], ["local_orders.account_id", "local_orders.order_id"],
        ondelete="CASCADE"),)
    account_id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    gamedata_hash: Mapped[str] = mapped_column(String(64))
    client_profile: Mapped[str] = mapped_column(String(96))
    catalog_hash: Mapped[str] = mapped_column(String(64))
    offer: Mapped[dict[str, Any]] = mapped_column(JSON)
    period: Mapped[str] = mapped_column(String(32))
    quote_hash: Mapped[str] = mapped_column(String(64))
    callback_secret_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[int] = mapped_column(Integer)
    approved_at: Mapped[int | None] = mapped_column(Integer)
    fulfillment: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class LocalPackClaim(Base):
    __tablename__ = "local_pack_claims"
    __table_args__ = (ForeignKeyConstraint(
        ["account_id", "order_id"], ["local_pack_orders.account_id", "local_pack_orders.order_id"],
        ondelete="CASCADE"),)
    account_id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    acknowledged_at: Mapped[int] = mapped_column(Integer)


class EventProgress(Base):
    __tablename__ = "event_progress"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    key: Mapped[str] = mapped_column(String(96), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON)


class RogueTopicAccount(Base):
    __tablename__ = "rlv2_accounts"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    gamedata_hash: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(64))
    pinned: Mapped[str | None] = mapped_column(String(128))
    initialized_at: Mapped[int] = mapped_column(Integer)


class RogueTopicOuter(Base):
    __tablename__ = "rlv2_topics"
    account_id: Mapped[int] = mapped_column(ForeignKey("rlv2_accounts.account_id", ondelete="CASCADE"), primary_key=True)
    topic_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    # One bounded theme object, never a whole-player or current-run snapshot.
    state: Mapped[dict[str, Any]] = mapped_column(JSON)


class RogueTopicRun(Base):
    __tablename__ = "rlv2_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("rlv2_accounts.account_id", ondelete="CASCADE"))
    gamedata_hash: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(64))
    topic_id: Mapped[str] = mapped_column(String(128))
    mode: Mapped[str] = mapped_column(String(24))
    grade: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(24))
    seed: Mapped[int] = mapped_column(Integer)
    hp: Mapped[int] = mapped_column(Integer)
    hp_max: Mapped[int] = mapped_column(Integer)
    shield: Mapped[int] = mapped_column(Integer)
    gold: Mapped[int] = mapped_column(Integer)
    hope_max: Mapped[int] = mapped_column(Integer)
    hope_cost: Mapped[int] = mapped_column(Integer)
    squad_capacity: Mapped[int] = mapped_column(Integer)
    level: Mapped[int] = mapped_column(Integer)
    max_level: Mapped[int] = mapped_column(Integer)
    exp: Mapped[int] = mapped_column(Integer)
    band_id: Mapped[str | None] = mapped_column(String(128))
    recruit_group: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[int] = mapped_column(Integer)
    ended_at: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (
        Index("uq_rlv2_active_run", "account_id", unique=True, sqlite_where=text("ended_at IS NULL")),
        CheckConstraint("grade >= 0 AND seed >= 0 AND hp >= 0 AND hp_max >= 0 AND shield >= 0 AND gold >= 0 "
                        "AND hope_cost >= 0 AND hope_max >= hope_cost AND squad_capacity >= 0 "
                        "AND level >= 1 AND max_level >= level AND exp >= 0", name="rlv2_run_values"),
        CheckConstraint("state IN ('INIT_RELIC','INIT_GROUP','INIT_RECRUIT','MAP_READY','ABANDONED','SETTLED')",
                        name="rlv2_run_state"),
    )


class RogueRunClosure(Base):
    """Explicit give-up intent, retained independently of reward confirmation."""

    __tablename__ = "rlv2_run_closures"
    run_id: Mapped[str] = mapped_column(ForeignKey("rlv2_runs.id", ondelete="CASCADE"), primary_key=True)
    policy_version: Mapped[str] = mapped_column(String(64))
    rule_hash: Mapped[str] = mapped_column(String(64))
    facts: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[int] = mapped_column(Integer)
    __table_args__ = (CheckConstraint("created_at >= 0", name="rlv2_closure_time"),)


class RogueGameSettlement(Base):
    """One acknowledged exploration; immutable result and owned progress ledger."""

    __tablename__ = "rlv2_game_settlements"
    run_id: Mapped[str] = mapped_column(ForeignKey("rlv2_runs.id", ondelete="CASCADE"), primary_key=True)
    policy_version: Mapped[str] = mapped_column(String(64))
    rule_hash: Mapped[str] = mapped_column(String(64))
    facts: Mapped[dict[str, Any]] = mapped_column(JSON)
    before: Mapped[dict[str, Any]] = mapped_column(JSON)
    after: Mapped[dict[str, Any]] = mapped_column(JSON)
    response: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[int] = mapped_column(Integer)
    __table_args__ = (CheckConstraint("created_at >= 0", name="rlv2_game_settle_time"),)


class RogueRunEvent(Base):
    __tablename__ = "rlv2_events"
    run_id: Mapped[str] = mapped_column(ForeignKey("rlv2_runs.id", ondelete="CASCADE"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    completed_at: Mapped[int | None] = mapped_column(Integer)


class RogueRunRelic(Base):
    __tablename__ = "rlv2_relics"
    run_id: Mapped[str] = mapped_column(ForeignKey("rlv2_runs.id", ondelete="CASCADE"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[str] = mapped_column(String(128))
    count: Mapped[int] = mapped_column(Integer)
    layer: Mapped[int] = mapped_column(Integer)
    acquired_at: Mapped[int] = mapped_column(Integer)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (CheckConstraint("count > 0 AND layer >= 0", name="rlv2_relic_values"),)


class RogueRunTicket(Base):
    __tablename__ = "rlv2_tickets"
    run_id: Mapped[str] = mapped_column(ForeignKey("rlv2_runs.id", ondelete="CASCADE"), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[str] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[int] = mapped_column(Integer)
    elite_pool: Mapped[list[str]] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    direct_pool: Mapped[list[str]] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    __table_args__ = (CheckConstraint("state IN ('CREATE','ACTIVE','DONE')", name="rlv2_ticket_state"),)


class RogueRecruitOption(Base):
    __tablename__ = "rlv2_recruit_options"
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticket_ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_operator_id: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    hope_cost: Mapped[int] = mapped_column(Integer)
    character: Mapped[dict[str, Any]] = mapped_column(JSON)
    target_char_ordinal: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (
        ForeignKeyConstraint(["run_id", "ticket_ordinal"], ["rlv2_tickets.run_id", "rlv2_tickets.ordinal"],
                             ondelete="CASCADE"),
        CheckConstraint("ordinal >= 0 AND hope_cost >= 0 AND kind IN ('NORMAL','THIRD_LOW','UPGRADE','UPGRADE_PAID','FREE','THIRD','DIRECT')",
                        name="rlv2_option_values"),
        CheckConstraint("kind!='FREE' OR (hope_cost=0 AND source_operator_id IS NULL)", name="rlv2_free_source"),
        CheckConstraint("kind!='THIRD' OR (hope_cost=0 AND source_operator_id IS NULL)", name="rlv2_elite_source"),
        CheckConstraint("kind!='DIRECT' OR source_operator_id>0 AND source_operator_id IS NOT NULL", name="rlv2_direct_source"),
        CheckConstraint("(kind='UPGRADE' AND target_char_ordinal IS NOT NULL AND target_char_ordinal >= 1 AND hope_cost=0) OR "
                        "(kind='UPGRADE_PAID' AND target_char_ordinal IS NOT NULL AND target_char_ordinal >= 1 AND hope_cost>0) OR "
                        "(kind NOT IN ('UPGRADE','UPGRADE_PAID') AND target_char_ordinal IS NULL)", name="rlv2_upgrade_target"),
    )


class RogueRunChar(Base):
    __tablename__ = "rlv2_chars"
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_ordinal: Mapped[int] = mapped_column(Integer)
    option_ordinal: Mapped[int] = mapped_column(Integer)
    training: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    __table_args__ = (
        ForeignKeyConstraint(["run_id", "ticket_ordinal", "option_ordinal"],
                             ["rlv2_recruit_options.run_id", "rlv2_recruit_options.ticket_ordinal",
                              "rlv2_recruit_options.ordinal"], ondelete="CASCADE"),
        UniqueConstraint("run_id", "ticket_ordinal", name="uq_rlv2_ticket_character"),
        CheckConstraint("ordinal >= 1", name="rlv2_character_index"),
    )


class RogueMapDraft(Base):
    """Versioned first-floor or explicit floor-sequence recipe; not a cursor."""

    __tablename__ = "rlv2_map_drafts"
    run_id: Mapped[str] = mapped_column(ForeignKey("rlv2_runs.id", ondelete="CASCADE"), primary_key=True)
    policy_version: Mapped[str] = mapped_column(String(64))
    gamedata_hash: Mapped[str] = mapped_column(String(64))
    seed: Mapped[int] = mapped_column(Integer)
    plan: Mapped[dict[str, Any]] = mapped_column(JSON)
    plan_hash: Mapped[str] = mapped_column(String(64))
    graph: Mapped[dict[str, Any]] = mapped_column(JSON)
    prepared_at: Mapped[int] = mapped_column(Integer)
    activated_at: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (CheckConstraint("prepared_at >= 0 AND seed >= 0", name="rlv2_map_draft_values"),)


class RogueFloorCursor(Base):
    """Owned cursor and append-only completed-floor bindings; maps stay immutable."""

    __tablename__ = "rlv2_floor_cursors"
    run_id: Mapped[str] = mapped_column(ForeignKey("rlv2_runs.id", ondelete="CASCADE"), primary_key=True)
    policy_version: Mapped[str] = mapped_column(String(64))
    map_hash: Mapped[str] = mapped_column(String(64))
    zone_index: Mapped[int] = mapped_column(Integer)
    activated_at: Mapped[int] = mapped_column(Integer)
    journal: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    rule_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (CheckConstraint("zone_index >= 1 AND activated_at >= 0", name="rlv2_floor_cursor_values"),)


class RogueSceneVisit(Base):
    """Immutable node assignment plus ordered, owned scene decisions."""

    __tablename__ = "rlv2_scene_visits"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("rlv2_runs.id", ondelete="CASCADE"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    zone_index: Mapped[int] = mapped_column(Integer)
    node_x: Mapped[int] = mapped_column(Integer)
    node_y: Mapped[int] = mapped_column(Integer)
    program_id: Mapped[str] = mapped_column(String(128))
    policy_version: Mapped[str] = mapped_column(String(64))
    rule_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    before: Mapped[dict[str, Any]] = mapped_column(JSON)
    recruit_count: Mapped[int | None] = mapped_column(Integer)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    prepared_at: Mapped[int] = mapped_column(Integer)
    entered_at: Mapped[int | None] = mapped_column(Integer)
    ended_at: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("run_id", "zone_index", "node_x", "node_y", name="uq_rlv2_scene_node"),
        CheckConstraint("zone_index >= 1 AND node_x >= 0 AND node_y >= 0 AND prepared_at >= 0",
                        name="rlv2_scene_values"),
        CheckConstraint("state IN ('PREPARED','ACTIVE','FINISHED','ABANDONED')", name="rlv2_scene_state"),
    )


class RogueShopVisit(Base):
    """Owned immutable shop quote and append-only purchase bindings."""

    __tablename__ = "rlv2_shop_visits"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("rlv2_runs.id", ondelete="CASCADE"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    zone_index: Mapped[int] = mapped_column(Integer)
    node_x: Mapped[int] = mapped_column(Integer)
    node_y: Mapped[int] = mapped_column(Integer)
    quote: Mapped[dict[str, Any]] = mapped_column(JSON)
    rule_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    before: Mapped[dict[str, Any]] = mapped_column(JSON)
    first_ticket: Mapped[int | None] = mapped_column(Integer)
    purchases: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    prepared_at: Mapped[int] = mapped_column(Integer)
    entered_at: Mapped[int | None] = mapped_column(Integer)
    ended_at: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("run_id", "zone_index", "node_x", "node_y", name="uq_rlv2_shop_node"),
        CheckConstraint("zone_index >= 1 AND node_x >= 0 AND node_y >= 0 AND prepared_at >= 0",
                        name="rlv2_shop_values"),
        CheckConstraint("state IN ('PREPARED','ACTIVE','FINISHED','ABANDONED')", name="rlv2_shop_state"),
    )


class RogueBankWallet(Base):
    """First-theme authoritative balance folded from owned bank visit journals."""

    __tablename__ = "rlv2_bank_wallets"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    gamedata_hash: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(64))
    state: Mapped[dict[str, Any]] = mapped_column(JSON)
    visits: Mapped[int] = mapped_column(Integer)
    head_hash: Mapped[str] = mapped_column(String(64))
    awards: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, server_default="[]")
    __table_args__ = (CheckConstraint("visits >= 0", name="rlv2_bank_wallet_values"),)


class RogueBankVisit(Base):
    """Explicit bank plan and the shared financial log for one owned shop."""

    __tablename__ = "rlv2_bank_visits"
    visit_id: Mapped[str] = mapped_column(ForeignKey("rlv2_shop_visits.id", ondelete="CASCADE"), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    run_id: Mapped[str] = mapped_column(ForeignKey("rlv2_runs.id", ondelete="CASCADE"))
    policy_version: Mapped[str] = mapped_column(String(64))
    plan: Mapped[dict[str, Any]] = mapped_column(JSON)
    plan_hash: Mapped[str] = mapped_column(String(64))
    prepared_at: Mapped[int] = mapped_column(Integer)
    ordinal: Mapped[int | None] = mapped_column(Integer)
    before_bank: Mapped[dict[str, Any]] = mapped_column(JSON)
    faulted_before: Mapped[bool | None] = mapped_column(Boolean)
    journal: Mapped[dict[str, Any]] = mapped_column(JSON)
    __table_args__ = (
        UniqueConstraint("account_id", "ordinal", name="uq_rlv2_bank_visit_order"),
        CheckConstraint("prepared_at >= 0 AND (ordinal IS NULL OR ordinal >= 0)", name="rlv2_bank_visit_values"),
    )


class RogueBattle(Base):
    __tablename__ = "rlv2_battles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    run_id: Mapped[str] = mapped_column(ForeignKey("rlv2_runs.id", ondelete="CASCADE"))
    session_id: Mapped[int] = mapped_column(ForeignKey("local_sessions.id"))
    session_binding: Mapped[str] = mapped_column(String(64))
    gamedata_hash: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(64))
    zone_index: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    node_x: Mapped[int] = mapped_column(Integer)
    node_y: Mapped[int] = mapped_column(Integer)
    stage_id: Mapped[str] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(16))
    seed: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[int] = mapped_column(Integer)
    ended_at: Mapped[int | None] = mapped_column(Integer)
    login_time: Mapped[int] = mapped_column(Integer)
    request_hash: Mapped[str] = mapped_column(String(64))
    squad: Mapped[list[dict[str, Any] | None]] = mapped_column(JSON)
    roster_revisions: Mapped[dict[str, int]] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    __table_args__ = (
        Index("uq_rlv2_account_active_battle", "account_id", unique=True, sqlite_where=text("state='STARTED'")),
        UniqueConstraint("run_id", "zone_index", "node_x", "node_y", name="uq_rlv2_battle_node"),
        CheckConstraint("state IN ('STARTED','FINISHED','ABANDONED')", name="rlv2_battle_state"),
        CheckConstraint("zone_index >= 1 AND node_x >= 0 AND node_y >= 0 AND seed >= 0 AND seed <= 2147483647 "
                        "AND started_at >= 0 AND login_time >= 0", name="rlv2_battle_values"),
    )


class RogueBattleLootPlan(Base):
    """Immutable server-authored extra loot, fixed before the node starts."""

    __tablename__ = "rlv2_battle_loot_plans"
    run_id: Mapped[str] = mapped_column(ForeignKey("rlv2_runs.id", ondelete="CASCADE"), primary_key=True)
    zone_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_x: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_y: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    policy_version: Mapped[str] = mapped_column(String(64))
    gamedata_hash: Mapped[str] = mapped_column(String(64))
    map_hash: Mapped[str] = mapped_column(String(64))
    stage_id: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32))
    spec: Mapped[dict[str, Any]] = mapped_column(JSON)
    rule_hash: Mapped[str] = mapped_column(String(64))
    prepared_at: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        CheckConstraint("zone_index >= 1 AND node_x >= 0 AND node_y >= 0 AND prepared_at >= 0", name="rlv2_loot_plan_values"),
    )


class RogueBattleSettlement(Base):
    """One battle's normalized result, independent loot and claim audit.

    Never stores encrypted telemetry/auth fields or a whole-player snapshot.
    Facts/effects/loot are immutable; claims and acknowledgement are monotone.
    """

    __tablename__ = "rlv2_battle_settlements"
    battle_id: Mapped[str] = mapped_column(ForeignKey("rlv2_battles.id", ondelete="CASCADE"), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("rlv2_runs.id", ondelete="CASCADE"))
    ordinal: Mapped[int] = mapped_column(Integer)
    policy_version: Mapped[str] = mapped_column(String(64))
    rule_hash: Mapped[str] = mapped_column(String(64))
    facts: Mapped[dict[str, Any]] = mapped_column(JSON)
    effects: Mapped[dict[str, Any]] = mapped_column(JSON)
    loot: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    claims: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    # Original bounded journal/snapshot, loaded only for explicit inspection.
    # Ordinary sync never serializes these archives into playerDataDelta.
    records: Mapped[dict[str, object]] = mapped_column(JSON, deferred=True)
    created_at: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("run_id", "ordinal", name="uq_rlv2_settlement_order"),
        CheckConstraint("ordinal >= 0 AND created_at >= 0", name="rlv2_settlement_values"),
    )


class RoguelikeRun(Base):
    __tablename__ = "roguelike_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[str] = mapped_column(String(96))
    state: Mapped[str] = mapped_column(String(16))
    seed: Mapped[int] = mapped_column(Integer)
    floor: Mapped[int] = mapped_column(default=1)
    hp: Mapped[int] = mapped_column(default=1)
    hope: Mapped[int] = mapped_column(default=0)
    coins: Mapped[int] = mapped_column(default=0)
    current_node: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[int] = mapped_column(Integer)


class RogueNode(Base):
    __tablename__ = "rogue_nodes"
    run_id: Mapped[str] = mapped_column(ForeignKey("roguelike_runs.id", ondelete="CASCADE"), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    visited: Mapped[bool] = mapped_column(Boolean, default=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)


class RogueInventory(Base):
    __tablename__ = "rogue_inventory"
    run_id: Mapped[str] = mapped_column(ForeignKey("roguelike_runs.id", ondelete="CASCADE"), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    count: Mapped[int] = mapped_column(default=1)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)


class ServerClockState(Base):
    __tablename__ = "server_clock"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    mode: Mapped[str] = mapped_column(String(16), default="realtime")
    fixed_at: Mapped[int | None] = mapped_column(Integer)
    offset: Mapped[int] = mapped_column(default=0)


class Receipt(Base):
    __tablename__ = "receipts"
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[int] = mapped_column(Integer)


class DomainEvent(Base):
    __tablename__ = "domain_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    occurred_at: Mapped[int] = mapped_column(Integer)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(64))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    action: Mapped[str] = mapped_column(String(96))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[int] = mapped_column(Integer)


class Announcement(Base):
    __tablename__ = "announcements"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    body: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[int] = mapped_column(Integer)
    ends_at: Mapped[int | None] = mapped_column(Integer)
    priority: Mapped[int] = mapped_column(default=0)


Index("one_active_battle", BattleSession.account_id, unique=True, sqlite_where=BattleSession.state == "STARTED")
