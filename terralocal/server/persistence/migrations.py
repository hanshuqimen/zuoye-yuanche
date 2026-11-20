"""Alembic-backed version stamps with transactional upgrade functions."""

from types import SimpleNamespace

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import JSON, Column, Integer, MetaData, String, Table, and_, exists, func, select

from terralocal.server.persistence.models import (
    AgreementConsent,
    Base,
    CampaignAccount,
    CampaignBreakClaim,
    CampaignMission,
    CampaignStageProgress,
    CampaignWeek,
    CrisisV2Account,
    CrisisV2Battle,
    CrisisV2MapProgress,
    CrisisV2Season,
    HeadHuntingBanner,
    HomePreset,
    HomePresetSlot,
    HomeRotation,
    LocalCashClaim,
    LocalCashOrder,
    LocalOrder,
    LocalPackClaim,
    LocalPackOrder,
    LowShopProgress,
    OperatorAcquisition,
    OwnedFurniture,
    RogueBankVisit,
    RogueBankWallet,
    RogueBattle,
    RogueBattleLootPlan,
    RogueBattleSettlement,
    RogueFloorCursor,
    RogueGameSettlement,
    RogueMapDraft,
    RogueRecruitOption,
    RogueRunChar,
    RogueRunClosure,
    RogueRunEvent,
    RogueRunRelic,
    RogueRunTicket,
    RogueSceneVisit,
    RogueShopVisit,
    RogueTopicAccount,
    RogueTopicOuter,
    RogueTopicRun,
    ShopCatalogCycle,
    ShopProgress,
    StoryCompletion,
)

LEGACY_REVISION = "0001_normalized_state"
SDK_REVISION = "0002_local_sdk_state"
VOICE_REVISION = "0003_operator_voice"
STORY_REVISION = "0004_story_completion"
RECRUIT_REVISION = "0005_recruitment_state"
HEADHUNTING_REVISION = "0006_headhunting_policy"
NATIVE_BATTLE_REVISION = "0007_native_battle_context"
FURNITURE_REVISION = "0008_furniture_inventory"
ACQUISITION_REVISION = "0009_operator_acquisitions"
BANNER_REVISION = "0010_headhunting_banners"
HOME_REVISION = "0011_home_rotation"
VOUCHER_REVISION = "0012_voucher_shops"
CASH_REVISION = "0013_local_cash_orders"
CLAIM_REVISION = "0014_cash_claims"
PACK_REVISION = "0015_gift_pack_orders"
CAMPAIGN_REVISION = "0016_campaign_state"
WEEK_REVISION = "0017_campaign_weeks"
ROGUE_PROFILE_REVISION = "0018_rogue_topic_state"
ROGUE_INITIAL_REVISION = "0019_rogue_initial_runs"
ROGUE_RECRUIT_REVISION = "0020_rogue_recruitment"
ROGUE_MAP_REVISION = "0021_rogue_map_drafts"
ROGUE_ACTIVATION_REVISION = "0022_rogue_map_activation"
ROGUE_BATTLE_REVISION = "0023_rogue_battle_start"
ROGUE_SETTLEMENT_REVISION = "0024_rogue_battle_settlement"
ROGUE_ENDING_REVISION = "0025_rogue_game_settlement"
ROGUE_SCENE_REVISION = "0026_rogue_scene_visits"
ROGUE_SHOP_REVISION = "0027_rogue_shop_visits"
ROGUE_FLOOR_REVISION = "0028_rogue_floor_cursors"
ROGUE_TRAINING_REVISION = "0029_rogue_training_history"
ROGUE_PAID_REVISION = "0030_rogue_paid_training"
ROGUE_FREE_REVISION = "0031_rogue_free_candidates"
ROGUE_ELITE_REVISION = "0032_rogue_elite_supply"
ROGUE_DIRECT_REVISION = "0033_rogue_direct_supply"
ROGUE_CLOSURE_REVISION = "0034_rogue_run_closures"
ROGUE_BANK_REVISION = "0035_rogue_bank_journals"
ROGUE_BANK_AWARDS_REVISION = "0036_rogue_bank_awards"
ROGUE_LOOT_REVISION = "0037_rogue_battle_loot_plans"
CRISIS_V2_REVISION = "0038_crisis_v2_state"
REVISION = "0039_crisis_v2_battles"
CURRENT_REVISIONS = (ROGUE_DIRECT_REVISION, ROGUE_CLOSURE_REVISION, ROGUE_BANK_REVISION,
                     ROGUE_BANK_AWARDS_REVISION, ROGUE_LOOT_REVISION, CRISIS_V2_REVISION, REVISION)
SUPPORTED_REVISIONS = {LEGACY_REVISION, SDK_REVISION, VOICE_REVISION, STORY_REVISION,
                       RECRUIT_REVISION, HEADHUNTING_REVISION, NATIVE_BATTLE_REVISION, FURNITURE_REVISION,
                       ACQUISITION_REVISION, BANNER_REVISION, HOME_REVISION, VOUCHER_REVISION,
                       CASH_REVISION, CLAIM_REVISION, PACK_REVISION, CAMPAIGN_REVISION, WEEK_REVISION,
                       ROGUE_PROFILE_REVISION, ROGUE_INITIAL_REVISION, ROGUE_RECRUIT_REVISION,
                       ROGUE_MAP_REVISION, ROGUE_ACTIVATION_REVISION, ROGUE_BATTLE_REVISION,
                       ROGUE_SETTLEMENT_REVISION, ROGUE_ENDING_REVISION, ROGUE_SCENE_REVISION,
                       ROGUE_SHOP_REVISION, ROGUE_FLOOR_REVISION, ROGUE_TRAINING_REVISION, ROGUE_PAID_REVISION,
                       ROGUE_FREE_REVISION, ROGUE_ELITE_REVISION, ROGUE_DIRECT_REVISION, ROGUE_CLOSURE_REVISION,
                       ROGUE_BANK_REVISION, ROGUE_BANK_AWARDS_REVISION, ROGUE_LOOT_REVISION,
                       CRISIS_V2_REVISION, REVISION}


def _crisis_v2_tables(connection):
    for entity in (CrisisV2Account, CrisisV2Season, CrisisV2MapProgress, CrisisV2Battle):
        entity.__table__.create(connection, checkfirst=True)


def _direct_recruit_schema(connection, operations):
    columns = {r[1] for r in connection.exec_driver_sql("PRAGMA table_info(rlv2_tickets)")}
    if "direct_pool" not in columns:
        operations.add_column("rlv2_tickets", Column("direct_pool", JSON, nullable=False, server_default="[]"))
    constraints = connection.dialect.get_check_constraints(connection, "rlv2_recruit_options")
    existing = next((c for c in constraints if c["name"] == "rlv2_direct_source"), None)
    if existing:
        values = next((c["sqltext"] for c in constraints if c["name"] == "rlv2_option_values"), "")
        if ("".join(existing["sqltext"].split()).lower() != "kind!='direct'orsource_operator_id>0andsource_operator_idisnotnull"
                or "'DIRECT'" not in values):
            raise ValueError("探索直升招募约束与版本不符；已保留原保存")
        return
    with operations.batch_alter_table("rlv2_recruit_options", recreate="always") as batch:
        batch.drop_constraint("rlv2_option_values", type_="check")
        batch.create_check_constraint("rlv2_option_values",
            "ordinal >= 0 AND hope_cost >= 0 AND kind IN ('NORMAL','THIRD_LOW','UPGRADE','UPGRADE_PAID','FREE','THIRD','DIRECT')")
        batch.create_check_constraint("rlv2_direct_source",
            "kind!='DIRECT' OR source_operator_id>0 AND source_operator_id IS NOT NULL")
    if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("探索直升招募迁移引用不完整；已回滚")


def _elite_recruit_schema(connection, operations):
    columns = {r[1] for r in connection.exec_driver_sql("PRAGMA table_info(rlv2_tickets)")}
    if "elite_pool" not in columns:
        operations.add_column("rlv2_tickets", Column("elite_pool", JSON, nullable=False, server_default="[]"))
    constraints = connection.dialect.get_check_constraints(connection, "rlv2_recruit_options")
    existing = next((c for c in constraints if c["name"] == "rlv2_elite_source"), None)
    if existing:
        values = next((c["sqltext"] for c in constraints if c["name"] == "rlv2_option_values"), "")
        if ("".join(existing["sqltext"].split()).lower() != "kind!='third'or(hope_cost=0andsource_operator_idisnull)"
                or "'THIRD'" not in values):
            raise ValueError("探索精英招募约束与版本不符；已保留原保存")
        return
    with operations.batch_alter_table("rlv2_recruit_options", recreate="always") as batch:
        batch.drop_constraint("rlv2_option_values", type_="check")
        batch.create_check_constraint("rlv2_option_values",
            "ordinal >= 0 AND hope_cost >= 0 AND kind IN ('NORMAL','THIRD_LOW','UPGRADE','UPGRADE_PAID','FREE','THIRD')")
        batch.create_check_constraint("rlv2_elite_source", "kind!='THIRD' OR (hope_cost=0 AND source_operator_id IS NULL)")
    if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("探索精英招募迁移引用不完整；已回滚")


def _free_recruit_schema(connection, operations):
    constraints = connection.dialect.get_check_constraints(connection, "rlv2_recruit_options")
    existing = next((c for c in constraints if c["name"] == "rlv2_free_source"), None)
    if existing:
        sql = "".join(existing["sqltext"].split()).lower()
        values = next((c["sqltext"] for c in constraints if c["name"] == "rlv2_option_values"), "")
        if "kind!='free'or(hope_cost=0andsource_operator_idisnull)" != sql or "'FREE'" not in values:
            raise ValueError("探索临时招募约束与版本不符；已保留原保存")
        return
    with operations.batch_alter_table("rlv2_recruit_options", recreate="always") as batch:
        batch.drop_constraint("rlv2_option_values", type_="check")
        batch.create_check_constraint("rlv2_option_values",
            "ordinal >= 0 AND hope_cost >= 0 AND kind IN ('NORMAL','THIRD_LOW','UPGRADE','UPGRADE_PAID','FREE')")
        batch.create_check_constraint("rlv2_free_source", "kind!='FREE' OR (hope_cost=0 AND source_operator_id IS NULL)")
    if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("探索临时招募迁移引用不完整；已回滚")


def _paid_training_schema(connection, operations):
    constraints = connection.dialect.get_check_constraints(connection, "rlv2_recruit_options")
    if any(c["name"] == "rlv2_option_values" and "UPGRADE_PAID" in c["sqltext"] for c in constraints):
        return
    with operations.batch_alter_table("rlv2_recruit_options", recreate="always") as batch:
        batch.drop_constraint("rlv2_option_values", type_="check")
        batch.drop_constraint("rlv2_upgrade_target", type_="check")
        batch.create_check_constraint("rlv2_option_values",
            "ordinal >= 0 AND hope_cost >= 0 AND kind IN ('NORMAL','THIRD_LOW','UPGRADE','UPGRADE_PAID')")
        batch.create_check_constraint("rlv2_upgrade_target",
            "(kind='UPGRADE' AND target_char_ordinal IS NOT NULL AND target_char_ordinal >= 1 AND hope_cost=0) OR "
            "(kind='UPGRADE_PAID' AND target_char_ordinal IS NOT NULL AND target_char_ordinal >= 1 AND hope_cost>0) OR "
            "(kind NOT IN ('UPGRADE','UPGRADE_PAID') AND target_char_ordinal IS NULL)")
    if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("探索付费晋升迁移引用不完整；已回滚")


def _training_schema(connection, operations):
    """Add history without rewriting offers or saved battle formations."""
    columns = {r[1] for r in connection.exec_driver_sql("PRAGMA table_info(rlv2_recruit_options)")}
    if "target_char_ordinal" not in columns:
        with operations.batch_alter_table("rlv2_recruit_options", recreate="always") as batch:
            batch.add_column(Column("target_char_ordinal", Integer, nullable=True))
            batch.drop_constraint("rlv2_option_values", type_="check")
            batch.create_check_constraint("rlv2_option_values",
                "ordinal >= 0 AND hope_cost >= 0 AND kind IN ('NORMAL','THIRD_LOW','UPGRADE')")
            batch.create_check_constraint("rlv2_upgrade_target",
                "(kind='UPGRADE' AND target_char_ordinal IS NOT NULL AND target_char_ordinal >= 1 AND hope_cost=0) OR "
                "(kind!='UPGRADE' AND target_char_ordinal IS NULL)")
    columns = {r[1] for r in connection.exec_driver_sql("PRAGMA table_info(rlv2_chars)")}
    if "training" not in columns:
        operations.add_column("rlv2_chars", Column("training", JSON, nullable=False, server_default="[]"))
    columns = {r[1] for r in connection.exec_driver_sql("PRAGMA table_info(rlv2_battles)")}
    if "roster_revisions" not in columns:
        operations.add_column("rlv2_battles", Column("roster_revisions", JSON, nullable=False, server_default="{}"))
    if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("探索晋升迁移引用不完整；已回滚")


def _battle_tables(connection):
    RogueBattle.__table__.create(connection, checkfirst=True)
    RogueBattleSettlement.__table__.create(connection, checkfirst=True)


def _floor_schema(connection, operations):
    """Run before the final version stamp, in the same migration transaction."""
    columns = {r[1] for r in connection.exec_driver_sql("PRAGMA table_info(rlv2_battles)")}
    constraints = connection.dialect.get_unique_constraints(connection, "rlv2_battles")
    unique = [r for r in constraints if r["name"] == "uq_rlv2_battle_node"]
    if "zone_index" not in columns or not unique or unique[0]["column_names"] != [
            "run_id", "zone_index", "node_x", "node_y"]:
        with operations.batch_alter_table("rlv2_battles", recreate="always") as batch:
            if "zone_index" not in columns:
                batch.add_column(Column("zone_index", Integer, nullable=False, server_default="1"))
            batch.drop_constraint("uq_rlv2_battle_node", type_="unique")
            batch.create_unique_constraint("uq_rlv2_battle_node", ["run_id", "zone_index", "node_x", "node_y"])
            batch.drop_constraint("rlv2_battle_values", type_="check")
            batch.create_check_constraint("rlv2_battle_values", "zone_index >= 1 AND node_x >= 0 AND node_y >= 0 "
                "AND seed >= 0 AND seed <= 2147483647 AND started_at >= 0 AND login_time >= 0")
    RogueFloorCursor.__table__.create(connection, checkfirst=True)
    from terralocal.server.domain.rogue_floors import POLICY as FLOOR_POLICY
    from terralocal.server.domain.rogue_progress import initial_values

    # Historical explicit sequences were first-floor-only. Add only that exact
    # initial cursor; never invent a completed floor or rewrite their maps.
    drafts = connection.exec_driver_sql("SELECT d.* FROM rlv2_map_drafts d LEFT JOIN rlv2_floor_cursors c "
        "ON c.run_id=d.run_id WHERE c.run_id IS NULL AND d.policy_version=? AND d.activated_at IS NOT NULL",
        (FLOOR_POLICY,)).mappings().all()
    for raw in drafts:
        draft = SimpleNamespace(**dict(raw))
        run = connection.exec_driver_sql("SELECT * FROM rlv2_runs WHERE id=?", (draft.run_id,)).mappings().one()
        connection.execute(RogueFloorCursor.__table__.insert().values(
            **initial_values(SimpleNamespace(**dict(run)), draft)))
    if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("探索楼层迁移引用不完整；已回滚")


def _map_activation(connection, operations):
    # Parent reconstruction must retain every child, not cascade-delete them.
    with operations.batch_alter_table("rlv2_runs", recreate="always") as batch:
        batch.drop_constraint("rlv2_run_state", type_="check")
        batch.create_check_constraint("rlv2_run_state",
            "state IN ('INIT_RELIC','INIT_GROUP','INIT_RECRUIT','MAP_READY','ABANDONED','SETTLED')")
    if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("集成战略迁移后的实体引用不完整；已回滚")


def _home_tables(connection):
    for entity in (HomePreset, HomePresetSlot, HomeRotation):
        entity.__table__.create(connection, checkfirst=True)


def _voucher_tables(connection):
    for entity in (ShopCatalogCycle, ShopProgress, LowShopProgress):
        entity.__table__.create(connection, checkfirst=True)


def _cash_tables(connection):
    LocalCashOrder.__table__.create(connection, checkfirst=True)
    LocalCashClaim.__table__.create(connection, checkfirst=True)


def _legacy_cash_claims(connection):
    # 0013 CONFIRMED orders were already removed from the native pending list.
    # Preserve that behavior instead of showing historical rewards again.
    old = LocalOrder.__table__
    quote = LocalCashOrder.__table__
    claim = LocalCashClaim.__table__
    rows = select(old.c.account_id, old.c.order_id, func.coalesce(old.c.confirmed_at, old.c.created_at)).join(
        quote, and_(old.c.account_id == quote.c.account_id, old.c.order_id == quote.c.order_id)).where(
            old.c.state == "CONFIRMED", ~exists(select(1).where(
                claim.c.account_id == old.c.account_id, claim.c.order_id == old.c.order_id)))
    connection.execute(claim.insert().from_select(["account_id", "order_id", "acknowledged_at"], rows))


def upgrade(engine) -> None:
    with engine.connect() as connection:
        driver = connection.connection.driver_connection
        has_version = driver.execute("SELECT 1 FROM sqlite_master WHERE name='alembic_version'").fetchone()
        original = driver.execute("SELECT version_num FROM alembic_version").fetchone() if has_version else None
        has_runs = driver.execute("SELECT 1 FROM sqlite_master WHERE name='rlv2_runs'").fetchone()
        rebuild = original and original[0] in SUPPORTED_REVISIONS - set(CURRENT_REVISIONS) and has_runs
        # PRAGMA must run outside a transaction; BEGIN IMMEDIATE below still
        # serializes the complete rebuild against other writers/migrators.
        if rebuild:
            driver.execute("PRAGMA foreign_keys=OFF")
        # Serialize startup migrations with normal writes, including a second
        # process attempting to initialize the same portable database.
        connection.info["write"] = True
        try:
            with connection.begin():
                context = MigrationContext.configure(connection)
                operations = Operations(context)
                def stamp():
                    _floor_schema(connection, operations)
                    _training_schema(connection, operations)
                    _paid_training_schema(connection, operations)
                    _free_recruit_schema(connection, operations)
                    _elite_recruit_schema(connection, operations)
                    _direct_recruit_schema(connection, operations)
                    RogueRunClosure.__table__.create(connection, checkfirst=True)
                    RogueBankWallet.__table__.create(connection, checkfirst=True)
                    RogueBankVisit.__table__.create(connection, checkfirst=True)
                    RogueBattleLootPlan.__table__.create(connection, checkfirst=True)
                    _crisis_v2_tables(connection)
                    connection.execute(version.update().values(version_num=REVISION))

                version = Table("alembic_version", MetaData(),
                                Column("version_num", String(64), primary_key=True))
                version.create(connection, checkfirst=True)
                current = connection.execute(select(version.c.version_num)).scalar_one_or_none()
                if current is None:
                    Base.metadata.create_all(connection)
                    connection.execute(version.insert().values(version_num=REVISION))
                elif current in SUPPORTED_REVISIONS - {REVISION}:
                    _crisis_v2_tables(connection)
                    if current in (ROGUE_LOOT_REVISION, CRISIS_V2_REVISION):
                        connection.execute(version.update().values(version_num=REVISION))
                        return
                    if current == ROGUE_BANK_AWARDS_REVISION:
                        RogueBattleLootPlan.__table__.create(connection, checkfirst=True)
                        connection.execute(version.update().values(version_num=REVISION))
                        return
                    if current == ROGUE_BANK_REVISION:
                        columns = {row[1] for row in connection.exec_driver_sql('PRAGMA table_info(rlv2_bank_wallets)')}
                        if "awards" not in columns:
                            operations.add_column("rlv2_bank_wallets", Column("awards", JSON, nullable=False, server_default="[]"))
                        RogueBattleLootPlan.__table__.create(connection, checkfirst=True)
                        connection.execute(version.update().values(version_num=REVISION))
                        return
                    if current in (ROGUE_DIRECT_REVISION, ROGUE_CLOSURE_REVISION):
                        # Additive intent ledger: no parent rebuild or changes
                        # to prior rows, constraints, results or owned assets.
                        RogueRunClosure.__table__.create(connection, checkfirst=True)
                        RogueBankWallet.__table__.create(connection, checkfirst=True)
                        RogueBankVisit.__table__.create(connection, checkfirst=True)
                        RogueBattleLootPlan.__table__.create(connection, checkfirst=True)
                        connection.execute(version.update().values(version_num=REVISION))
                        return
                    if current in (ROGUE_PAID_REVISION, ROGUE_FREE_REVISION, ROGUE_ELITE_REVISION):
                        stamp()
                        return
                    if current == ROGUE_TRAINING_REVISION:
                        stamp()
                        return
                    if current == ROGUE_FLOOR_REVISION:
                        stamp()
                        return
                    if current == ROGUE_SHOP_REVISION:
                        stamp()
                        return
                    RogueShopVisit.__table__.create(connection, checkfirst=True)
                    if current == ROGUE_SCENE_REVISION:
                        stamp()
                        return
                    RogueSceneVisit.__table__.create(connection, checkfirst=True)
                    if current == ROGUE_ENDING_REVISION:
                        stamp()
                        return
                    # Rebuild the parent with FK enforcement temporarily off;
                    # every dependent row and the full operation stay atomic.
                    if has_runs:
                        _map_activation(connection, operations)
                    RogueGameSettlement.__table__.create(connection, checkfirst=True)
                    if current == ROGUE_SETTLEMENT_REVISION:
                        stamp()
                        return
                    if current == ROGUE_BATTLE_REVISION:
                        # In 0023 this table has no incoming child references.
                        # Rebuild before creating the new settlement child.
                        with operations.batch_alter_table("rlv2_battles", recreate="always") as batch:
                            batch.drop_constraint("rlv2_battle_state", type_="check")
                            batch.create_check_constraint("rlv2_battle_state",
                                "state IN ('STARTED','FINISHED','ABANDONED')")
                        RogueBattleSettlement.__table__.create(connection, checkfirst=True)
                        if connection.exec_driver_sql("PRAGMA foreign_key_check").fetchone() is not None:
                            raise ValueError("探索结算迁移引用不完整；已回滚")
                        stamp()
                        return
                    if current == ROGUE_ACTIVATION_REVISION:
                        _battle_tables(connection)
                        stamp()
                        return
                    if current == ROGUE_MAP_REVISION:
                        operations.add_column("rlv2_map_drafts", Column("activated_at", Integer))
                        _battle_tables(connection)
                        stamp()
                        return
                    if current == ROGUE_RECRUIT_REVISION:
                        RogueMapDraft.__table__.create(connection, checkfirst=True)
                        _battle_tables(connection)
                        stamp()
                        return
                    if current == ROGUE_INITIAL_REVISION:
                        # No incoming option/character foreign keys exist in 0019.
                        # Rebuild only this small table, inside the same transaction.
                        with operations.batch_alter_table("rlv2_tickets", recreate="always") as batch:
                            batch.drop_constraint("rlv2_initial_ticket_state", type_="check")
                            batch.create_check_constraint("rlv2_ticket_state", "state IN ('CREATE','ACTIVE','DONE')")
                    for entity in (RogueTopicAccount, RogueTopicOuter, RogueTopicRun,
                                   RogueRunEvent, RogueRunRelic, RogueRunTicket, RogueRecruitOption, RogueRunChar,
                                   RogueMapDraft, RogueBattle, RogueBattleSettlement):
                        entity.__table__.create(connection, checkfirst=True)
                    if current in (ROGUE_PROFILE_REVISION, ROGUE_INITIAL_REVISION):
                        stamp()
                        return
                    if current == WEEK_REVISION:
                        stamp()
                        return
                    for entity in (CampaignAccount, CampaignStageProgress, CampaignBreakClaim, CampaignMission):
                        entity.__table__.create(connection, checkfirst=True)
                    CampaignWeek.__table__.create(connection, checkfirst=True)
                    if current == CAMPAIGN_REVISION:
                        stamp()
                        return
                    if current == PACK_REVISION:
                        stamp()
                        return
                    LocalPackOrder.__table__.create(connection, checkfirst=True)
                    LocalPackClaim.__table__.create(connection, checkfirst=True)
                    if current == CLAIM_REVISION:
                        stamp()
                        return
                    if current == CASH_REVISION:
                        _cash_tables(connection)
                        _legacy_cash_claims(connection)
                        stamp()
                        return
                    if current == VOUCHER_REVISION:
                        _cash_tables(connection)
                        stamp()
                        return
                    if current == HOME_REVISION:
                        _voucher_tables(connection)
                        _cash_tables(connection)
                        stamp()
                        return
                    if current in {ACQUISITION_REVISION, BANNER_REVISION}:
                        HeadHuntingBanner.__table__.create(connection, checkfirst=True)
                        _home_tables(connection)
                        _voucher_tables(connection)
                        _cash_tables(connection)
                        stamp()
                        return
                    if current == LEGACY_REVISION:
                        AgreementConsent.__table__.create(connection)
                        LocalOrder.__table__.create(connection)
                    if current in {LEGACY_REVISION, SDK_REVISION}:
                        operations.add_column("operators", Column("voice_language", String(32),
                                                                    nullable=False, server_default="JP"))
                    if current in {LEGACY_REVISION, SDK_REVISION, VOICE_REVISION}:
                        StoryCompletion.__table__.create(connection)
                    if current not in {RECRUIT_REVISION, HEADHUNTING_REVISION, NATIVE_BATTLE_REVISION,
                                       FURNITURE_REVISION}:
                        for column in [Column("duration_seconds", Integer, nullable=False, server_default="0"),
                                       Column("max_finishes_at", Integer),
                                       Column("retained_tags", JSON, nullable=False, server_default="[]"),
                                       Column("result_char_id", String(96)),
                                       Column("policy_version", String(64)), Column("gamedata_hash", String(64))]:
                            operations.add_column("recruit_slots", column)
                    if current not in {HEADHUNTING_REVISION, NATIVE_BATTLE_REVISION, FURNITURE_REVISION}:
                        for column in [Column("policy_version", String(64)), Column("gamedata_hash", String(64))]:
                            operations.add_column("gacha_pity", column)
                    # Historical battles have no verified native codec/key;
                    # preserve them as null instead of inventing a binding.
                    if current not in {NATIVE_BATTLE_REVISION, FURNITURE_REVISION}:
                        operations.add_column("battle_sessions", Column("native_context", JSON))
                    if current != FURNITURE_REVISION:
                        OwnedFurniture.__table__.create(connection)
                    # Legacy saves lack a complete acquisition ledger. Create
                    # it without fabricating counts from potential/token balances.
                    OperatorAcquisition.__table__.create(connection)
                    HeadHuntingBanner.__table__.create(connection, checkfirst=True)
                    _home_tables(connection)
                    _voucher_tables(connection)
                    _cash_tables(connection)
                    stamp()
                elif current != REVISION:
                    raise ValueError(f"未知数据库版本 {current}；不能覆盖或降级存档")
        finally:
            connection.info["write"] = False
            if rebuild:
                driver.execute("PRAGMA foreign_keys=ON")
