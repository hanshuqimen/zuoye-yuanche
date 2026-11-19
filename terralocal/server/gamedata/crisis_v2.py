"""Frozen 2.7.71 Crisis V2 map selection and score rules.

Derived from the versioned native model consumers documented in
docs/crisis-contract-2026-11-19.md. This is not a season source, a calendar,
an unlock award service, or a battle settlement. Caller-supplied player data
must belong to the same map/version; no all-unlocked player is synthesized.
"""

from collections import deque
from dataclasses import dataclass
from enum import IntEnum
from types import MappingProxyType
from typing import Mapping

from terralocal.server.gamedata.repository import SHA256, fingerprint

CONTRACT = "cn-android-2.7.71-crisis-v2-map-v1"
CLIENT_ELF_SHA256 = "3ece1e7b34165233fe8c3c919cf55dfcb4406b6bbc2725def2b1242b4c0a6259"
DIMENSIONS = 6
INT_MAX = 2**31 - 1


class NodeStatus(IntEnum):
    DISABLE = 0
    UNREACH = 1
    REACHABLE = 2
    SELECTED = 3


@dataclass(frozen=True)
class Rune:
    score: int
    dimension: int


@dataclass(frozen=True)
class Node:
    kind: str
    rune: Rune | None
    bag: str | None
    exclusion: str | None
    adjacent: tuple[str, ...]
    lockable: bool


@dataclass(frozen=True)
class Bag:
    dimension: int
    reward_score: int
    members: tuple[str, ...]


@dataclass(frozen=True)
class Exclusion:
    default_slot: str | None
    members: tuple[str, ...]


@dataclass(frozen=True)
class BagProgress:
    current: int
    target: int

    @property
    def complete(self) -> bool:
        # M163123 uses >=, including 0/0. This does not award shop currency.
        return self.current >= self.target


@dataclass(frozen=True)
class MapEvaluation:
    rules_fingerprint: str
    rune_slots: tuple[str, ...]
    selected_nodes: frozenset[str]
    start_nodes: frozenset[str]
    available_nodes: frozenset[str]
    unknown_nodes: frozenset[str]
    dimension_scores: tuple[int, ...]
    bag_progress: Mapping[str, BagProgress]

    @property
    def total_score(self) -> int:
        return sum(self.dimension_scores)


def _object(value, label):
    if type(value) is not dict:
        raise ValueError(f"危机合约{label}必须为对象")
    return value


def _identifier(value, label):
    if type(value) is not str or not value or "\0" in value:
        raise ValueError(f"危机合约{label}标识非法")
    return value


def _optional_identifier(value, label):
    return None if value is None or value == "" else _identifier(value, label)


def _integer(value, label):
    if type(value) is not int or not -2**31 <= value <= INT_MAX:
        raise ValueError(f"危机合约{label}必须为有符号32位整数")
    return value


@dataclass(frozen=True, init=False)
class CrisisV2MapRules:
    """Immutable map rules; strict admission checks precede native arithmetic.

    Reference completeness, symmetric adjacency and overflow rejection are
    local admission safeguards. They are not asserted as universal game rules.
    Display maxima are retained separately and never clamp a selected score.
    """

    map_id: str
    display_maxima: tuple[int, ...]
    nodes: Mapping[str, Node]
    bags: Mapping[str, Bag]
    exclusions: Mapping[str, Exclusion]
    data_hash: str
    fingerprint: str

    def __init__(self, map_id: str, detail: dict, *, data_hash: str, client_elf_sha256: str):
        object.__setattr__(self, "map_id", _identifier(map_id, "地图"))
        if client_elf_sha256 != CLIENT_ELF_SHA256:
            raise ValueError("危机合约客户端指纹未匹配已核实的规则合同")
        if type(data_hash) is not str or not SHA256.fullmatch(data_hash):
            raise ValueError("危机合约数据版本指纹非法")
        detail = _object(detail, "地图配置")
        raw_nodes = _object(detail.get("nodeDataMap"), "节点表")
        raw_runes = _object(detail.get("runeDataMap"), "符文表")
        raw_bags = _object(detail.get("bagDataMap"), "符文组表")
        raw_groups = _object(detail.get("exclusionDataMap"), "互斥组表")
        raw_locks = _object(detail.get("dailyRuneUnlcokDataMap"), "每日解锁表")
        runes = {}
        for key, row in raw_runes.items():
            _identifier(key, "符文")
            row = _object(row, "符文")
            if row.get("runeId") != key:
                raise ValueError("危机合约符文键与runeId不一致")
            runes[key] = Rune(_integer(row.get("score"), "符文分数"),
                              _integer(row.get("dimension"), "符文维度"))
        nodes = {}
        for key, row in raw_nodes.items():
            _identifier(key, "节点")
            row = _object(row, "节点")
            kind = row.get("nodeType")
            if type(kind) is not str or kind not in {"START", "NORMAL", "KEYPOINT", "TREASURE"}:
                raise ValueError("危机合约出现未接纳的节点类型")
            adjacent = row.get("adjacentNodeList")
            if type(adjacent) is not list or any(type(v) is not str or not v for v in adjacent):
                raise ValueError("危机合约节点邻接表非法")
            rune = None
            if kind == "NORMAL":
                rune_id = _optional_identifier(row.get("runeId"), "节点符文")
                if rune_id is not None:
                    if rune_id not in runes:
                        raise ValueError("危机合约普通节点引用了缺失的符文")
                    rune = runes[rune_id]
            # Special nodes do not consume runeId. Preserve the original detail
            # in its fingerprint, including an unused TREASURE runeId of " ".
            nodes[key] = Node(kind, rune, _optional_identifier(row.get("slotPackId"), "节点符文组"),
                              _optional_identifier(row.get("mutualExclusionGroup"), "节点互斥组"),
                              tuple(adjacent), key in raw_locks)
        for key, node in nodes.items():
            if any(v not in nodes or key not in nodes[v].adjacent for v in node.adjacent):
                raise ValueError("危机合约邻接引用缺失或不对称，未接纳此地图")
            if node.bag is not None and node.bag not in raw_bags:
                raise ValueError("危机合约节点引用了缺失的符文组")
            if node.exclusion is not None and node.exclusion not in raw_groups:
                raise ValueError("危机合约节点引用了缺失的互斥组")
        if any(key not in nodes for key in raw_locks):
            raise ValueError("危机合约每日解锁表引用了缺失的节点")
        bags = {}
        for key, row in raw_bags.items():
            _identifier(key, "符文组")
            row = _object(row, "符文组")
            if row.get("slotPackId") != key or row.get("mapId") != map_id:
                raise ValueError("危机合约符文组标识或地图不匹配")
            bags[key] = Bag(_integer(row.get("dimension"), "符文组维度"),
                            _integer(row.get("rewardScore"), "符文组附加分"),
                            tuple(k for k, n in nodes.items() if n.bag == key))
        groups = {}
        for key, row in raw_groups.items():
            _identifier(key, "互斥组")
            row = _object(row, "互斥组")
            members = tuple(k for k, n in nodes.items() if n.exclusion == key)
            default = _optional_identifier(row.get("defaultSlotId"), "默认节点")
            if default is not None and default not in members:
                raise ValueError("危机合约互斥组默认节点不属于该组")
            groups[key] = Exclusion(default, members)
        dimensions = detail.get("dimensionItemList")
        if type(dimensions) is not list or len(dimensions) != DIMENSIONS:
            raise ValueError("危机合约维度显示配置未匹配六维合同")
        object.__setattr__(self, "display_maxima", tuple(
            _integer(_object(row, "维度").get("maxScore"), "显示最大分") for row in dimensions))
        # Bound all possible partial sums without emulating signed overflow.
        if (sum(abs(n.rune.score) for n in nodes.values() if n.rune is not None)
                + sum(abs(b.reward_score) for b in bags.values()) > INT_MAX):
            raise ValueError("危机合约分数可能溢出，未接纳此配置")
        object.__setattr__(self, "nodes", MappingProxyType(nodes))
        object.__setattr__(self, "bags", MappingProxyType(bags))
        object.__setattr__(self, "exclusions", MappingProxyType(groups))
        object.__setattr__(self, "data_hash", data_hash)
        object.__setattr__(self, "fingerprint", fingerprint({
            "contract": CONTRACT, "client_elf": client_elf_sha256,
            "data": data_hash, "map_id": map_id, "detail": detail}))

    def _states(self, value, label, *, kind):
        rows = _object(value, label)
        result = {}
        for key, state in rows.items():
            if key not in self.nodes or self.nodes[key].kind != kind:
                raise ValueError(f"危机合约{label}引用了不匹配的节点")
            result[key] = _integer(state, label)
        return result

    def _runtime(self, player_map: dict, permanent: bool):
        player_map = _object(player_map, "玩家地图")
        if type(permanent) is not bool:
            raise ValueError("危机合约地图类别必须显式指定")
        self._states(player_map.get("rune"), "玩家符文状态", kind="NORMAL")
        challenge = self._states(player_map.get("challenge"), "玩家挑战状态", kind="KEYPOINT")
        extra = self._states(player_map.get("exRunes"), "玩家附加符文状态", kind="NORMAL") if permanent else {}
        starts, unknown, connectivity = set(), set(), {}
        for key, node in self.nodes.items():
            if node.kind == "START" or node.kind == "KEYPOINT" and challenge.get(key, 0) > 0:
                starts.add(key)
            connectivity[key] = 2
            if node.kind == "NORMAL" and node.lockable:
                state = extra.get(key, 0) if permanent else 0
                connectivity[key] = 2 if state >= 2 else 0
                if state < 2 and state != 1:
                    unknown.add(key)
        available, waiting = set(starts), deque(v for k in starts for v in self.nodes[k].adjacent)
        while waiting:
            key = waiting.popleft()
            if key in available or connectivity[key] == 0:
                continue
            available.add(key)
            if connectivity[key] == 2:
                waiting.extend(self.nodes[key].adjacent)
        return frozenset(starts), frozenset(available), frozenset(unknown)

    def evaluate(self, rune_slots: list[str] | tuple[str, ...], player_map: dict, *, permanent: bool):
        """Admit a battle's normal slots, then project connected auto nodes and score.

        Input duplicates are a set, as in the native model. Sorted normal IDs
        are a local canonical representation, not a claimed native list order.
        This operation never updates player progression or distributes rewards.
        """
        if type(rune_slots) not in (list, tuple) or any(type(v) is not str for v in rune_slots):
            raise ValueError("危机合约符文槽必须为字符串列表")
        requested = frozenset(rune_slots)
        if any(k not in self.nodes or self.nodes[k].kind != "NORMAL" for k in requested):
            raise ValueError("危机合约战斗只能提交本地图普通符文槽")
        starts, available, unknown = self._runtime(player_map, permanent)
        if not requested <= available:
            raise ValueError("危机合约符文槽尚不可用")
        selected, visited, waiting = set(), set(starts), deque(starts)
        while waiting:
            key = waiting.popleft()
            for other in self.nodes[key].adjacent:
                if other in visited or other not in available:
                    continue
                if other in requested or self.nodes[other].kind == "KEYPOINT":
                    visited.add(other)
                    selected.add(other)
                    waiting.append(other)
        if not requested <= selected:
            raise ValueError("危机合约符文槽未通过所选路径连接到起点")
        for group in self.exclusions.values():
            if len((selected | starts).intersection(group.members)) > 1:
                raise ValueError("危机合约同一互斥组不能选择多个节点")
        scores = [0] * DIMENSIONS
        for key in selected:
            rune = self.nodes[key].rune
            if rune is not None and 0 <= rune.dimension < DIMENSIONS:
                scores[rune.dimension] += rune.score
        progresses = {}
        for key, bag in self.bags.items():
            current = target = 0
            for member in bag.members:
                node = self.nodes[member]
                if node.kind != "NORMAL" or member in unknown or member not in available:
                    continue
                value = node.rune.score if node.rune is not None else 0
                if node.exclusion is None or self.exclusions[node.exclusion].default_slot == member:
                    target += value
                if member in selected:
                    current += value
            progress = BagProgress(current, target)
            progresses[key] = progress
            if progress.complete and 0 <= bag.dimension < DIMENSIONS:
                scores[bag.dimension] += bag.reward_score
        return MapEvaluation(self.fingerprint, tuple(sorted(requested)), frozenset(selected), starts,
                             available, unknown, tuple(scores), MappingProxyType(progresses))

    def node_status(self, node_id: str | None, evaluation: MapEvaluation) -> NodeStatus:
        if evaluation.rules_fingerprint != self.fingerprint:
            raise ValueError("危机合约节点状态来自其他地图或版本")
        if not node_id or node_id not in evaluation.available_nodes:
            return NodeStatus.DISABLE
        selected = evaluation.start_nodes | evaluation.selected_nodes
        if node_id in selected:
            return NodeStatus.SELECTED
        if any(key in selected for key in self.nodes[node_id].adjacent):
            return NodeStatus.REACHABLE
        return NodeStatus.UNREACH
