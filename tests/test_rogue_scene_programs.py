"""Authored event graphs; no official event distribution or native effect claim."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_events import Resources, advance, decide, replay, scene_content
from terralocal.server.gamedata.rogue_events import (
    Branch,
    Delta,
    EventSpec,
    FirstThemeSceneCatalog,
    Frame,
    fixed_programs,
)


def source():
    choices = {
        "buy": {"id": "buy", "type": "TRADE", "nextSceneId": "result"},
        "skip": {"id": "skip", "type": "NEXT", "nextSceneId": "result"},
        "leave": {"id": "leave", "type": "LEAVE", "nextSceneId": None},
        "loop": {"id": "loop", "type": "NEXT", "nextSceneId": "entry"},
        "random": {"id": "random", "type": "NEXT_PROB", "nextSceneId": None},
    }
    for value in choices.values():
        value.update(title="Authored choice", isHiddenChoice=False, forceShowWhenOnlyLeave=False, sortId=0)
    scenes = {key: {"id": key, "title": "Authored scene", "description": "Authored line", "useHiddenMusic": False}
              for key in ("entry", "result")}
    return {"details": {"rogue_1": {"choices": choices, "choiceScenes": scenes}}}


def catalog(table=None):
    table = source() if table is None else table
    data = SimpleNamespace(manifest={"hash": "a" * 64},
                           rogue_topics=SimpleNamespace(topic=lambda theme: None), table=lambda name: table)
    return FirstThemeSceneCatalog(data)


def spec(c):
    def b(key, delta=Delta(), minimum=()):
        return Branch(key, c.choices[key].digest, delta, minimum)

    return EventSpec("authored-event", "entry", (
        Frame("entry", (b("buy", Delta(gold=-5, hope_max=3), (("gold", 5),)), b("skip"))),
        Frame("result", (b("leave"),))), "Authored QA rule; not official game mechanics")


def test_native_scene_contract_true_available_and_atomic_decision_replay():
    c = catalog()
    program = c.compile(spec(c))
    initial = Resources(hp=4, gold=6, hope_max=6, hope_cost=3, squad_capacity=6)
    state = replay(program, initial, ())
    assert scene_content(program, state) == {"id": "entry", "choices": {"buy": True, "skip": True},
                                             "choiceAdditional": {}}
    bought = advance(program, state, "buy")
    assert bought.scene == "result" and bought.resources == Resources(4, 1, 9, 3, 6)
    assert bought.resources.hope == 6 and bought.steps == ("buy",)
    assert initial.gold == 6 and state.resources == initial
    assert replay(program, initial, bought.steps) == bought
    ended = advance(program, bought, "leave")
    assert ended.scene is None and ended.resources == bought.resources
    with pytest.raises(DomainError, match="已经结束"):
        advance(program, ended, "buy")
    with pytest.raises(DomainError):
        replay(program, initial, ("buy", "buy"))


def test_cost_gate_disabled_choice_and_stale_cross_scene_request_do_not_change_resources():
    c = catalog()
    program = c.compile(spec(c))
    initial = Resources(4, 4, 6, 3, 6)
    state = replay(program, initial, ())
    assert scene_content(program, state)["choices"] == {"buy": False, "skip": True}
    with pytest.raises(DomainError) as error:
        advance(program, state, "buy")
    assert error.value.code == "ROGUE_EVENT_REQUIREMENT"
    assert state.resources == initial and state.steps == ()
    for bad in ("leave", "missing", 1, True, {"choice": "skip"}):
        with pytest.raises(DomainError) as error:
            advance(program, state, bad)
        assert error.value.code == "ROGUE_EVENT_CHOICE"


@pytest.mark.parametrize("delta,minimum", [(Delta(hp=3), ()), (Delta(squad_capacity=1), ()),
    (Delta(hope_max=-3, hp=10), (("hope", 3),)), (Delta(hp=-2, gold=8), (("hp", 3),))])
def test_explicit_resource_rules_share_one_runner_without_mutating_input(delta, minimum):
    c = catalog()
    base = spec(c)
    branch = replace(base.frames[0].branches[0], delta=delta, minimum=minimum)
    program = c.compile(replace(base, frames=(replace(base.frames[0], branches=(branch,)), base.frames[1])))
    initial = Resources(4, 6, 6, 3, 6)
    state = replay(program, initial, ("buy",))
    assert state.resources.hope_cost == 3
    for key in ("hp", "gold", "hope_max", "squad_capacity"):
        assert getattr(state.resources, key) == getattr(initial, key) + getattr(delta, key)


@pytest.mark.parametrize("change", ["choice-hash", "random", "next-side-effect", "missing-frame", "unreachable",
                                   "duplicate-frame", "duplicate-choice", "closed-loop", "unknown-condition",
                                   "duplicate-condition", "bool-value", "missing-evidence"])
def test_program_admission_rejects_guessed_versions_invalid_graphs_and_effects(change):
    c = catalog()
    value = spec(c)
    frame, branch = value.frames[0], value.frames[0].branches[0]
    if change == "choice-hash":
        branch = replace(branch, choice_digest="b" * 64)
    elif change == "random":
        branch = replace(branch, choice="random", choice_digest=c.choices["random"].digest)
    elif change == "next-side-effect":
        branch = replace(frame.branches[1], delta=Delta(gold=1))
    elif change == "unknown-condition":
        branch = replace(branch, minimum=(("__import__('os')", 0),))
    elif change == "duplicate-condition":
        branch = replace(branch, minimum=(("gold", 1), ("gold", 2)))
    elif change == "bool-value":
        branch = replace(branch, delta=Delta(gold=True))
    if change in ("choice-hash", "random", "next-side-effect", "unknown-condition", "duplicate-condition", "bool-value"):
        value = replace(value, frames=(replace(frame, branches=(branch,)), value.frames[1]))
    elif change == "missing-frame":
        value = replace(value, frames=(frame,))
    elif change == "unreachable":
        value = replace(value, entry="result")
    elif change == "duplicate-frame":
        value = replace(value, frames=value.frames + (frame,))
    elif change == "duplicate-choice":
        value = replace(value, frames=(replace(frame, branches=(branch, branch)), value.frames[1]))
    elif change == "closed-loop":
        value = replace(value, frames=(Frame("entry", (Branch("loop", c.choices["loop"].digest, Delta()),)),))
    elif change == "missing-evidence":
        value = replace(value, evidence="")
    with pytest.raises(ValueError):
        c.compile(value)


def test_loop_with_exit_replays_under_bounded_budget_and_never_regenerates_program():
    c = catalog()
    value = spec(c)
    loop = Branch("loop", c.choices["loop"].digest, Delta())
    value = replace(value, frames=(replace(value.frames[0], branches=(loop, value.frames[0].branches[1])),
                                   value.frames[1]))
    program = c.compile(value)
    initial = Resources(4, 6, 6, 3, 6)
    state = replay(program, initial, ("loop",) * 254 + ("skip", "leave"))
    assert state.scene is None and state.resources == initial and len(state.steps) == 256
    with pytest.raises(DomainError):
        replay(program, initial, ("loop",) * 257)
    assert program.digest == c.compile(value).digest
    with pytest.raises(TypeError):
        program.frames["new"] = value.frames[0]


@pytest.mark.parametrize("initial", [Resources(True, 6, 6, 3, 6), Resources(4, -1, 6, 3, 6),
                                      Resources(4, 6, 2, 3, 6), Resources(4, 2**31, 6, 3, 6)])
def test_illegal_saved_resources_rejected(initial):
    c = catalog()
    with pytest.raises(DomainError):
        replay(c.compile(spec(c)), initial, ())


def test_all_unavailable_choices_fail_explicitly_and_hope_cost_cannot_be_spent_again():
    c = catalog()
    value = spec(c)
    buy = replace(value.frames[0].branches[0], delta=Delta(hope_max=-4), minimum=(("hope", 4),))
    program = c.compile(replace(value, frames=(replace(value.frames[0], branches=(buy,)), value.frames[1])))
    state = replay(program, Resources(4, 6, 6, 3, 6), ())
    with pytest.raises(DomainError) as error:
        scene_content(program, state)
    assert error.value.code == "ROGUE_EVENT_NO_CHOICE"


def test_catalog_validates_every_choice_and_scene_not_only_the_chosen_path():
    value = deepcopy(source())
    value["details"]["rogue_1"]["choices"]["random"]["nextSceneId"] = "missing"
    with pytest.raises(ValueError):
        catalog(value)
    value = source()
    value["details"]["rogue_1"]["choiceScenes"]["result"]["useHiddenMusic"] = 1
    with pytest.raises(ValueError):
        catalog(value)


def test_driver_boundary_replays_before_decision_and_never_accepts_repeated_cost():
    c = catalog()
    program = c.compile(spec(c))
    initial = Resources(4, 6, 6, 3, 6)
    bought = decide(program, initial, (), "buy")
    ended = decide(program, initial, bought.steps, "leave")
    assert ended.resources.gold == 1 and ended.scene is None
    with pytest.raises(DomainError):
        decide(program, initial, bought.steps, "buy")
    with pytest.raises(DomainError):
        decide(program, initial, ("leave",), "buy")


def test_client_row_change_invalidates_reviewed_effect_and_fixed_rules_do_not_fallback():
    c = catalog()
    value = spec(c)
    source_changed = source()
    source_changed["details"]["rogue_1"]["choices"]["buy"]["title"] = "Different offer"
    with pytest.raises(ValueError):
        catalog(source_changed).compile(value)
    with pytest.raises(ValueError):
        fixed_programs(c)


def test_overflow_disables_resource_effect_instead_of_wrapping_or_partially_paying():
    c = catalog()
    value = spec(c)
    buy = replace(value.frames[0].branches[0], delta=Delta(gold=-5, hp=1))
    program = c.compile(replace(value, frames=(replace(value.frames[0], branches=(buy, value.frames[0].branches[1])),
                                              value.frames[1])))
    initial = Resources(2**31 - 1, 6, 6, 3, 6)
    state = replay(program, initial, ())
    assert scene_content(program, state)["choices"] == {"buy": False, "skip": True}
    with pytest.raises(DomainError):
        decide(program, initial, (), "buy")
    assert state.resources == initial
