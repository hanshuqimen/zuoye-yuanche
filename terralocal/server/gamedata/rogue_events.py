"""First-theme scene contracts and explicit, version-bound event programs.

The client supplies presentation and some transition targets, not an event
selection pool, rewards or probabilities. Programs must supply a complete
graph and reviewed effects; there is no inference from an ID or display text.
"""

from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Mapping

from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.roguelike import identifier, invalid

POLICY = "rogue1-explicit-scene-program-v1"
CHOICE_TYPES = frozenset({"LEAVE", "NEXT", "NEXT_PROB", "TRADE", "TRADE_PROB"})
RESOURCES = ("hp", "gold", "hope_max", "squad_capacity")


@dataclass(frozen=True)
class SceneChoice:
    id: str
    kind: str
    target: str | None
    digest: str


@dataclass(frozen=True)
class Delta:
    hp: int = 0
    gold: int = 0
    hope_max: int = 0
    squad_capacity: int = 0


@dataclass(frozen=True)
class Branch:
    choice: str
    choice_digest: str
    delta: Delta
    # Minima are explicit rule data, never expressions evaluated from text.
    minimum: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class Frame:
    scene: str
    branches: tuple[Branch, ...]


@dataclass(frozen=True)
class EventSpec:
    id: str
    entry: str
    frames: tuple[Frame, ...]
    evidence: str


@dataclass(frozen=True)
class EventProgram:
    id: str
    entry: str
    frames: Mapping[str, Frame]
    choices: Mapping[str, SceneChoice]
    digest: str
    data_hash: str
    evidence: str
    choice_deltas: Mapping[str, tuple[Delta, ...]] | None = None
    exit_steps: Mapping[str, int] | None = None


class FirstThemeSceneCatalog:
    def __init__(self, data):
        data.rogue_topics.topic("rogue_1")
        detail = data.table("roguelike_topic_table")["details"]["rogue_1"]
        scenes, choices = detail["choiceScenes"], detail["choices"]
        if not 0 < len(scenes) <= 4096 or not 0 < len(choices) <= 4096:
            raise invalid("首主题场景或选项目录为空/超出预算")
        for key, row in scenes.items():
            identifier(key, "场景")
            if (row.get("id") != key or not isinstance(row.get("title"), str)
                    or not isinstance(row.get("description"), str)
                    or type(row.get("useHiddenMusic")) is not bool):
                raise invalid("首主题场景显示合同不匹配: " + key)
        admitted = {}
        for key, row in choices.items():
            identifier(key, "选项")
            kind, target = row.get("type"), row.get("nextSceneId")
            if (row.get("id") != key or type(kind) is not str or kind not in CHOICE_TYPES
                    or type(row.get("isHiddenChoice")) is not bool
                    or type(row.get("forceShowWhenOnlyLeave")) is not bool
                    or type(row.get("sortId")) is not int
                    or not isinstance(row.get("title"), str)
                    or target is not None and (type(target) is not str or target not in scenes)
                    or kind == "LEAVE" and target is not None):
                raise invalid("首主题选项合同不匹配: " + key)
            admitted[key] = SceneChoice(key, kind, target, fingerprint(row))
        self.scenes = frozenset(scenes)
        self.choices = MappingProxyType(admitted)
        self.data_hash = data.manifest["hash"]

    def compile(self, spec: EventSpec) -> EventProgram:
        """Compile explicit server rules; catalog coverage is not playability."""
        if (not isinstance(spec, EventSpec) or type(spec.frames) is not tuple
                or not 1 <= len(spec.frames) <= 128 or not isinstance(spec.evidence, str)
                or not 1 <= len(spec.evidence) <= 2048):
            raise invalid("事件方案缺少显式图或依据")
        identifier(spec.id, "事件方案")
        frames = {}
        for frame in spec.frames:
            if (not isinstance(frame, Frame) or type(frame.scene) is not str
                    or frame.scene not in self.scenes or frame.scene in frames
                    or type(frame.branches) is not tuple or not 1 <= len(frame.branches) <= 32):
                raise invalid("事件图的场景、选项预算或重复项非法")
            seen = set()
            for branch in frame.branches:
                if not isinstance(branch, Branch) or type(branch.choice) is not str or branch.choice in seen:
                    raise invalid("事件图存在非法或重复选项")
                choice = self.choices.get(branch.choice)
                if (choice is None or branch.choice_digest != choice.digest
                        or choice.kind not in ("LEAVE", "NEXT", "TRADE")):
                    raise invalid("选项版本未匹配或随机/未知效果尚未接纳")
                if (not isinstance(branch.delta, Delta) or any(type(n) is not int or abs(n) >= 2**31
                    for n in asdict(branch.delta).values())
                        or choice.kind in ("NEXT", "LEAVE") and any(asdict(branch.delta).values())):
                    raise invalid("非交易转场不能夹带资源效果，或效果超出预算")
                if type(branch.minimum) is not tuple or len(branch.minimum) > len(RESOURCES) + 1:
                    raise invalid("选项条件必须为有界显式最小余额")
                minima = set()
                for condition in branch.minimum:
                    if (type(condition) is not tuple or len(condition) != 2
                            or condition[0] not in (*RESOURCES, "hope") or condition[0] in minima
                            or type(condition[1]) is not int or not 0 <= condition[1] < 2**31):
                        raise invalid("事件条件非法；不执行文本表达式")
                    minima.add(condition[0])
                seen.add(branch.choice)
            frames[frame.scene] = frame
        if spec.entry not in frames:
            raise invalid("事件入口不存在")
        edges = {key: {self.choices[b.choice].target for b in f.branches}
                 for key, f in frames.items()}
        if any(target is not None and target not in frames for values in edges.values() for target in values):
            raise invalid("事件转场缺少明确后继场景")
        reached, queue = set(), [spec.entry]
        while queue:
            key = queue.pop()
            if key in reached:
                continue
            reached.add(key)
            queue.extend(t for t in edges[key] if t is not None)
        can_end = {key for key, values in edges.items() if None in values}
        for _ in frames:
            can_end |= {key for key, values in edges.items() if values.intersection(can_end)}
        if reached != set(frames) or can_end != set(frames):
            raise invalid("事件存在不可达场景或无法退出的循环")
        digest = fingerprint({"policy": POLICY, "data": self.data_hash, "spec": asdict(spec)})
        return EventProgram(spec.id, spec.entry, MappingProxyType(frames), self.choices,
                            digest, self.data_hash, spec.evidence)


# Reviewed fixed effects, guarded by complete frozen choice-row fingerprints.
# Strings/art remain in the imported client data. No random pool, node/floor
# availability or official encounter frequency is implied by these programs.
FIXED_RULES = (
    ("hp", "scene_hp_enter", "choice_hp_1", "scene_hp_1", Delta(hp=3),
     "856ca19f7d3070068058deb8c5b37ec822c0206571645a7f9e3a21047cd480ed"),
    ("hope", "scene_population_enter", "choice_population_1", "scene_population_1", Delta(hope_max=2),
     "c97899c6eb2a4da8af033c9ee144457c4d054808c4d9d2fe7be5973f887cfdb1"),
    ("gold", "scene_gold_enter", "choice_gold_1", "scene_gold_1", Delta(gold=5),
     "d725518148ea6eb607a3e71cca14022d05a0ec5517f5cf9f62ac6e66784a20cf"),
)
LEAVE_DIGEST = "caa928dcfcfbbc416ec57f9c33fe89bbc75d1a5c6ec1b66c72475b1896f13937"
GOLD_HOPE_PROGRAM = "rogue1-trade-gold-hope"
HEALTH_GOLD_PROGRAM = "rogue1-trade-hp-gold-v1"


def fixed_programs(catalog: FirstThemeSceneCatalog) -> Mapping[str, EventProgram]:
    """Compile all reviewed fixed-gain events together; no partial fallback.

    Two-frame graph adapter: initial fixed choice, result text, exit. A QA
    scene's extra initial 'leave' option is deliberately not treated as proof
    that the actual event offers it. Runtime node integration is separate.
    """
    evidence = ("Frozen CN2.7.71 choice rows plus PRTS first-theme event descriptions: "
                "https://prts.wiki/w/傀影与猩红孤钻/事件一览 ; explicit graph adapter, "
                "no official spawn pool or probability claim")
    result = {}
    for name, entry, choice, target, delta, digest in FIXED_RULES:
        spec = EventSpec("rogue1-fixed-" + name, entry, (
            Frame(entry, (Branch(choice, digest, delta),)),
            Frame(target, (Branch("choice_leave", LEAVE_DIGEST, Delta()),))), evidence)
        result[spec.id] = catalog.compile(spec)
    return MappingProxyType(result)


def trade_programs(catalog: FirstThemeSceneCatalog) -> Mapping[str, EventProgram]:
    """Reviewed gold-for-hope transaction and the independent decline path.

    This admits the event graph, not its official floor pool or appearance
    rate. Keep fixed_programs separate so old saved program digests and
    fixtures do not acquire a dependency on newly admitted event rows.
    """
    buy = Branch("choice_trade2_1",
        "5ba2df5eb2ccf5cfa6ee57b36a6c4b35967e95c465ec3f13895ee445072f5dea",
        Delta(gold=-5, hope_max=3), (("gold", 5),))
    decline = Branch("choice_trade2_2",
        "595048a0ee25590fa36b5b39391b501ee855f195f7f3f6be989b1bec07f7029a", Delta())
    leave = Branch("choice_leave", LEAVE_DIGEST, Delta())
    spec = EventSpec(GOLD_HOPE_PROGRAM, "scene_trade2_enter", (
        Frame("scene_trade2_enter", (buy, decline)),
        Frame("scene_trade2_1", (leave,)), Frame("scene_trade2_2", (leave,))),
        "Frozen CN2.7.71 complete choice-row hashes and nextSceneId; "
        "PRTS first-theme event list gold5 for hope3, independent decline: "
        "https://prts.wiki/w/傀影与猩红孤钻/事件一览 ; "
        "explicit server graph, no official spawn pool or probability claim")
    return MappingProxyType({spec.id: catalog.compile(spec)})


def health_trade_programs(catalog: FirstThemeSceneCatalog) -> Mapping[str, EventProgram]:
    """IS2 base life-for-gold trade, separate from earlier saved programs.

    Voluntary LP spending must leave at least one LP. Shields are not payment
    resources. This supplies no encounter weights or hallucination modifiers.
    """
    buy = Branch("choice_trade1_1",
        "5963449bc5a20af3f8da751d4cd11b32073d71167acc54cfff8ecc1063b7c1a3",
        Delta(hp=-2, gold=8), (("hp", 3),))
    decline = Branch("choice_trade1_2",
        "2435ede5f2617d02e7be499619b2a25e01239328df435422a8ef4d5b75f31412", Delta())
    leave = Branch("choice_leave", LEAVE_DIGEST, Delta())
    spec = EventSpec(HEALTH_GOLD_PROGRAM, "scene_trade1_enter", (
        Frame("scene_trade1_enter", (buy, decline)),
        Frame("scene_trade1_1", (leave,)), Frame("scene_trade1_2", (leave,))),
        "Frozen choice-row hashes/nextSceneId; IS2 base Hallucinatory Candlelights: "
        "https://prts.wiki/w/傀影与猩红孤钻/事件一览 ; voluntary LP payment leaves at least one LP: "
        "https://arknights.wiki.gg/wiki/Life_Point ; explicit server graph, "
        "no official encounter weights or modifier claim")
    return MappingProxyType({spec.id: catalog.compile(spec)})
