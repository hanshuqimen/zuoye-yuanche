from __future__ import annotations

from pathlib import Path
from threading import Lock, RLock

from sqlalchemy import select

from terralocal.config import Settings
from terralocal.server.compatibility.profile import (
    CAMPAIGN_CLIENT_PROFILE,
    CAMPAIGN_DATA_HASH,
    ROGUE_CLIENT_PROFILE,
    ROGUE_DATA_HASH,
    native_profile,
)
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.sessions import account_receipt_key, authenticate_session, receipt_key
from terralocal.server.gamedata import GameData
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.persistence import models as m
from terralocal.server.persistence.database import Database
from terralocal.server.protocol.delta import diff
from terralocal.server.protocol.sync import SyncDataAssembler


class StartupInputs:
    """Validate startup data and bindings against the supplied save path."""

    def __init__(self, settings: Settings, database_path: Path):
        self.settings = settings
        self.protocol_profile = native_profile(settings.client_profile)
        if settings.client_profile == CAMPAIGN_CLIENT_PROFILE and settings.gamedata_hash != CAMPAIGN_DATA_HASH:
            raise ValueError("独立剿灭测试配置只接受已冻结的19表GameData，不转换原存档")
        if settings.client_profile == ROGUE_CLIENT_PROFILE and settings.gamedata_hash != ROGUE_DATA_HASH:
            raise ValueError("独立集成战略测试配置只接受已冻结的现代主题19表GameData，不转换原存档")
        self.data = GameData(settings.data_dir / "cache" / settings.gamedata_hash,
                             expected_hash=settings.gamedata_hash) if settings.gamedata_hash else None
        if self.data:
            self.data.verify()
        self.rogue_content_source = None
        content_path = settings.data_dir / "rogue_content.json"
        if content_path.exists():
            from terralocal.server.gamedata.rogue_content_specs import read_source

            self.rogue_content_source = read_source(self.require_data(), content_path, database_path)
        if self.data:
            self.data.rogue_content_source = self.rogue_content_source
        self.headhunting_rules = None
        head_path = settings.data_dir / "headhunting_rules.json"
        if head_path.exists():
            from terralocal.server.gamedata.headhunting import HeadHuntingCatalog
            from terralocal.server.gamedata.headhunting_rules import read_rules

            self.headhunting_rules = read_rules(head_path, self.require_data())
            self.data.headhunting = HeadHuntingCatalog(self.data, self.headhunting_rules)
        path = settings.data_dir / "drop_rules.json"
        self.drop_catalog = None
        if path.exists():
            from terralocal.server.gamedata.drops import read_catalog

            self.drop_catalog = read_catalog(path, self.require_data())
        self.drop_rules = self.drop_catalog.rules(self.data) if self.drop_catalog else {}
        self.skin_shop_catalog = None
        path = settings.data_dir / "skin_shop.json"
        if path.exists():
            from terralocal.server.gamedata.skin_shop import read_catalog

            self.skin_shop_catalog = read_catalog(path, self.require_data(), self.protocol_profile)
        self.voucher_shop_catalog = None
        path = settings.data_dir / "voucher_shop.json"
        from terralocal.server.gamedata.voucher_shop import preflight_saved_catalog

        if path.exists():
            from terralocal.server.gamedata.voucher_shop import read_catalog

            self.voucher_shop_catalog = read_catalog(path, self.require_data(), self.protocol_profile)
        preflight_saved_catalog(self.voucher_shop_catalog, database_path)
        if self.data:
            self.data.voucher_shop_catalog = self.voucher_shop_catalog
        self.cash_shop_catalog = None
        path = settings.data_dir / "cash_shop.json"
        if path.exists():
            from terralocal.server.gamedata.cash_shop import frozen_products, read_catalog

            self.cash_shop_catalog = read_catalog(path, self.require_data(), self.protocol_profile,
                                                *frozen_products(settings))
        if self.data:
            self.data.cash_shop_catalog = self.cash_shop_catalog
        self.gift_pack_catalog = None
        path = settings.data_dir / "gift_packs.json"
        from terralocal.server.gamedata.gift_packs import preflight_saved_catalog as preflight_packs

        if path.exists():
            from terralocal.server.gamedata.cash_shop import frozen_products
            from terralocal.server.gamedata.gift_packs import read_catalog

            self.gift_pack_catalog = read_catalog(path, self.require_data(), self.protocol_profile,
                                                  *frozen_products(settings))
            if self.cash_shop_catalog:
                cash_ids = {o.goodId for o in self.cash_shop_catalog.offers}
                pack_ids = {o.goodId for o in self.gift_pack_catalog.all_offers()}
                cash_stores = {o.storeId for o in self.cash_shop_catalog.offers}
                pack_stores = {o.storeId for o in self.gift_pack_catalog.all_offers() if o.storeId is not None}
                if cash_ids & pack_ids or cash_stores & pack_stores:
                    raise ValueError("源石与组合包目录不能使用相同商品或 SDK 标识")
        preflight_packs(self.gift_pack_catalog, database_path)
        if self.data:
            self.data.gift_pack_catalog = self.gift_pack_catalog
        if self.data:
            from terralocal.server.domain.home_rotation import validate_catalog

            validate_catalog(self.data)
        from terralocal.server.domain.campaign import preflight

        preflight(self.data, database_path, require_existing_binding=settings.client_profile == CAMPAIGN_CLIENT_PROFILE)
        from terralocal.server.domain.rogue_topics import preflight as rogue_preflight

        rogue_preflight(self.data, database_path,
                        require_existing_binding=settings.client_profile == ROGUE_CLIENT_PROFILE)

    def require_data(self):
        if not self.data:
            raise DomainError("GAMEDATA_NOT_READY", "请先导入并选择匹配的 GameData", 503)
        return self.data

    def initialize_database(self, database: Database) -> None:
        from terralocal.server.gamedata.gift_packs import admit_catalog as admit_packs
        from terralocal.server.gamedata.voucher_shop import admit_catalog

        database.initialize()
        admit_catalog(self.voucher_shop_catalog, database)
        admit_packs(self.gift_pack_catalog, database)
        self.initialize_home(database)
        self.initialize_campaign(database)
        self.initialize_rogue_topics(database)

    def initialize_rogue_topics(self, database):
        from terralocal.server.domain.rogue_topics import available, initialize, snapshot

        if available(self.data):
            with database.transaction() as session:
                for account in session.scalars(select(m.Account)):
                    ctx = Context(session, self.data, account.id)
                    initialize(ctx)
                    snapshot(ctx)

    def initialize_campaign(self, database):
        from terralocal.server.domain.campaign import available, initialize, snapshot

        if available(self.data):
            with database.transaction() as session:
                for account in session.scalars(select(m.Account)):
                    ctx = Context(session, self.data, account.id)
                    initialize(ctx)
                    snapshot(ctx)

    def initialize_home(self, database):
        from terralocal.server.domain.home_rotation import available, initialize

        if self.data and available(self.data):
            with database.transaction() as session:
                for account in session.scalars(select(m.Account)):
                    initialize(Context(session, self.data, account.id))


class Runtime(StartupInputs):
    def __init__(self, settings: Settings):
        settings.prepare()
        super().__init__(settings, settings.database_path)
        self.maintenance = RLock()
        self.backup_files = Lock()
        # Reject incompatible policies before upgrading or touching a save.
        self.database = Database(settings.database_path)
        try:
            self.initialize_database(self.database)
        except BaseException:
            self.database.close()
            raise

    def mutate(self, token: str, uid: str | None, key: str, operation: str, payload: dict, action,
               *, account_scoped: bool = False) -> dict:
        if not key or len(key) > 120:
            raise DomainError("IDEMPOTENCY_REQUIRED", "写操作需要有效的幂等键")
        hashed = fingerprint({"operation": operation, "payload": payload})
        with self.maintenance, self.database.transaction() as session:
            account, local_session = authenticate_session(session, token, uid)
            session_key = receipt_key(local_session, operation, key)
            namespaced_key = account_receipt_key(operation, key) if account_scoped else session_key
            old = session.get(m.Receipt, (account.id, namespaced_key))
            if account_scoped and old is None:
                old = session.get(m.Receipt, (account.id, session_key))
            if old is not None:
                if old.request_hash != hashed:
                    raise DomainError("IDEMPOTENCY_CONFLICT", "同一幂等键不能提交不同请求", 409)
                if old.key != namespaced_key:
                    # A matching retry in its original session confirms the legacy receipt.
                    session.add(m.Receipt(account_id=account.id, key=namespaced_key,
                                          request_hash=old.request_hash, result=old.result,
                                          created_at=old.created_at))
                return old.result
            ctx = Context(session, self.require_data(), account.id, local_session=local_session)
            from terralocal.server.domain.campaign import available as campaign_available
            from terralocal.server.domain.campaign import initialize as initialize_campaign
            from terralocal.server.domain.campaign_weeks import advance
            from terralocal.server.domain.refresh import last_refreshed_at

            # A client may still hold the prior calendar view at a weekly
            # rollover. Reasserting that view's changes is safe after syncData.
            period_at = last_refreshed_at(ctx) if campaign_available(ctx.data) else ctx.now
            before = SyncDataAssembler(ctx, period_at=period_at).assemble()
            ctx.sanity()
            initialize_campaign(ctx)
            advance(ctx)
            result = action(ctx)
            ctx.profile.revision += 1
            session.flush()
            after = SyncDataAssembler(ctx).assemble()
            envelope = {"result": 0, **result, "playerDataDelta": diff(before, after),
                        "ts": ctx.now, "revision": ctx.profile.revision}
            session.add(m.Receipt(account_id=account.id, key=namespaced_key, request_hash=hashed,
                                  result=envelope, created_at=ctx.now))
            # The enclosing context commits before this response becomes visible to the caller.
            return envelope

    def sync(self, token: str, uid: str | None = None) -> dict:
        from terralocal.server.domain.campaign import initialize as initialize_campaign
        from terralocal.server.domain.campaign_weeks import advance
        from terralocal.server.domain.cash_shop import reconcile_before_sync
        from terralocal.server.domain.gift_packs import reconcile_before_sync as reconcile_packs
        from terralocal.server.domain.mission_stages import reconcile as reconcile_stage_missions
        from terralocal.server.domain.story import reconcile_stages

        with self.maintenance, self.database.transaction() as session:
            account, _ = authenticate_session(session, token, uid)
            ctx = Context(session, self.require_data(), account.id)
            reconcile_before_sync(ctx, self.protocol_profile)
            reconcile_packs(ctx, self.protocol_profile)
            initialize_campaign(ctx)
            if reconcile_stages(ctx):
                ctx.profile.revision += 1
            if reconcile_stage_missions(ctx):
                ctx.profile.revision += 1
            if advance(ctx):
                ctx.profile.revision += 1
            ctx.sanity()
            return {"result": 0, "user": SyncDataAssembler(ctx).assemble(), "ts": ctx.now,
                    "revision": ctx.profile.revision}
