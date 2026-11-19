"""Native QA23 regression: owned relics must survive ordinary defeat display."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from terralocal.server.domain.rogue_settlement import CURRENT_POLICY, TERMINAL_POLICY, pending


def ending(outcome="DEFEAT", policy=CURRENT_POLICY):
    run = SimpleNamespace(level=1, topic_id="rogue_1", mode="NORMAL", band_id="rogue_1_band_1",
                          created_at=100, grade=0, seed=42)
    row = SimpleNamespace(effects={"outcome": outcome, "zone": "zone_1"}, policy_version=policy,
                          created_at=120, battle_id="owned-battle")
    return row, run


@pytest.mark.parametrize("outcome,policy", [("DEFEAT", CURRENT_POLICY), ("DEFEAT", TERMINAL_POLICY),
                                            ("SUCCESS", TERMINAL_POLICY)])
def test_every_ending_displays_the_same_owned_inventory_in_acquisition_order(outcome, policy):
    row, run = ending(outcome, policy)
    held = ("rogue_1_relic_q28", "rogue_1_relic_r13")
    before = deepcopy(vars(row)), deepcopy(vars(run)), held
    event = pending(row, run, (row,), relics=held)
    assert event["type"] == "GAME_SETTLE" and not event["content"]["done"]
    result = event["content"]["result"]
    assert result["record"]["relicList"] == list(held)
    assert result["record"]["cntZone"] == (5 if policy == TERMINAL_POLICY else 1)
    assert result["brief"]["success"] == int(outcome == "SUCCESS")
    assert (vars(row), vars(run), held) == before
    # A caller/client mutating a returned list cannot alter inventory or a
    # later projection, and a projection itself cannot become an acquisition.
    result["record"]["relicList"].clear()
    assert pending(row, run, (row,), relics=held)["content"]["result"]["record"]["relicList"] == list(held)


@pytest.mark.parametrize("outcome,policy", [("DEFEAT", CURRENT_POLICY), ("SUCCESS", TERMINAL_POLICY)])
def test_legacy_no_relic_run_stays_empty_and_does_not_gain_its_starting_band(outcome, policy):
    row, run = ending(outcome, policy)
    assert pending(row, run, (row,))["content"]["result"]["record"]["relicList"] == []


def test_display_inventory_does_not_change_ordinary_floor_count():
    row, run = ending()
    earlier = SimpleNamespace(effects={"zone": "zone_1"})
    row.effects["zone"] = "zone_2"
    record = pending(row, run, (earlier, row), relics=("owned-a",))["content"]["result"]["record"]
    assert record["cntZone"] == 2 and record["relicList"] == ["owned-a"]
