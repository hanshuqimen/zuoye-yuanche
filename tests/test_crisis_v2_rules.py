"""Authored graph fixtures exercising the frozen native model contract.

No official tables, historical player states, client assets, or claimed native
playthroughs are included. Selection admission is a local server safeguard.
"""

import copy
from dataclasses import FrozenInstanceError

import pytest

from terralocal.server.gamedata.crisis_v2 import CLIENT_ELF_SHA256, CrisisV2MapRules, NodeStatus


def source():
    def node(kind, adjacent, *, rune=None, bag=None, group=None):
        return {"nodeType": kind, "runeId": rune, "slotPackId": bag,
                "mutualExclusionGroup": group, "adjacentNodeList": adjacent}

    return {
        "nodeDataMap": {
            "start": node("START", ["low", "high", "branch"]),
            "low": node("NORMAL", ["start", "bridge"], rune="low", bag="bag", group="group"),
            "high": node("NORMAL", ["start", "bridge"], rune="high", bag="bag", group="group"),
            "bridge": node("KEYPOINT", ["low", "high", "end", "locked"]),
            "end": node("NORMAL", ["bridge"], rune="end", bag="bag"),
            "locked": node("NORMAL", ["bridge"], rune="locked", bag="bag"),
            "branch": node("NORMAL", ["start", "reward"], rune="branch"),
            "reward": node("TREASURE", ["branch"], rune=" "),
            "island": node("NORMAL", [], rune="island"),
        },
        "runeDataMap": {key: {"runeId": key, "score": score, "dimension": dimension}
                        for key, score, dimension in [("low", 10, 0), ("high", 40, 0), ("end", 20, 1),
                                                       ("locked", 30, 2), ("branch", 5, -1), ("island", 50, 5)]},
        "bagDataMap": {"bag": {"slotPackId": "bag", "mapId": "map", "rewardScore": 7, "dimension": 3}},
        "exclusionDataMap": {"group": {"defaultSlotId": "low"}},
        "dailyRuneUnlcokDataMap": {"locked": {"startTs": 123, "mapAttachOn": "other-map"}},
        "dimensionItemList": [{"maxScore": 1} for _ in range(6)],
    }


def load(detail=None, *, data_hash="a" * 64, elf=CLIENT_ELF_SHA256):
    return CrisisV2MapRules("map", source() if detail is None else detail,
                           data_hash=data_hash, client_elf_sha256=elf)


def player(*, locked=None, challenge=0):
    return {"rune": {}, "challenge": {"bridge": challenge},
            "exRunes": {} if locked is None else {"locked": locked}}


def test_configured_default_not_highest_score_controls_bag_target():
    rules = load()
    low = rules.evaluate(["low", "end"], player(), permanent=True)
    high = rules.evaluate(["high", "end"], player(), permanent=True)
    assert low.bag_progress["bag"].target == high.bag_progress["bag"].target == 30
    assert low.bag_progress["bag"].current == 30
    assert high.bag_progress["bag"].current == 60
    assert low.dimension_scores == (10, 20, 0, 7, 0, 0)
    assert high.dimension_scores == (40, 20, 0, 7, 0, 0)
    assert high.total_score == 67
    assert rules.display_maxima == (1,) * 6
    assert "bridge" in high.selected_nodes and high.rune_slots == ("end", "high")


def test_submitting_a_more_difficult_alternative_does_not_require_the_default_slot():
    result = load().evaluate(["high"], player(), permanent=True)
    # Current >= target, not equality and not every member selected.
    assert result.bag_progress["bag"].current == 40
    assert result.bag_progress["bag"].target == 30
    assert result.bag_progress["bag"].complete
    assert result.total_score == 47


@pytest.mark.parametrize("default", [None, ""])
def test_an_exclusion_can_have_no_default_and_does_not_invent_a_maximum(default):
    detail = source()
    detail["exclusionDataMap"]["group"]["defaultSlotId"] = default
    rules = load(detail)
    low = rules.evaluate(["low"], player(), permanent=True)
    high = rules.evaluate(["high"], player(), permanent=True)
    assert low.bag_progress["bag"].target == high.bag_progress["bag"].target == 20
    assert not low.bag_progress["bag"].complete
    assert high.bag_progress["bag"].complete


def test_bag_membership_does_not_make_special_nodes_normal_runes():
    detail = source()
    for key in ("bridge", "reward"):
        detail["nodeDataMap"][key]["slotPackId"] = "bag"
    result = load(detail).evaluate(["low", "end", "branch"], player(), permanent=True)
    assert result.bag_progress["bag"].target == result.bag_progress["bag"].current == 30
    assert result.total_score == 37


def test_unknown_known_locked_and_unlocked_extra_runes_have_distinct_effects():
    rules = load()
    for state, unknown, available, target in [(0, True, False, 30), (1, False, False, 30),
                                               (2, False, True, 60), (3, False, True, 60)]:
        result = rules.evaluate(["low", "end"], player(locked=state), permanent=True)
        assert ("locked" in result.unknown_nodes) is unknown
        assert ("locked" in result.available_nodes) is available
        assert result.bag_progress["bag"].target == target
        if available:
            chosen = rules.evaluate(["low", "end", "locked"], player(locked=state), permanent=True)
            assert chosen.dimension_scores == (10, 20, 30, 7, 0, 0)
        else:
            with pytest.raises(ValueError, match="不可用"):
                rules.evaluate(["low", "locked"], player(locked=state), permanent=True)
    daily = rules.evaluate(["low"], player(locked=3), permanent=False)
    assert "locked" in daily.unknown_nodes and "locked" not in daily.available_nodes


def test_challenge_state_adds_a_start_without_inventing_an_unlocked_path():
    rules = load()
    with pytest.raises(ValueError, match="连接"):
        rules.evaluate(["end"], player(), permanent=True)
    result = rules.evaluate(["end"], player(challenge=1), permanent=True)
    assert result.start_nodes == {"start", "bridge"}
    assert result.selected_nodes == {"end"}
    assert result.dimension_scores == (0, 20, 0, 0, 0, 0)


def test_node_status_is_one_edge_from_the_selected_set():
    rules = load()
    empty = rules.evaluate([], player(), permanent=True)
    assert rules.node_status("start", empty) == NodeStatus.SELECTED
    assert rules.node_status("low", empty) == NodeStatus.REACHABLE
    assert rules.node_status("bridge", empty) == NodeStatus.UNREACH
    assert rules.node_status("end", empty) == NodeStatus.UNREACH
    assert rules.node_status("island", empty) == NodeStatus.DISABLE
    assert rules.node_status("locked", empty) == NodeStatus.DISABLE
    assert rules.node_status(None, empty) == NodeStatus.DISABLE
    selected = rules.evaluate(["low"], player(), permanent=True)
    assert rules.node_status("bridge", selected) == NodeStatus.SELECTED
    assert rules.node_status("end", selected) == NodeStatus.REACHABLE


def test_duplicate_slots_are_idempotent_and_dimensionless_runes_only_affect_bag_progress():
    rules = load()
    once = rules.evaluate(["branch", "high"], player(), permanent=True)
    duplicate = rules.evaluate(["high", "branch", "high", "branch"], player(), permanent=True)
    assert duplicate == once
    assert once.dimension_scores == (40, 0, 0, 7, 0, 0)
    assert "reward" not in once.selected_nodes
    assert rules.node_status("reward", once) == NodeStatus.REACHABLE
    detail = source()
    detail["nodeDataMap"]["branch"]["slotPackId"] = "bag"
    bagged = load(detail).evaluate(["branch", "low", "end"], player(), permanent=True)
    assert bagged.bag_progress["bag"].target == bagged.bag_progress["bag"].current == 35
    assert bagged.dimension_scores == (10, 20, 0, 7, 0, 0)


def test_zero_over_zero_completes_in_score_projection_without_awarding_currency():
    detail = source()
    detail["bagDataMap"]["empty"] = {"slotPackId": "empty", "mapId": "map", "dimension": 4, "rewardScore": 9}
    result = load(detail).evaluate([], player(), permanent=True)
    assert result.bag_progress["empty"].current == result.bag_progress["empty"].target == 0
    assert result.bag_progress["empty"].complete
    assert result.dimension_scores == (0, 0, 0, 0, 9, 0)


def test_locked_node_blocks_availability_until_player_extra_state_unlocks_it():
    detail = source()
    detail["nodeDataMap"]["end"]["adjacentNodeList"] = ["locked"]
    detail["nodeDataMap"]["bridge"]["adjacentNodeList"] = ["low", "high", "locked"]
    detail["nodeDataMap"]["locked"]["adjacentNodeList"] = ["bridge", "end"]
    rules = load(detail)
    with pytest.raises(ValueError, match="不可用"):
        rules.evaluate(["low", "end"], player(locked=1), permanent=True)
    # Availability alone cannot bridge an unselected normal node.
    with pytest.raises(ValueError, match="连接"):
        rules.evaluate(["low", "end"], player(locked=2), permanent=True)
    result = rules.evaluate(["low", "locked", "end"], player(locked=2), permanent=True)
    assert result.total_score == 67


@pytest.mark.parametrize("slots", [["low", "high"], ["start"], ["bridge"], ["reward"], ["missing"],
                                   ["island"], [True], "low", None])
def test_invalid_or_conflicting_requests_cannot_change_player_data(slots):
    state = player()
    before = copy.deepcopy(state)
    with pytest.raises(ValueError):
        load().evaluate(slots, state, permanent=True)
    assert state == before


@pytest.mark.parametrize("damage", ["rune", "bag", "group", "default", "neighbor", "asymmetry", "type",
                                   "bool_score", "overflow", "dimensions", "bag_map", "lock"])
def test_unmatched_or_unsafe_configuration_is_rejected_without_a_default(damage):
    detail = source()
    if damage in {"rune", "bag", "group"}:
        detail["nodeDataMap"]["low"][{"rune": "runeId", "bag": "slotPackId",
                                       "group": "mutualExclusionGroup"}[damage]] = "missing"
    elif damage == "default":
        detail["exclusionDataMap"]["group"]["defaultSlotId"] = "branch"
    elif damage == "neighbor":
        detail["nodeDataMap"]["low"]["adjacentNodeList"].append("missing")
    elif damage == "asymmetry":
        detail["nodeDataMap"]["start"]["adjacentNodeList"].remove("low")
    elif damage == "type":
        detail["nodeDataMap"]["low"]["nodeType"] = {}
    elif damage == "bool_score":
        detail["runeDataMap"]["low"]["score"] = True
    elif damage == "overflow":
        detail["runeDataMap"]["low"]["score"] = 2**31 - 1
    elif damage == "dimensions":
        detail["dimensionItemList"].pop()
    elif damage == "bag_map":
        detail["bagDataMap"]["bag"]["mapId"] = "other"
    else:
        detail["dailyRuneUnlcokDataMap"]["missing"] = {}
    with pytest.raises(ValueError):
        load(detail)


def test_compiled_rules_and_results_do_not_alias_source_or_other_versions():
    detail = source()
    rules = load(detail)
    first = rules.evaluate(["low"], player(), permanent=True)
    detail["runeDataMap"]["low"]["score"] = 999
    detail["nodeDataMap"]["low"]["adjacentNodeList"].clear()
    assert rules.evaluate(["low"], player(), permanent=True) == first
    with pytest.raises(FrozenInstanceError):
        rules.data_hash = "b" * 64
    with pytest.raises(TypeError):
        rules.nodes["low"] = rules.nodes["high"]
    with pytest.raises(TypeError):
        first.bag_progress["bag"] = first.bag_progress["bag"]
    with pytest.raises(ValueError, match="其他地图或版本"):
        load(data_hash="b" * 64).node_status("low", first)
    with pytest.raises(ValueError, match="指纹"):
        load(elf="b" * 64)


@pytest.mark.parametrize("state", [None, {}, {"rune": {}, "challenge": {}},
                                  {"rune": {"low": True}, "challenge": {}, "exRunes": {}},
                                  {"rune": {}, "challenge": {"low": 1}, "exRunes": {}}])
def test_missing_or_mismatched_player_state_does_not_synthesize_unlocks(state):
    with pytest.raises(ValueError):
        load().evaluate(["low"], state, permanent=True)
