"""Pure explicit-scene interpreter, separate from protocol and DB transactions.

The scene visit transaction driver supplies owned, persisted decisions.
An interpreter check alone is not native acceptance.
"""

from dataclasses import asdict, dataclass

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.rogue_events import RESOURCES, Delta, EventProgram

MAX_STEPS = 256  # Local admission budget, not an official event limit.


@dataclass(frozen=True)
class Resources:
    hp: int
    gold: int
    hope_max: int
    hope_cost: int
    squad_capacity: int

    def validate(self):
        if (any(type(n) is not int or not 0 <= n < 2**31 for n in asdict(self).values())
                or self.hope_cost > self.hope_max):
            raise DomainError("ROGUE_EVENT_RESOURCES", "事件资源状态非法，未推进事件", 503)

    @property
    def hope(self):
        return self.hope_max - self.hope_cost


@dataclass(frozen=True)
class SceneState:
    scene: str | None
    resources: Resources
    steps: tuple[str, ...]
    capacity_peak: int | None = None  # Derived fact; never part of saved or wire JSON.


def allowed(resources: Resources, branch, *, delta=None) -> bool:
    if any(getattr(resources, name) < n for name, n in branch.minimum):
        return False
    try:
        changed(resources, branch.delta if delta is None else delta)
        return True
    except DomainError:
        return False


def changed(resources: Resources, delta: Delta) -> Resources:
    result = Resources(**(asdict(resources) | {
        key: getattr(resources, key) + getattr(delta, key) for key in RESOURCES}))
    result.validate()
    return result


def choice_effect(program, state, branch):
    target = program.choices[branch.choice].target
    if program.exit_steps is not None and len(state.steps) + 1 + program.exit_steps.get(target, 0) > MAX_STEPS:
        return None
    effects = program.choice_deltas
    delta = branch.delta
    if effects is not None and branch.choice in effects:
        entries = effects[branch.choice]
        uses = state.steps.count(branch.choice)
        if uses >= len(entries):
            return None
        delta = entries[uses]
    return delta if allowed(state.resources, branch, delta=delta) else None


def advance(program: EventProgram, state: SceneState, choice: str) -> SceneState:
    if (not isinstance(program, EventProgram) or not isinstance(state, SceneState)
            or type(state.steps) is not tuple or len(state.steps) >= MAX_STEPS):
        raise DomainError("ROGUE_EVENT_BUDGET", "事件路径超过已接纳预算，未推进", 409)
    state.resources.validate()
    if state.scene is None:
        raise DomainError("ROGUE_EVENT_ENDED", "事件已经结束，未重复执行效果", 409)
    frame = program.frames.get(state.scene)
    if frame is None:
        raise DomainError("ROGUE_EVENT_FRAME", "当前场景不属于已保存事件", 503)
    branch = next((b for b in frame.branches if type(choice) is str and b.choice == choice), None)
    if branch is None:
        raise DomainError("ROGUE_EVENT_CHOICE", "所选选项不属于当前场景", 409)
    delta = choice_effect(program, state, branch)
    if delta is None:
        raise DomainError("ROGUE_EVENT_REQUIREMENT", "选项条件或资源不足，未扣款或推进", 409)
    resources = changed(state.resources, delta)
    peak = state.resources.squad_capacity if state.capacity_peak is None else state.capacity_peak
    if type(peak) is not int or not state.resources.squad_capacity <= peak < 2**31:
        raise DomainError("ROGUE_EVENT_HISTORY", "事件容量历史非法，未推进事件", 503)
    return SceneState(program.choices[choice].target, resources, state.steps + (choice,),
                      max(peak, resources.squad_capacity))


def replay(program: EventProgram, initial: Resources, steps: tuple[str, ...]) -> SceneState:
    """Recompute state from ordered accepted decisions; never trust saved sums."""
    initial.validate()
    if type(steps) is not tuple or len(steps) > MAX_STEPS:
        raise DomainError("ROGUE_EVENT_HISTORY", "事件决策历史非法或过长", 503)
    state = SceneState(program.entry, initial, (), initial.squad_capacity)
    for choice in steps:
        state = advance(program, state, choice)
    return state


def decide(program: EventProgram, initial: Resources, steps: tuple[str, ...], choice: str) -> SceneState:
    """Driver boundary: derive the current scene before accepting a decision.

    A transaction driver must supply its persisted original resources and
    ordered choices, not a client-supplied scene, balance or result object.
    Idempotency and saving the accepted decision belong to that transaction.
    """
    return advance(program, replay(program, initial, steps), choice)


def scene_content(program: EventProgram, state: SceneState) -> dict:
    """Only the scene portion of Content; ownership/index belong to the driver."""
    state.resources.validate()
    if state.scene is None:
        raise DomainError("ROGUE_EVENT_ENDED", "事件已经结束，不能重建选项", 409)
    frame = program.frames.get(state.scene)
    if frame is None:
        raise DomainError("ROGUE_EVENT_FRAME", "当前场景不属于已保存事件", 503)
    choices = {b.choice: choice_effect(program, state, b) is not None for b in frame.branches}
    if not any(choices.values()):
        raise DomainError("ROGUE_EVENT_NO_CHOICE", "事件规则没有可用后继，请保留存档", 503)
    return {"id": state.scene, "choices": choices, "choiceAdditional": {}}
