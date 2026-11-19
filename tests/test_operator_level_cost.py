"""Cost witnesses from the frozen native UI and fingerprinted ARM64 function."""

import pytest

from terralocal.server.domain.operator_level_cost import cost


@pytest.mark.parametrize("start_level,start_exp,end_level,end_exp,expected", [
    (1, 0, 2, 100, 61),  # First green record: UI preview and native charge both 61.
    (2, 100, 3, 0, 5),  # Remaining fraction rounds once; per-segment ceil overcharges.
    (2, 100, 4, 49, 64),  # Second green record; don't round the intermediate fractions.
    (1, 0, 4, 49, 125),  # Two green records in one request.
    (2, 0, 2, 65, 20),  # Round nearest, rather than ceil(20.0...).
])
def test_native_partial_level_cost_witnesses(start_level, start_exp, end_level, end_exp, expected):
    assert cost([100, 117, 134, 151], [30, 36, 43, 50],
                start_level, start_exp, end_level, end_exp) == expected


def test_single_precision_fraction_and_bias_match_frozen_half_boundary():
    # A frozen phase-zero level costs 57 for 168 EXP. Its half is rounded up,
    # including the single precision error; Python's bankers rounding differs.
    assert cost([168], [57], 1, 0, 1, 84) == 29
