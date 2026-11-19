"""Explicit first-theme quotes, never inferred official prices or pools.

Only a trusted server plan may compile these quotes. The client selects an
index; item IDs, prices and stock never come from its purchase request.
"""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_special_recruit import (
    DIRECT_TICKET_IDS,
    ELITE_TICKET_ID,
    FREE_TICKET_IDS,
)
from terralocal.server.gamedata.roguelike import identifier

POLICY = "rogue1-authored-ticket-shop-v1"
RELIC_POLICY = "rogue1-authored-nonstack-cost-relic-shop-v1"
ATTRIBUTE_POLICY = "rogue1-authored-nonstack-battle-attribute-shop-v1"
GLOBAL_BUFF_POLICY = "rogue1-authored-nonstack-global-buff-shop-v1"
CURRENCY_POLICY = "rogue1-authored-nonstack-scalar-currency-shop-v1"
LIFE_POLICY = "rogue1-authored-nonstack-uncapped-life-shop-v1"
CAPACITY_POLICY = "rogue1-authored-nonstack-capacity-relic-shop-v1"
GOLD_POLICY = "rogue1-authored-nonstack-gold-relic-shop-v1"
RESOURCE_POLICY = "rogue1-authored-resource-layer-relic-shop-v1"
SUPPORT_POLICY = "rogue1-authored-support-tool-shop-v1"


@dataclass(frozen=True)
class Offer:
    index: str
    item_id: str
    price: int
    elite_pool: tuple[str, ...] = ()
    direct_pool: tuple[str, ...] = ()
    relic_layer: int | None = None


@dataclass(frozen=True)
class Shop:
    id: str
    data_hash: str
    gold_id: str
    offers: Mapping[str, Offer]
    digest: str
    evidence: str
    ticket_indices: frozenset[str]
    gold_gains: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))
    support_indices: frozenset[str] = frozenset()


def compile_shop(data, shop_id, offers, *, evidence):
    """Admit an authored quote against actual imported item/ticket references.

    Each slot binds one admitted ticket, explicitly unstacked relic or reviewed
    support tool. The owned transaction/history adapter applies its effect.
    Compilation proves references and bounds, not an official encounter pool.
    """
    identifier(shop_id, "商店方案")
    if type(evidence) is not str or not 1 <= len(evidence) <= 1024:
        raise ValueError("商店方案必须记录来源及本地策略边界")
    if type(offers) is not tuple or not 1 <= len(offers) <= 32:
        raise ValueError("商店方案必须有明确且有限的商品槽位")
    detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
    gold = detail["gameConst"]["goldItemId"]
    identifier(gold, "主题源石锭")
    if detail["items"].get(gold, {}).get("type") != "GOLD":
        raise ValueError("主题货币未匹配源石锭定义")
    admitted, relic_layers, attribute_layers, capacity_layers, gold_layers, gold_gains = {}, {}, {}, {}, {}, {}
    resource_layers, support_tools, global_layers, currency_layers, life_layers = {}, {}, {}, {}, {}
    for offer in offers:
        if not isinstance(offer, Offer):
            raise ValueError("商店商品必须是明确报价")
        identifier(offer.index, "商品索引")
        identifier(offer.item_id, "商品物品")
        if offer.index in admitted or type(offer.price) is not int or not 0 <= offer.price < 2**31:
            raise ValueError("商店商品索引重复或价格越界")
        kind = detail["items"].get(offer.item_id, {}).get("type")
        ordinary = kind == "RECRUIT_TICKET" and offer.item_id in data.rogue_recruit.catalog
        special_ticket = kind == "RECRUIT_TICKET" and offer.item_id in FREE_TICKET_IDS | DIRECT_TICKET_IDS | {ELITE_TICKET_ID}
        special = getattr(data, "rogue_special_recruit", None) if special_ticket else None
        if special_ticket and special is None:
            raise ValueError("此商品缺少明确的特殊招募供给合同")
        temporary = (kind == "RECRUIT_TICKET" and offer.item_id in FREE_TICKET_IDS
                     and offer.item_id in special.tickets)
        elite = kind == "RECRUIT_TICKET" and offer.item_id == ELITE_TICKET_ID
        if elite:
            special.elite_scope(offer.item_id, offer.elite_pool)
        elif offer.elite_pool != () or type(offer.elite_pool) is not tuple:
            raise ValueError("此商品没有精英候选供给合同")
        upgrade = kind == "UPGRADE_TICKET" and offer.item_id in data.rogue_upgrades.tickets
        direct = kind == "RECRUIT_TICKET" and offer.item_id in DIRECT_TICKET_IDS
        if direct:
            special.direct_scope(offer.item_id, offer.direct_pool)
        elif offer.direct_pool != () or type(offer.direct_pool) is not tuple:
            raise ValueError("此商品没有直升候选供给合同")
        relic = kind == "RELIC"
        tool = kind == "ACTIVE_TOOL"
        if tool:
            catalog = data.rogue_support_tools
            if offer.item_id not in catalog.entries or offer.item_id in support_tools.values():
                raise ValueError("支援道具需要逐项核对且不重复的明确商品")
            support_tools[offer.index] = offer.item_id
        if relic:
            from terralocal.server.gamedata.rogue_battle_effects import supported
            from terralocal.server.gamedata.rogue_capacity_relics import supported as capacity_supported
            from terralocal.server.gamedata.rogue_currency_relics import supported as currency_supported
            from terralocal.server.gamedata.rogue_global_buffs import supported as global_supported
            from terralocal.server.gamedata.rogue_gold_relics import supported as gold_supported
            from terralocal.server.gamedata.rogue_life_relics import supported as life_supported
            from terralocal.server.gamedata.rogue_resource_relics import supported as resource_supported

            # An explicit authored no-stack display contract, not an inferred
            # official acquisition floor or a natural-generation/unlock rule.
            if (type(offer.relic_layer) is not int or offer.relic_layer != 0
                    or not (offer.item_id in data.rogue_recruit_costs.modifiers or supported(data, offer.item_id)
                            or capacity_supported(data, offer.item_id) or gold_supported(data, offer.item_id)
                            or resource_supported(data, offer.item_id) or currency_supported(data, offer.item_id)
                            or life_supported(data, offer.item_id))
                    or offer.item_id in {o.item_id for o in admitted.values()}):
                raise ValueError("收藏品需要唯一且明确的无叠层完整效果报价")
            target = (life_layers if life_supported(data, offer.item_id) else
                      currency_layers if currency_supported(data, offer.item_id) else
                      resource_layers if resource_supported(data, offer.item_id) else
                      gold_layers if gold_supported(data, offer.item_id) else
                      relic_layers if offer.item_id in data.rogue_recruit_costs.modifiers else capacity_layers
                      if capacity_supported(data, offer.item_id) else global_layers
                      if global_supported(data, offer.item_id) else attribute_layers)
            target[offer.index] = offer.relic_layer
            if target is gold_layers:
                gold_gains[offer.index] = data.rogue_gold_relics.require(offer.item_id)
            elif target is currency_layers:
                gain = data.rogue_currency_relics.require(offer.item_id).gold
                if gain:
                    gold_gains[offer.index] = gain
        elif offer.relic_layer is not None:
            raise ValueError("票券商品不能声明收藏品层数")
        if not (ordinary or temporary or elite or direct or upgrade or relic or tool):
            raise ValueError("尚未接纳此商品的完整发放效果")
        admitted[offer.index] = offer
    # Order is presentation data and remains part of the immutable quote.
    rule = {"policy": LIFE_POLICY if life_layers else CURRENCY_POLICY if currency_layers else GLOBAL_BUFF_POLICY if global_layers else SUPPORT_POLICY if support_tools
            else RESOURCE_POLICY if resource_layers else GOLD_POLICY if gold_layers
            else CAPACITY_POLICY if capacity_layers else ATTRIBUTE_POLICY if attribute_layers
            else RELIC_POLICY if relic_layers else POLICY,
            "data": data.manifest["hash"], "id": shop_id, "gold": gold,
            "offers": [(o.index, o.item_id, o.price) for o in offers], "evidence": evidence}
    scopes = {o.index: o.elite_pool for o in offers if o.elite_pool}
    if scopes:
        rule["elite_pools"] = scopes  # Preserve every legacy quote digest exactly.
    direct_scopes = {o.index: o.direct_pool for o in offers if o.direct_pool}
    if direct_scopes:
        rule["direct_pools"] = direct_scopes
    if relic_layers:
        rule["cost_relics"] = {"layers": relic_layers, "rules": data.rogue_recruit_costs.fingerprint}
    if attribute_layers:
        rule["battle_attribute_relics"] = {"layers": attribute_layers,
                                           "rules": data.rogue_battle_attributes.fingerprint}
    if global_layers:
        rule["global_buff_relics"] = {"layers": global_layers, "rules": data.rogue_global_buffs.fingerprint}
    if currency_layers:
        rule["scalar_currency_relics"] = {"layers": currency_layers,
            "gold_gains": {key: value for key, value in gold_gains.items() if key in currency_layers},
            "rules": data.rogue_currency_relics.fingerprint}
    if life_layers:
        rule["uncapped_life_relics"] = {"layers": life_layers, "rules": data.rogue_life_relics.fingerprint}
    if capacity_layers:
        rule["capacity_relics"] = {"layers": capacity_layers, "rules": data.rogue_capacity_relics.fingerprint}
    if gold_layers:
        rule["gold_relics"] = {"layers": gold_layers, "gains": gold_gains, "rules": data.rogue_gold_relics.fingerprint}
    if resource_layers:
        rule["resource_relics"] = {"base_layers": resource_layers, "rules": data.rogue_resource_relics.fingerprint}
    if support_tools:
        rule["support_tools"] = {"items": support_tools, "rules": data.rogue_support_tools.fingerprint}
    # Reward allocation follows the imported item kind, never purchase count.
    # This classification itself cannot grant an effect or authorize ownership.
    ticket_indices = frozenset(o.index for o in offers
        if detail["items"][o.item_id]["type"] in ("RECRUIT_TICKET", "UPGRADE_TICKET"))
    return Shop(shop_id, data.manifest["hash"], gold, MappingProxyType(admitted), fingerprint(rule), evidence,
                ticket_indices, MappingProxyType(gold_gains), frozenset(support_tools))
