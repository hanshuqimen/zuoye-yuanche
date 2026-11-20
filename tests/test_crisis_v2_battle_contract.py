"""Authored finish fields; no captured response or invented settlement rule."""

import pytest
from pydantic import ValidationError

from terralocal.server.protocol.crisis_v2_battle import FinishDetails


def details():
    return {"mapId": "authored_map", "scoreRecord": [10, 0, 0, 0, 0, 0],
            "scoreCurrent": [0, 20, 0, 0, 0, 0], "isNewRecord": True,
            "commentNew": ["new_comment"], "commentOld": ["old_comment"],
            "runeCount": [4, 7], "ts": 1234, "runeIds": ["actual_rune_id"]}


def test_finish_keeps_two_old_current_counts_distinct_from_six_score_axes():
    wire = details()
    result = FinishDetails.model_validate(wire).model_dump(mode="json")
    assert result == wire
    assert result["runeCount"] == [4, 7]
    assert len(result["scoreRecord"]) == len(result["scoreCurrent"]) == 6
    # A six-axis-looking payload is accepted by the client's list type but
    # skips both quantity assignments in M162480. Reject it before assembly.
    wire["runeCount"] = [0] * 6
    with pytest.raises(ValidationError):
        FinishDetails.model_validate(wire)
