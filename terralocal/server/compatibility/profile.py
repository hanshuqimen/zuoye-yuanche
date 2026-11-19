from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict

CAMPAIGN_CLIENT_PROFILE = "cn-android-2.7.71-campaign-qa"
CAMPAIGN_DATA_HASH = "f4ef9ba642138521ac84a16943b72a4f31a7c74d48417f017c314a9d729ae219"
ROGUE_CLIENT_PROFILE = "cn-android-2.7.71-rogue-qa"
ROGUE_DATA_HASH = "e915675d8d8a1cc97df8fa46eed27ef1bdaa9d1b0fdb07461dcabda36271ae29"


def native_profile(identifier: str) -> str:
    """Explicit adapters reuse the same frozen native wire contracts.

    The campaign QA profile adds a separately pinned table and independent
    save; it does not upgrade old account/catalog bindings. A future native
    binary or wire version needs a new protocol profile, not another alias.
    """
    return ("cn-android-2.7.71-display" if identifier in {
        "cn-android-2.7.71-local-cash", CAMPAIGN_CLIENT_PROFILE, ROGUE_CLIENT_PROFILE}
            else identifier)


class ClientCompatibilityProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    package: str
    channel: str
    client_version: str
    version_code: int
    apk_sha256: str
    resource_version: str
    api_version: str
    resource_manifest_version: str | None = None
    gamedata_hash: str | None = None
    gamedata_version: str | None = None
    client_verified: bool = False
    supported_features: list[str] = []
    adapter_script: str | None = None

    @classmethod
    def load(cls, path: Path) -> ClientCompatibilityProfile:
        return cls.model_validate(json.loads(path.read_text("utf-8")))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(self.model_dump_json(indent=2), "utf-8")
        temporary.replace(path)
