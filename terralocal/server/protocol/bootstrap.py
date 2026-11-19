"""Frozen bootstrap documents, scoped to an explicit client fingerprint.

The signed network document is served unchanged. The isolated client adapter handles
address selection; server startup never fetches official documents or authenticates there.
"""

import hashlib
import json

from fastapi import APIRouter
from fastapi.responses import Response

from terralocal.server.compatibility.profile import ClientCompatibilityProfile
from terralocal.server.domain.errors import DomainError


class Bootstrap:
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.data_dir / "client" / "bootstrap" / settings.client_profile
        self.profile_path = settings.data_dir / "profiles" / f"{settings.client_profile}.json"

    def profile(self) -> ClientCompatibilityProfile:
        if not self.profile_path.is_file():
            raise DomainError("CLIENT_PROFILE_MISSING", "尚未冻结客户端兼容配置", 503)
        profile = ClientCompatibilityProfile.load(self.profile_path)
        if profile.id != self.settings.client_profile or profile.gamedata_hash != self.settings.gamedata_hash:
            raise DomainError("CLIENT_PROFILE_MISMATCH", "客户端配置与已启用 GameData 不一致", 503)
        return profile

    def document(self, name: str) -> dict:
        self.profile()
        sources_path = self.root / "sources.json"
        path = self.root / f"{name}.json"
        if not path.is_file() or not sources_path.is_file():
            raise DomainError("BOOTSTRAP_MISSING", f"缺少冻结的启动配置 {name}", 503)
        sources = json.loads(sources_path.read_bytes())
        body = path.read_bytes()
        if sources.get(name, {}).get("sha256") != hashlib.sha256(body).hexdigest():
            raise DomainError("BOOTSTRAP_INVALID", "启动配置指纹校验失败", 503)
        return json.loads(body)

    def check_version(self, client: str, resource: str, network: str) -> None:
        profile = self.profile()
        config = json.loads(self.document("network")["content"])
        if (client != profile.client_version or resource != profile.resource_version or
                network != config["configVer"]):
            raise DomainError("CLIENT_VERSION_MISMATCH", "客户端、资源或网络配置版本不匹配", 409)


def router(runtime) -> APIRouter:
    api = APIRouter()
    bootstrap = Bootstrap(runtime.settings)

    @api.get("/favicon.ico")
    def favicon():
        # The local notice WebView requests this asset independently of the SDK.
        return Response('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
                        '<rect width="32" height="32" rx="6" fill="#111c26"/>'
                        '<path d="M8 8h16v4h-6v13h-4V12H8z" fill="#76dbc5"/></svg>',
                        media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})

    @api.get("/config/prod/official/network_config")
    def network():
        return bootstrap.document("network")

    @api.get("/api/remote_config/1/prod/default/Android/network_config")
    def android_network():
        # Observed on the frozen 2.7.71 Android client. This endpoint is a plain
        # network dictionary; the older signed wrapper remains a separate route.
        return bootstrap.document("network_android")

    @api.get("/config/prod/official/Android/version")
    @api.get("/assetbundle/official/Android/version")
    def version():
        profile = bootstrap.profile()
        return {"clientVersion": profile.client_version, "resVersion": profile.resource_version}

    @api.get("/config/prod/official/remote_config")
    def remote():
        result = bootstrap.document("remote")
        # Telemetry is disabled explicitly for this local server.
        return {**result, "enableGameBI": False, "enableMarquee": False}

    @api.get("/api/remote_config/1/prod/default/Android/remote_config")
    def android_remote():
        result = bootstrap.document("remote_android")
        return {**result, "enableGameBI": False}

    @api.get("/app/v1/config")
    def sdk_config():
        result = bootstrap.document("sdk_app")
        data = result["data"]
        # The local Java adapter handles account selection. Payments and links
        # that require an official user token must not be offered by this SDK.
        app = {**data["app"], "enablePayment": False, "enableAuthenticate": False,
               "enableAntiAddiction": False, "enableUnbindGrant": False,
               "enableScanLogin": False, "enableGiftCode": False,
               "showCustomerService": False, "showAccountAgreement": False}
        return {**result, "data": {**data, "payment": [], "app": app}}

    @api.get("/general/v1/server_time")
    def sdk_time():
        from terralocal.server.domain.clock import ServerClock
        from terralocal.server.persistence import models as m

        with runtime.database.transaction(write=False) as session:
            now = ServerClock(session.get(m.ServerClockState, 1)).now()
        return {"status": 0, "msg": "OK", "type": "A",
                "data": {"serverTime": now, "isHoliday": False}}

    @api.get("/config/prod/official/refresh_config")
    def refresh():
        return {"resVersion": bootstrap.profile().resource_version}

    @api.get("/config/prod/announce_meta/Android/preannouncement.meta.json")
    @api.get("/api/gate/meta/Android")
    def preannouncement():
        bootstrap.profile()
        return {"preAnnounceId": "1", "actived": True, "preAnnounceType": 2,
                "preAnnounceUrl": runtime.settings.advertised_url + "/gameBulletin"}

    @api.get("/config/prod/announce_meta/Android/announcement.meta.json")
    def announcement():
        from datetime import datetime

        from terralocal.server.domain.clock import ServerClock
        from terralocal.server.persistence import models as m

        bootstrap.profile()
        with runtime.database.transaction(write=False) as session:
            now = ServerClock(session.get(m.ServerClockState, 1)).now()
        date = datetime.fromtimestamp(now)
        return {"focusAnnounceId": "1", "announceList": [
            {"announceId": "1", "title": "TerraLocal 本地公告", "isWebUrl": True,
             "webUrl": runtime.settings.advertised_url + "/gameBulletin", "day": date.day,
             "month": date.month, "group": "SYSTEM"}], "extra": {"enable": False, "name": ""}}

    @api.get("/gameBulletin")
    def bulletin():
        from terralocal.server.services.bulletin_webview import bulletin_response

        return bulletin_response()

    return api
