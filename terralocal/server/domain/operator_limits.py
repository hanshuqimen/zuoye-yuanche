"""Operator limits from the active, versioned game tables."""

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata import GameData


def maximum_trust(data: GameData) -> int:
    maximum = data.table("favor_table").get("maxFavor")
    if type(maximum) is not int or not 0 <= maximum <= 2_000_000_000:
        raise DomainError("GAMEDATA_INVALID", "favor_table.maxFavor 必须是有效的非负整数", 503)
    return maximum
