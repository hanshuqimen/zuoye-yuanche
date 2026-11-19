"""Common admission of independently compiled battle-only relic capabilities.

Legacy attribute catalogs and their saved quote fingerprints remain separate.
Capability is neither ownership nor natural-supply eligibility.
"""

from types import MappingProxyType

from terralocal.server.gamedata.rogue_battle_attributes import SOURCES as ATTRIBUTES
from terralocal.server.gamedata.rogue_global_buffs import SOURCES as GLOBAL_BUFFS

SOURCES = MappingProxyType(dict(ATTRIBUTES) | dict(GLOBAL_BUFFS))


def catalog(data, key):
    if key in ATTRIBUTES:
        return data.rogue_battle_attributes
    if key in GLOBAL_BUFFS:
        return data.rogue_global_buffs
    raise ValueError("首主题收藏品没有已核对的完整战斗效果")


def supported(data, key):
    if key not in SOURCES:
        return False
    catalog(data, key).require(key)
    return True


def require_open(data, key, at):
    catalog(data, key).require_open(key, at)
