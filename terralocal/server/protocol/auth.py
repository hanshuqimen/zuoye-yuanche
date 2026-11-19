"""CN SDK/U8/GS transport adapters backed exclusively by local sessions.

Reference: public request schemas and the frozen APK's Java login callback.
Actual client validation remains tracked separately in the compatibility profile.
"""

import hashlib
import json

from fastapi import APIRouter
from pydantic import Field, model_validator
from sqlalchemy import select

from terralocal.server.api.schemas import Command, Identifier, Login
from terralocal.server.domain import accounts
from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence import models as m
from terralocal.server.protocol.bootstrap import Bootstrap


class Grant(Command):
    code: str | None = Field(default=None, max_length=256)
    token: str | None = Field(default=None, max_length=256)
    appCode: str | None = Field(default=None, max_length=64)
    appId: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def require_credential(self):
        if not (self.code or self.token) or (self.code and self.token and self.code != self.token):
            raise ValueError("唯一的本地 SDK 凭据必填")
        return self


class U8Token(Command):
    appId: str
    platform: int
    channelId: str
    subChannel: str | None = None
    extension: str = Field(max_length=8192)
    worldId: str | None = None
    deviceId: str | None = Field(default=None, max_length=256)
    deviceId2: str | None = Field(default=None, max_length=256)
    deviceId3: str | None = Field(default=None, max_length=256)
    sign: str | None = Field(default=None, max_length=256)


class ProductCatalog(Command):
    appId: str
    channelId: str
    worldId: int
    platform: int


class GameLogin(Command):
    uid: Identifier
    token: str = Field(min_length=1, max_length=256)
    platform: int
    networkVersion: str = Field(max_length=32)
    assetsVersion: str = Field(max_length=128)
    clientVersion: str = Field(max_length=32)
    # Present in the observed 2.7.71 GS login body; transport metadata only.
    udtVersion: str | None = Field(default=None, max_length=128)
    deviceId: str | None = Field(default=None, max_length=256)
    deviceId2: str | None = Field(default=None, max_length=256)
    deviceId3: str | None = Field(default=None, max_length=256)


def authenticate_kind(session, token: str, uid: str | None, expected: str):
    account = accounts.authenticate(session, token, uid)
    row = session.scalar(select(m.LocalSession).where(
        m.LocalSession.token_hash == hashlib.sha256(token.encode()).hexdigest()))
    if row.kind != expected:
        error = DomainError("INVALID_AUTH_STAGE", "本地登录凭据阶段不匹配", 401)
        error.auth_stage = row.kind
        raise error
    return account


def router(runtime) -> APIRouter:
    api = APIRouter()
    settings = runtime.settings

    @api.post("/u8/pay/getAllProductList")
    def product_catalog(payload: ProductCatalog):
        if (payload.appId, payload.channelId, payload.worldId, payload.platform) != ("1", "1", 1, 1):
            raise DomainError("UNSUPPORTED_CHANNEL", "商品目录与客户端渠道不匹配", 409)
        return Bootstrap(settings).document("sdk_products")

    @api.post("/local/v1/sdk/login")
    def sdk_login(payload: Login):
        with runtime.maintenance, runtime.database.transaction() as session:
            result = accounts.login(session, settings, kind="sdk", **payload.model_dump(exclude_none=True))
            return {"uid": result["uid"], "code": result["secret"],
                    "callback": {"code": result["secret"], "isSuc": True, "type": 1}}

    @api.post("/user/oauth2/v2/grant")
    @api.post("/user/oauth2/v1/grant")
    def grant(payload: Grant):
        token = payload.code or payload.token
        with runtime.maintenance, runtime.database.transaction(write=False) as session:
            account = authenticate_kind(session, token, None, "sdk")
            return {"status": 0, "msg": "OK", "data": {"code": token, "uid": account.uid}}

    @api.post("/u8/user/v1/getToken")
    def u8_token(payload: U8Token):
        if payload.appId != "1" or payload.platform != 1 or payload.channelId != "1":
            raise DomainError("UNSUPPORTED_CHANNEL", "此兼容配置仅支持国服官服 Android", 409)
        try:
            extension = json.loads(payload.extension)
        except (ValueError, TypeError) as exc:
            raise DomainError("INVALID_EXTENSION", "U8 扩展必须为 JSON 对象") from exc
        if not isinstance(extension, dict):
            raise DomainError("INVALID_EXTENSION", "U8 扩展必须为 JSON 对象")
        tokens = [extension.get(key) for key in ("code", "access_token", "token") if extension.get(key)]
        if not tokens or any(not isinstance(token, str) or token != tokens[0] for token in tokens):
            raise DomainError("INVALID_EXTENSION", "U8 扩展缺少唯一的本地 SDK 凭据")
        uid = extension.get("uid")
        if uid is not None and not isinstance(uid, str):
            raise DomainError("INVALID_EXTENSION", "U8 uid 必须为字符串")
        with runtime.maintenance, runtime.database.transaction() as session:
            account = authenticate_kind(session, tokens[0], uid, "sdk")
            result = accounts.login(session, settings, uid=account.uid, token=tokens[0], kind="u8")
            return {"result": 0, "uid": account.uid, "channelUid": account.uid, "token": result["secret"],
                    "isGuest": 0, "error": "", "extension": json.dumps(
                        {"isMinor": False, "isAuthenticate": True}, separators=(",", ":"))}

    @api.post("/account/login")
    def game_login(payload: GameLogin):
        if payload.platform != 1:
            raise DomainError("UNSUPPORTED_PLATFORM", "此配置仅支持 Android", 409)
        Bootstrap(settings).check_version(payload.clientVersion, payload.assetsVersion, payload.networkVersion)
        with runtime.maintenance, runtime.database.transaction() as session:
            authenticate_kind(session, payload.token, payload.uid, "u8")
            return accounts.login(session, settings, uid=payload.uid, token=payload.token, kind="game")

    return api
