"""2.7.71 SDK notice and GS order reads, with local credentials and state.

Notice schema: own APK HGGameProtocol$1 / HGGameProtocolDialog.onClick.
Order-list envelope: historical CN reference; current client requests confirmed.
"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import Field
from sqlalchemy import select

from terralocal.server.api.schemas import Command
from terralocal.server.domain import local_payments, sdk
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.sessions import authenticate_session
from terralocal.server.persistence import models as m
from terralocal.server.protocol.auth import authenticate_kind


class NoticeAcceptance(Command):
    code: str = Field(min_length=1, max_length=256)


class LegacyOrderConfirmation(Command):
    uid: str = Field(min_length=1, max_length=32)
    orderId: str = Field(min_length=1, max_length=96)
    extension: str = Field(max_length=4096)


def router(runtime) -> APIRouter:
    api = APIRouter()

    @api.get("/u8/user/auth/v1/agreement_version")
    def agreement_version(code: str = Query(min_length=1, max_length=256)):
        with runtime.maintenance, runtime.database.transaction(write=False) as session:
            # Observed 2.7.71 passes its U8 token as `code`, after GS login.
            account = authenticate_kind(session, code, None, "u8")
            authorized, latest = sdk.consent_state(session, account.id)
        base = runtime.settings.advertised_url + "/protocol/plain/ak/"
        return {"status": 0, "msg": "OK", "data": {
            "agreementUrl": {"service": base + "service", "privacy": base + "privacy",
                             "childrenPrivacy": base + "children_privacy",
                             "updateOverview": base + "overview_of_changes"},
            "authorized": authorized, "isLatestUserAgreement": latest,
            "updatedAgreement": '["service","privacy"]'}}

    @api.post("/u8/user/auth/v1/update_agreement")
    def accept_agreement(payload: NoticeAcceptance):
        with runtime.maintenance, runtime.database.transaction() as session:
            account = authenticate_kind(session, payload.code, None, "u8")
            sdk.accept_notice(session, account.id)
        return {"status": 0, "msg": "OK", "data": {}}

    @api.get("/protocol/plain/ak/{document}")
    def local_notice(document: str):
        if document not in {"service", "privacy", "children_privacy", "overview_of_changes", "index"}:
            raise DomainError("NOTICE_NOT_FOUND", "本地说明不存在", 404)
        return HTMLResponse("<!doctype html><html lang=zh-CN><meta charset=utf-8>"
                            "<meta name=viewport content='width=device-width,initial-scale=1'>"
                            "<title>TerraLocal 本地存档说明</title><body style='padding:16px;line-height:1.7'>"
                            "<h1>TerraLocal 本地存档说明</h1><p>版本 1</p>"
                            "<p>你正在连接自己的 TerraLocal 服务器。账号、游戏进度和备份保存在该电脑中；"
                            "此页面说明本地存档的使用方式。</p>"
                            "<p>SDK 凭据仅用于这个本地服务器，不能登录官方账号。此服务器不处理真实支付，"
                            "不发送官方身份认证请求。请求日志保存接口名称、耗时、错误字段结构，"
                            "不保存登录密码或凭据。</p>"
                            "<p>在客户端勾选并确认后，只会为当前本地账号记录本说明的版本及确认时间。"
                            "请使用管理面板备份存档。当前版本的已验证范围以 STATUS.md 为准。</p>"
                            "</body></html>", headers={"Cache-Control": "no-store"})

    @api.post("/pay/getUnconfirmedOrderIdList")
    def orders(payload: Command, request: Request):
        from terralocal.server.main import credentials

        with runtime.maintenance, runtime.database.transaction(write=False) as session:
            account, _ = authenticate_session(session, *credentials(request))
            order_ids = sdk.unconfirmed_orders(session, account.id)
        return {"orderIdList": order_ids, "playerDataDelta": {"modified": {}, "deleted": {}}}

    @api.post("/u8/pay/confirmOrderState")
    def confirm_local_payment(payload: LegacyOrderConfirmation):
        # The frozen U8 legacy request has no game-auth header. Its first
        # approval must present the random capability issued by authenticated
        # GS createOrder. Empty-extension polling only reads an already
        # approved quote; the authenticated GS endpoint still owns rewards.
        with runtime.maintenance, runtime.database.transaction() as session:
            account = session.scalar(select(m.Account).where(m.Account.uid == payload.uid))
            if account is None:
                raise DomainError("UNKNOWN_LOCAL_ORDER", "本地订单不存在", 404)
            ctx = Context(session, runtime.require_data(), account.id)
            order, quote = local_payments.pair(ctx, payload.orderId)
            if order.state == "CANCELLED":
                return {"payState": 4}
            if quote.approved_at is None or payload.extension:
                try:
                    local_payments.approve(ctx, payload.orderId, payload.extension)
                except DomainError as exc:
                    if exc.code != "LOCAL_ORDER_EXPIRED":
                        raise
                    # A rejected approval previously rolled this transaction
                    # back, allowing clock rewind to revive an expired quote.
                    # Native payState=4 commits cancellation without rewards.
                    order.state = "CANCELLED"
                    return {"payState": 4}
        # U8PayConfirmResult.payState=3 -> native SDK status=4 -> GS claim.
        # This is a local simulation status, never a financial receipt.
        return {"payState": 3}

    return api
