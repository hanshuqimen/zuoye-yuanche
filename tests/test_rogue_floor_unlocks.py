"""Completed-floor goal family; synthetic HTTP is not native stage replay."""

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from rogue_qa_rules import add_base_score
from test_rogue_ending import ending_runtime as ending_runtime
from test_rogue_floor_progress import setup
from test_rogue_roster_unlocks import add_conditions, table
from test_rogue_shop_ending import shop_ending_runtime as shop_ending_runtime
from test_rogue_visits import visits_runtime as visits_runtime
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_initial import post
from test_roguelike_state import rows

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.rogue_collection import FirstThemeRelicArchive
from terralocal.server.gamedata.rogue_floor_unlocks import (
    CONDITIONS,
    ZONES,
    FirstThemeFloorUnlocks,
    RunFloors,
    available,
)
from terralocal.server.gamedata.rogue_roster_unlocks import FirstThemeRosterUnlocks
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

R25, A48, A34 = CONDITIONS


def add_floor_conditions(detail):
    detail.setdefault("enrolls", {})
    archive = detail.setdefault("archiveComp", {}).setdefault("relic", {}).setdefault("relic", {})
    for index, (key, row) in enumerate(detail["items"].items()):
        if row.get("type") == "RELIC":
            archive.setdefault(
                key,
                {
                    "relicId": key,
                    "enrollId": None,
                    "isSpRelic": False,
                    "relicGroupId": 1,
                    "relicSortId": index,
                    "orderId": str(index),
                },
            )
    add_conditions(detail)
    for number, name in enumerate(ZONES, 1):
        key = "zone_" + str(number)
        detail.setdefault("zones", {})[key] = {"id": key, "name": name, "isHiddenZone": False}
    for index, (key, (_, description)) in enumerate(CONDITIONS.items(), 300):
        detail["items"].setdefault(key, {"id": key, "type": "RELIC"})["unlockCondDesc"] = description
        detail["relics"].setdefault(key, {"id": key, "buffs": []})
        detail["relicParams"].setdefault(key, {"id": key, "checkCharBoxParams": [], "checkCharBoxTypes": []})
        detail["archiveComp"]["relic"]["relic"].setdefault(
            key,
            {
                "relicId": key,
                "enrollId": None,
                "isSpRelic": False,
                "relicGroupId": 1,
                "relicSortId": index,
                "orderId": str(index),
            },
        )


def source():
    value = table()
    add_floor_conditions(value["details"]["rogue_1"])
    return value


def load(value):
    def zone(key):
        assert key.startswith("zone_")

    data = SimpleNamespace(
        table=lambda name: value,
        manifest={"hash": "a" * 64, "tables": {"roguelike_topic_table": "b" * 64}},
        rogue_topics=SimpleNamespace(topic=lambda topic: SimpleNamespace(start=100)),
        rogue_map=SimpleNamespace(require_zone=zone),
    )
    data.rogue_relic_archive = FirstThemeRelicArchive(data)
    data.rogue_roster_unlocks = FirstThemeRosterUnlocks(data)
    assert available(data)
    return FirstThemeFloorUnlocks(data)


def run(zones, mode="NORMAL", at=200):
    return RunFloors(mode, 0, at, tuple(zones))


@pytest.mark.parametrize(
    "count,expected",
    [(0, (0, 0, 0)), (1, (1, 0, 0)), (2, (1, 1, 0)), (3, (1, 1, 0)), (4, (1, 1, 1)), (5, (1, 1, 1))],
)
def test_entire_unconditional_family_uses_completed_prefix_not_entered_index(count, expected):
    result = load(source()).evaluate((run(["zone_" + str(i) for i in range(1, count + 1)]),))
    assert tuple(result[k].current for k in CONDITIONS) == expected
    assert all(
        result[k].wire() == {"state": n, "progress": [n, 1]}
        for k, n in zip(CONDITIONS, expected, strict=True)
    )


@pytest.mark.parametrize(
    "zones",
    [
        ("zone_2",),
        ("zone_1", "zone_1", "zone_4"),
        ("zone_1", "zone_3", "zone_4"),
        ("portal_zone_1", "zone_2", "zone_3", "zone_4"),
    ],
)
def test_skipped_repeated_portal_or_reordered_recipes_are_not_canonical_floor_clears(zones):
    result = load(source()).evaluate((run(zones),))
    assert result[A48].current == result[A34].current == 0
    assert result[R25].current == int(zones[0] == "zone_1")


def test_mode_enrollment_gate_and_separate_runs_do_not_stitch_a_floor_sequence():
    value = source()
    detail = value["details"]["rogue_1"]
    detail["difficulties"][1]["enrollId"] = "review"
    detail["enrolls"]["review"] = {"enrollId": "review", "enrollTime": 200, "enrollNoticeEndTime": 201}
    rules = load(value)
    all_four = tuple("zone_" + str(i) for i in range(1, 5))
    assert rules.evaluate((run(all_four, "EASY"), run(all_four, at=199)))[R25].current == 0
    assert rules.evaluate((run(all_four, at=201),))[A34].current == 1
    assert rules.evaluate((run(("zone_1",)), run(("zone_2", "zone_3", "zone_4"))))[A34].current == 0


@pytest.mark.parametrize("change", ["condition", "name", "hidden", "missing_zone", "special", "enrollment"])
def test_changed_conditions_or_region_binding_fail_strictly(change):
    value = source()
    detail = value["details"]["rogue_1"]
    if change == "condition":
        detail["items"][R25]["unlockCondDesc"] = "进入第一层"
    elif change == "name":
        detail["zones"]["zone_1"]["name"] = "other"
    elif change == "hidden":
        detail["zones"]["zone_2"]["isHiddenZone"] = True
    elif change == "missing_zone":
        del detail["zones"]["zone_4"]
    elif change == "special":
        detail["archiveComp"]["relic"]["relic"][A48]["isSpRelic"] = True
    else:
        detail["enrolls"]["later"] = {}
        detail["archiveComp"]["relic"]["relic"][A48]["enrollId"] = "later"
    with pytest.raises(ValueError):
        load(value)


@pytest.mark.parametrize(
    "bad",
    [
        RunFloors("NORMAL", True, 200, ()),
        RunFloors("UNKNOWN", 0, 200, ()),
        RunFloors("NORMAL", 0, -1, ()),
        RunFloors("NORMAL", 0, 200, []),
        RunFloors("NORMAL", 0, 200, (None,)),
        RunFloors("NORMAL", 0, 200, ("zone_1",) * 16),
    ],
)
def test_malformed_run_facts_fail_instead_of_producing_eligibility(bad):
    with pytest.raises(ValueError):
        load(source()).evaluate((bad,))


def test_compiled_conditions_are_immutable_and_legacy_unnamed_qa_does_not_enable_contract():
    value = source()
    rules = load(value)
    value["details"]["rogue_1"]["zones"]["zone_1"]["name"] = "changed"
    assert rules.evaluate((run(("zone_1",)),))[R25].current == 1
    with pytest.raises(TypeError):
        rules.conditions[R25] = (2, "changed")
    legacy = SimpleNamespace(
        manifest={"tables": {"roguelike_topic_table": "b" * 64}}, table=lambda name: table()
    )
    assert not available(legacy)


@pytest.fixture
def floor_unlock_runtime(monkeypatch, request):
    original = start_fixture.import_data

    def imported(folder, destination):
        path = folder / "roguelike_topic_table.json"
        value = json.loads(path.read_bytes())
        detail = value["details"]["rogue_1"]
        add_floor_conditions(detail)
        add_base_score({"roguelike_topic_table": value})
        detail["zones"]["zone_5"] = {"id": "zone_5", "name": "血月长廊", "isHiddenZone": False}
        path.write_text(json.dumps(value), "utf8")
        return original(folder, destination)

    monkeypatch.setattr(start_fixture, "import_data", imported)
    return request.getfixturevalue("shop_ending_runtime")


def relics(runtime, token):
    return runtime.sync(token)["user"]["rlv2"]["outer"]["rogue_1"]["collect"]["relic"]


def test_real_crossing_delta_idempotency_rollback_abandon_restart_and_backup(floor_unlock_runtime):
    runtime, token = floor_unlock_runtime
    setup(runtime, token, ("INCIDENT",) * 5)
    assert all(relics(runtime, token)[key] == {"state": 0, "progress": [0, 1]} for key in CONDITIONS)
    with TestClient(create_game_app(runtime)) as client:
        for number in range(1, 5):
            assert (
                post(client, token, "moveTo", {"to": {"x": 0, "y": 0}}, f"enter-{number}").status_code == 200
            )
            assert (
                post(client, token, "selectChoice", {"choice": "choice_gold"}, f"gain-{number}").status_code
                == 200
            )
            if number == 1:
                before = rows(runtime.database.path)
                from terralocal.server.domain.rogue_visits import choose

                def fail(ctx):
                    choose(ctx, "choice_leave")
                    raise DomainError("INJECTED", "rollback floor unlock projection")

                with pytest.raises(DomainError):
                    runtime.mutate(token, None, "rollback-unlock", "qa", {}, fail)
                assert rows(runtime.database.path) == before and relics(runtime, token)[R25]["state"] == 0
            before = runtime.sync(token)["user"]
            reply = post(client, token, "selectChoice", {"choice": "choice_leave"}, f"leave-{number}")
            assert reply.status_code == 200, reply.text
            after = runtime.sync(token)["user"]
            assert apply(before, reply.json()["playerDataDelta"]) == after
            assert relics(runtime, token)[R25]["state"] == 1
            assert relics(runtime, token)[A48]["state"] == int(number >= 2)
            assert relics(runtime, token)[A34]["state"] == int(number >= 4)
            assert (
                post(client, token, "selectChoice", {"choice": "choice_leave"}, f"retry-{number}").status_code
                == 200
            )
            assert runtime.sync(token)["user"] == after
        assert post(client, token, "giveUpGame", {}, "abandon-floor-goals").status_code == 200
    state = runtime.sync(token)["user"]
    saved = rows(runtime.database.path)
    with runtime.database.transaction(write=False) as session:
        outer = session.get(m.RogueTopicOuter, (1, "rogue_1"))
        assert not any(key in outer.state["collect"]["relic"] for key in CONDITIONS)
        assert all(r.ordinal == 0 for r in session.query(m.RogueRunRelic).all())
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == state
        backup = BackupService(reopened)
        backup.restore(backup.create()["name"])
        assert rows(reopened.database.path) == saved and reopened.sync(token)["user"] == state
    finally:
        reopened.database.close()


def test_unfounded_eligibility_rejected_live_and_before_startup_writes(floor_unlock_runtime):
    runtime, token = floor_unlock_runtime
    with runtime.database.transaction() as session:
        row = session.get(m.RogueTopicOuter, (1, "rogue_1"))
        state = copy.deepcopy(row.state)
        state["collect"]["relic"][A48] = {"state": 1, "progress": [1, 1]}
        row.state = state
    with pytest.raises(DomainError):
        runtime.sync(token)
    raw = runtime.settings.database_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest() == digest
