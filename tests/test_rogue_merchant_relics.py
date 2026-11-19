"""Normal merchant terms, separate from effect admission and random selection."""

import copy
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from terralocal.server.gamedata import rogue_merchant_relics
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_merchant_relics import (
    SOURCES,
    FirstThemeMerchantRelics,
)

A11 = "rogue_1_relic_a11"
N04 = "rogue_1_relic_n04"
R28 = "rogue_1_relic_r28"


def fixture_data(*, extra=False):
    # Small authored identity fixtures; complete effect adapters are delegated
    # and separately exercised against actual imported data in the frozen audit.
    rows = [(A11, "NORMAL", None, "055", 2, 11, None)]
    if extra:
        rows += [(N04, "SUPER_RARE", None, "217", 8, 4, "rogue_1_enroll_2"),
                 (R28, "SUPER_RARE", "拥有不小于15名干员时完成游戏结局", "028", 1, 28, None)]
    detail = {"items": {"qa-gold": {"type": "GOLD"}}, "archiveComp": {"relic": {"relic": {}}},
              "enrolls": {"rogue_1_enroll_2": {"enrollId": "rogue_1_enroll_2", "enrollTime": 100}},
              "gameConst": {"goldItemId": "qa-gold"}}
    entries = {}
    for key, rarity, condition, order, group, sort, enroll in rows:
        detail["items"][key] = {"id": key, "type": "RELIC", "iconId": key,
                               "rarity": rarity, "unlockCondDesc": condition}
        detail["archiveComp"]["relic"]["relic"][key] = {"relicId": key, "isSpRelic": False,
            "enrollId": enroll, "orderId": order, "relicGroupId": group, "relicSortId": sort}
        entries[key] = SimpleNamespace(special=False, enrollment=enroll)
    calls = []
    data = SimpleNamespace(table=lambda name: {"details": {"rogue_1": detail}}, manifest={"hash": "a" * 64},
        rogue_topics=SimpleNamespace(topic=lambda key: None),
        rogue_relic_archive=SimpleNamespace(entries=entries),
        rogue_recruit_costs=SimpleNamespace(modifiers={R28: object()}, fingerprint="b" * 64),
        rogue_battle_attributes=SimpleNamespace(require=calls.append, fingerprint="c" * 64))
    return data, detail, calls


def scope(**changes):
    return {"topic": "rogue_1", "mode": "NORMAL", "grade": 0, "at": 100,
            "collection_state": 1, "owned": False} | changes


def test_catalog_separates_mechanical_capability_from_normal_merchant_availability():
    data, _, calls = fixture_data(extra=True)
    value = FirstThemeMerchantRelics(data)
    assert len(SOURCES) == 61 and sum(price is not None for price, _ in SOURCES.values()) == 47
    assert len(value.entries) == 3 and set(calls) == {A11, N04}
    assert value.offer("0", A11, **scope()).price == 8
    assert value.offer("1", N04, **scope()).price == 16
    with pytest.raises(ValueError):
        value.offer("2", R28, **scope(collection_state=2))
    assert value.entries[R28].price is None
    with pytest.raises(TypeError):
        value.entries[A11] = value.entries[N04]
    with pytest.raises(FrozenInstanceError):
        value.entries[A11].price = 0


@pytest.mark.parametrize("change", [
    {"topic": "rogue_2"}, {"mode": "EXPEDITION"}, {"grade": 1}, {"grade": True},
    {"at": True}, {"at": -1}, {"at": 2**63}, {"collection_state": 0},
    {"collection_state": True}, {"collection_state": 3}, {"owned": True}, {"owned": 0},
])
def test_invalid_or_ineligible_context_never_produces_an_offer(change):
    value = FirstThemeMerchantRelics(fixture_data()[0])
    with pytest.raises(ValueError):
        value.offer("0", A11, **scope(**change))


def test_enrollment_uses_run_start_boundary_and_discovery_is_not_required():
    value = FirstThemeMerchantRelics(fixture_data(extra=True)[0])
    with pytest.raises(ValueError):
        value.offer("0", N04, **scope(at=99))
    assert value.offer("0", N04, **scope(at=100, collection_state=1)) == value.offer(
        "0", N04, **scope(at=100, collection_state=2))


@pytest.mark.parametrize("field,value", [("type", "GOLD"), ("rarity", "SUPER_RARE"),
                                       ("iconId", R28), ("unlockCondDesc", "changed")])
def test_changed_identity_does_not_reuse_old_price(field, value):
    data, detail, _ = fixture_data()
    detail["items"][A11][field] = value
    with pytest.raises(ValueError):
        FirstThemeMerchantRelics(data)


def test_changed_archive_or_effect_adapter_is_not_silently_accepted():
    data, detail, _ = fixture_data()
    detail["archiveComp"]["relic"]["relic"][A11]["isSpRelic"] = True
    with pytest.raises(ValueError):
        FirstThemeMerchantRelics(data)
    detail["archiveComp"]["relic"]["relic"][A11]["isSpRelic"] = False

    def incompatible(_):
        raise ValueError("effect mismatch")

    data.rogue_battle_attributes.require = incompatible
    with pytest.raises(ValueError):
        FirstThemeMerchantRelics(data)


def test_compile_binds_base_terms_and_collection_scope_without_mutating_inputs():
    data, _, _ = fixture_data(extra=True)
    value = FirstThemeMerchantRelics(data)
    collection = {A11: {"state": 1}, N04: {"state": 2}}
    before = copy.deepcopy(collection)
    context = {"topic": "rogue_1", "mode": "NORMAL", "grade": 0, "at": 100,
               "collection": collection, "owned": frozenset()}
    slots = (("0", A11), ("1", N04))
    first = value.compile("merchant-a", slots, **context)
    again = value.compile("merchant-a", slots, **context)
    assert first.digest == again.digest and collection == before
    assert [(o.item_id, o.price, o.relic_layer) for o in first.offers.values()] == [(A11, 8, 0), (N04, 16, 0)]
    assert not first.ticket_indices
    other = value.compile("merchant-a", slots, **(context | {"at": 101}))
    assert first.digest != other.digest
    with pytest.raises(ValueError):
        value.compile("merchant-a", slots, **(context | {"owned": frozenset({A11})}))
    collection[A11]["state"] = 0
    with pytest.raises(ValueError):
        value.compile("merchant-a", slots, **context)


@pytest.mark.parametrize("slots", [(), (("0", A11), ("0", N04)), (("0", A11), ("1", A11)),
                                    (("0", "rogue_1_relic_m21"),), (("0", A11, 0),),
                                    ((True, A11),), (("0", []),)])
def test_explicit_selection_rejects_unknown_duplicates_or_client_shaped_input(slots):
    value = FirstThemeMerchantRelics(fixture_data(extra=True)[0])
    with pytest.raises(ValueError):
        value.compile("merchant-a", slots, topic="rogue_1", mode="NORMAL", grade=0, at=100,
                      collection={A11: {"state": 1}, N04: {"state": 2}}, owned=frozenset())


CAPACITY_PRICES = {"rogue_1_relic_a" + str(n): price
                   for n, price in zip(range(35, 41), (8, 8, 8, 12, 12, 16))}


def capacity_data(monkeypatch):
    # Authored identity fixtures, not copied client definitions. Formal-data
    # verification separately binds the production digests and complete effects.
    data, detail, attribute_calls = fixture_data()
    sources, capacity_calls = {}, []
    for number, (key, price) in enumerate(CAPACITY_PRICES.items()):
        item = {"id": key, "type": "RELIC", "iconId": key, "rarity": "QA",
                "unlockCondDesc": None}
        archive = {"relicId": key, "isSpRelic": False, "enrollId": None,
                   "orderId": "QA" + str(number)}
        detail["items"][key] = item
        detail["archiveComp"]["relic"]["relic"][key] = archive
        data.rogue_relic_archive.entries[key] = SimpleNamespace(special=False, enrollment=None)
        sources[key] = (price, fingerprint({"item": item, "archive": archive}))
    monkeypatch.setattr(rogue_merchant_relics, "SOURCES", sources)
    data.rogue_capacity_relics = SimpleNamespace(require=capacity_calls.append, fingerprint="d" * 64)
    return data, capacity_calls, attribute_calls


@pytest.mark.parametrize("key,price", tuple(CAPACITY_PRICES.items()))
def test_capacity_base_price_uses_capacity_effect_adapter(monkeypatch, key, price):
    # This assertion uses production terms before installing authored identities.
    assert SOURCES[key][0] == price
    data, capacity_calls, attribute_calls = capacity_data(monkeypatch)
    value = FirstThemeMerchantRelics(data)
    assert set(capacity_calls) == set(CAPACITY_PRICES) and not attribute_calls
    assert value.offer("0", key, **scope()).price == price


def test_capacity_price_is_not_admitted_with_an_incompatible_effect(monkeypatch):
    data, _, _ = capacity_data(monkeypatch)
    def incompatible(_):
        raise ValueError("capacity effect mismatch")
    data.rogue_capacity_relics.require = incompatible
    with pytest.raises(ValueError, match="capacity effect mismatch"):
        FirstThemeMerchantRelics(data)


def test_capacity_price_does_not_bootstrap_unknown_or_claimed_eligibility(monkeypatch):
    data, _, _ = capacity_data(monkeypatch)
    value = FirstThemeMerchantRelics(data)
    key = "rogue_1_relic_a35"
    for collection in ({}, {key: {"state": 0}}, {key: {"state": True}}):
        with pytest.raises(ValueError):
            value.compile("capacity-shop", (("0", key),), topic="rogue_1", mode="NORMAL", grade=0,
                          at=100, collection=collection, owned=frozenset())


def test_capacity_base_quote_keeps_order_prices_and_existing_quote_immutable(monkeypatch):
    data, _, _ = capacity_data(monkeypatch)
    value = FirstThemeMerchantRelics(data)
    context = {"topic": "rogue_1", "mode": "NORMAL", "grade": 0, "at": 100,
               "collection": {k: {"state": 1} for k in CAPACITY_PRICES}, "owned": frozenset()}
    slots = tuple((str(i), key) for i, key in enumerate(CAPACITY_PRICES))
    quote = value.compile("capacity-shop", slots, **context)
    assert [(o.item_id, o.price) for o in quote.offers.values()] == list(CAPACITY_PRICES.items())
    digest = quote.digest
    assert value.compile("capacity-shop", slots, **context).digest == digest
    # A future catalog price never mutates this immutable quote object.
    key = slots[0][1]
    terms = dict(rogue_merchant_relics.SOURCES)
    terms[key] = (9, terms[key][1])
    monkeypatch.setattr(rogue_merchant_relics, "SOURCES", terms)
    assert FirstThemeMerchantRelics(data).compile("capacity-shop", slots, **context).digest != digest
    assert quote.digest == digest and quote.offers["0"].price == 8
