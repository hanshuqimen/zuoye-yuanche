"""Frozen CN campaign sync fields and the native weekly-cap view.

This models CampaignFeeViewModel.LoadData, not a payout/reset transaction.
Its isFull compares the unlocked cap with the achievable cap; weekly earned
orundum is a separate field and does not participate in this comparison.
"""

from dataclasses import dataclass
from typing import Annotated

from pydantic import ConfigDict, Field

from terralocal.server.api.schemas import Command, Identifier
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.campaigns import CampaignCatalog

NonnegativeInt = Annotated[int, Field(ge=0, le=2**31 - 1)]
SignedInt = Annotated[int, Field(ge=-(2**31), le=2**31 - 1)]
MissionState = Annotated[int, Field(ge=0, le=2)]
# Native strings are reference fields. In particular, LoadData explicitly
# applies String.IsNullOrEmpty to rotate before considering mission cap fees.
OptionalIdentifier = Annotated[str, Field(max_length=96)] | None


class CampaignOpen(Command):
    # Frozen field-token-bound JsonProperty attributes, not CLR field names.
    # Domain constructors retain the descriptive names; only wire dumps use
    # rGroup/tGroup/tAllOpen. Reject duplicate internal/wire keys via forbid.
    model_config = ConfigDict(populate_by_name=True)

    permanent: list[Identifier] = Field(max_length=4096)
    training: list[Identifier] = Field(max_length=4096)
    rotate: OptionalIdentifier
    rotateGroup: OptionalIdentifier = Field(alias="rGroup")
    trainingGroup: OptionalIdentifier = Field(alias="tGroup")
    trainingAllOpenGroup: OptionalIdentifier = Field(alias="tAllOpen")


class CampaignStage(Command):
    maxKills: NonnegativeInt
    # The weekly-cap indicator tests exactly zero. Other reward views test
    # positive versus nonpositive values. Keep the integer values separate
    # from the unrelated three-state UI display enum.
    rewardStatus: list[SignedInt] = Field(max_length=4096)


class CampaignState(Command):
    campaignCurrentFee: NonnegativeInt
    campaignTotalFee: NonnegativeInt
    activeGroupId: OptionalIdentifier
    open: CampaignOpen
    # Native comparisons establish UNCOMPLETE=0, COMPLETE=1, FINISHED=2.
    missions: dict[Identifier, MissionState] = Field(max_length=4096)
    instances: dict[Identifier, CampaignStage] = Field(max_length=4096)
    sweepMaxKills: dict[Identifier, NonnegativeInt] = Field(max_length=4096)


@dataclass(frozen=True)
class CampaignFeeView:
    achievable_total: int
    is_full: bool
    has_unconfirmed_break_fee: bool
    unresolved_permanent_stages: tuple[str, ...]


def claimable_break_indices(catalog: CampaignCatalog, state: CampaignState, stage_id: str) -> tuple[int, ...]:
    """Return the native reward-list candidates, distinct from the cap hint.

    The reward list treats missing/nonpositive status entries as unclaimed.
    Opening rules, request ownership and an atomic claim still belong to the
    future campaign domain transaction; this view grants no rewards.
    """
    definition = catalog.stage(stage_id)
    progress = state.instances.get(stage_id)
    if progress is None:
        return ()
    return tuple(index for index, ladder in enumerate(definition.break_ladders)
                 if progress.maxKills >= ladder.kills and (index >= len(progress.rewardStatus)
                                                          or progress.rewardStatus[index] <= 0))


def fee_view(catalog: CampaignCatalog, state: CampaignState, *, initial_fee: int) -> CampaignFeeView:
    """Derive the native cap-upgrade view without changing a save or rewards.

    Pass initCampaignTotalFee from the matching global GameData constants.
    Unknown permanent stages contribute zero as in the native getter; retain
    their IDs for diagnostics. Null/malformed sync arrays are rejected by the
    model instead of disguising them as empty native arrays.
    """
    if type(initial_fee) is not int or not 0 <= initial_fee <= 2**31 - 1:
        raise DomainError("INVALID_CAMPAIGN_INITIAL_FEE", "剿灭初始周上限无效", 503)
    total = initial_fee
    pending = False
    unresolved = []
    for stage_id in state.open.permanent:
        definition = catalog.definitions.get(stage_id)
        if definition is None:
            unresolved.append(stage_id)
            continue
        stage_fee = sum(ladder.fee_add for ladder in definition.break_ladders)
        if stage_fee <= 0:
            continue
        total += stage_fee
        progress = state.instances.get(stage_id)
        if progress is not None:
            pending = pending or any(ladder.fee_add > 0 and progress.maxKills >= ladder.kills
                and index < len(progress.rewardStatus) and progress.rewardStatus[index] == 0
                for index, ladder in enumerate(definition.break_ladders))
    if state.open.rotate:
        # The native view walks every static mission, including missions not
        # yet present in the player's dictionary. Only COMPLETE signals a
        # pending cap reward; FINISHED has already been claimed.
        for mission_id, fee in catalog.mission_fees.items():
            if fee > 0:
                total += fee
                pending = pending or state.missions.get(mission_id) == 1
    if total > 2**31 - 1:
        raise DomainError("CAMPAIGN_FEE_OVERFLOW", "剿灭周上限定义超出客户端整数范围", 503)
    return CampaignFeeView(total, state.campaignTotalFee >= total, pending, tuple(unresolved))
