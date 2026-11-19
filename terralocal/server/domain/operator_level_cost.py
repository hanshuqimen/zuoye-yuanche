"""Frozen CN cost: full levels + final fraction - existing fraction, rounded once.

CharacterLvlupViewModel._CalcTargetLevel uses single precision for both
fractions, then adds a 1e-5 single precision bias before MathUtil.RoundToLong.
This keeps billing equal to the owned client's preview across partial levels.
"""

import math
import struct


def _single(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _fraction(exp_map: list[int], cost_map: list[int], level: int, exp: int) -> float:
    if not exp:
        return 0.0
    ratio = _single(_single(cost_map[level - 1]) / _single(exp_map[level - 1]))
    return _single(ratio * _single(exp))


def cost(exp_map: list[int], cost_map: list[int], start_level: int, start_exp: int,
         end_level: int, end_exp: int) -> int:
    complete = sum(cost_map[start_level - 1:end_level - 1])
    final = _fraction(exp_map, cost_map, end_level, end_exp)
    initial = _fraction(exp_map, cost_map, start_level, start_exp)
    return math.floor(final - initial + complete + _single(1e-5) + 0.5)
