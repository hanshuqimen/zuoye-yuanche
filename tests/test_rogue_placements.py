"""Authored placement counterexamples; frozen90-stage audit is local evidence."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_roguelike_map import map_data as map_data

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_map import Column, Entry, Plan, admit_wire, generate
from terralocal.server.gamedata.rogue_map import FirstThemeMapCatalog
from terralocal.server.gamedata.rogue_placements import AUTHORED_POLICY, AUTHORED_TABLE, StagePlacements


def policy():
    return {"schema": 1, "policy": AUTHORED_POLICY,
            "regions": {"ordinary": ["floor"], "emergency": ["hidden"], "boss": ["floor"]}}


def rules(catalog, value=None):
    return StagePlacements(catalog.stages, catalog.zones, catalog.portal_zones, policy() if value is None else value)


def test_region_pools_are_explicit_immutable_and_do_not_imply_unlock_or_weight(map_data):
    p = rules(map_data.rogue_map)
    assert p.pool("floor", "BATTLE_NORMAL") == ("ordinary",)
    assert p.pool("floor", "BATTLE_ELITE") == ()
    assert p.pool("hidden", "BATTLE_ELITE") == ("emergency",)
    p.require("ordinary", "floor")
    for stage, zone in (("ordinary", "hidden"), ("emergency", "floor"), ("unknown", "floor")):
        with pytest.raises(DomainError) as exc:
            p.require(stage, zone)
        assert exc.value.code == "ROGUE_STAGE_REGION" and exc.value.status == 409
    with pytest.raises(TypeError):
        p.regions["ordinary"] = ("hidden",)
    for zone, kind in (("missing", "BATTLE_NORMAL"), ("portal", "BATTLE_NORMAL"), ("floor", "INCIDENT")):
        with pytest.raises(DomainError):
            p.pool(zone, kind)


def test_plan_and_saved_wire_cannot_place_a_stage_on_another_region(map_data, monkeypatch):
    c = map_data.rogue_map
    spec = Plan("floor", (Column(1, 1, (Entry("BATTLE_NORMAL", 1, "ordinary"),)),), 0)
    good = generate(map_data, spec, 10).wire()
    monkeypatch.setattr(c, "placements", rules(c))
    assert admit_wire(c, good).wire() == good
    with pytest.raises(DomainError, match="区域"):
        replace(spec, zone_id="hidden").validate(c)
    good["id"] = "hidden"
    with pytest.raises(DomainError, match="区域"):
        admit_wire(c, good)


def test_unknown_client_stage_catalog_cannot_guess_a_floor_from_identifiers(map_data):
    table = deepcopy(map_data.table("roguelike_topic_table"))
    old = table["details"]["rogue_1"]["stages"].pop("ordinary")
    table["details"]["rogue_1"]["stages"]["ro1_n_1_1"] = old | {"id": "ro1_n_1_1"}
    table["details"]["rogue_1"]["stages"]["emergency"]["linkedStageId"] = "ro1_n_1_1"
    source = SimpleNamespace(rogue_topics=map_data.rogue_topics, manifest={"tables": {"roguelike_topic_table": "a" * 64}},
                             table=lambda name: table)
    with pytest.raises(DomainError) as exc:
        FirstThemeMapCatalog(source)
    assert exc.value.code == "ROGUE_PLACEMENT_INCOMPATIBLE"


@pytest.mark.parametrize("damage", ["schema", "policy", "missing-stage", "extra-stage", "unknown-zone",
    "portal", "duplicate-zone", "zone-type", "regions-type", "extra-field"])
def test_malformed_explicit_policies_do_not_acquire_default_eligibility(map_data, damage):
    value = policy()
    if damage == "schema":
        value["schema"] = True
    elif damage == "policy":
        value["policy"] = "guessed"
    elif damage == "missing-stage":
        value["regions"].pop("boss")
    elif damage == "extra-stage":
        value["regions"]["missing"] = ["floor"]
    elif damage == "unknown-zone":
        value["regions"]["ordinary"] = ["missing"]
    elif damage == "portal":
        value["regions"]["ordinary"] = ["portal"]
    elif damage == "duplicate-zone":
        value["regions"]["ordinary"] = ["floor", "floor"]
    elif damage == "zone-type":
        value["regions"]["ordinary"] = [True]
    elif damage == "regions-type":
        value["regions"] = []
    else:
        value["defaultZone"] = "floor"
    with pytest.raises(DomainError):
        rules(map_data.rogue_map, value)


def test_authored_data_is_explicitly_labelled_and_binds_its_own_table(map_data):
    assert map_data.rogue_map.placements.policy == AUTHORED_POLICY
    assert AUTHORED_TABLE in map_data.manifest["tables"]
