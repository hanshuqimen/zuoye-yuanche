"""Account/device pairing and atomic private files for the local launcher."""
from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from terralocal.launcher.client_session import ClientConnectionError, LocalCredential
from terralocal.server.compatibility.profile import (
    CAMPAIGN_CLIENT_PROFILE,
    CRISIS_CLIENT_PROFILE,
    ROGUE_CLIENT_PROFILE,
)
from terralocal.server.persistence import models as m

INSTANCE = 1
INSTANCE_NAME = "TerraLocal"
SERIAL = "emulator-5556"
DEVICE_SERIAL = "0063090c"
PACKAGE = "com.hypergryph.arknights"
PATCHED_APK = "f75a9643d2d3fb487e5da082492cb2336bce399cabdc0725a895efd186df2e01"
CASH_CLIENT_PROFILE = "cn-android-2.7.71-local-cash"
CASH_PATCHED_APK = "473566842bc219e8f15945e6c3a377e97ca0d97ea064fc545dafdd8d570ae548"


def expected_apk(client_profile: str) -> str:
    # Keep the previously accepted adapter/bindings usable. The cash adapter
    # belongs to its own compatibility profile; it never replaces that hash.
    return CASH_PATCHED_APK if client_profile in {
        CASH_CLIENT_PROFILE, CAMPAIGN_CLIENT_PROFILE, ROGUE_CLIENT_PROFILE, CRISIS_CLIENT_PROFILE} else PATCHED_APK


def installation_folder(client_profile: str) -> str:
    if client_profile == CRISIS_CLIENT_PROFILE:
        return "test-instance-crisis-qa"
    if client_profile == ROGUE_CLIENT_PROFILE:
        return "test-instance-rogue-qa"
    if client_profile == CAMPAIGN_CLIENT_PROFILE:
        return "test-instance-campaign-qa"
    return "test-instance-local-cash" if client_profile == CASH_CLIENT_PROFILE else "test-instance"


class ClientBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: int = Field(default=1, ge=1, le=1)
    account_id: int = Field(ge=1)
    account_uid: str = Field(min_length=1, max_length=32, repr=False)
    instance: int = Field(default=INSTANCE, ge=INSTANCE, le=INSTANCE)
    instance_name: str = INSTANCE_NAME
    serial: str = SERIAL
    device_serial: str = DEVICE_SERIAL
    package: str = PACKAGE
    apk_sha256: str = PATCHED_APK
    client_profile: str = Field(min_length=1, max_length=96)
    gamedata_hash: str = Field(pattern=r"^[a-f0-9]{64}$")

    def validate_target(self) -> None:
        if (self.instance_name, self.serial, self.device_serial, self.package, self.apk_sha256) != (
                INSTANCE_NAME, SERIAL, DEVICE_SERIAL, PACKAGE, expected_apk(self.client_profile)):
            raise ClientConnectionError("UNSUPPORTED_CLIENT_BINDING", "绑定不属于已验证的独立测试实例")


def private_directory(settings) -> Path:
    directory = settings.data_dir / "launcher-client"
    if directory.is_symlink() or directory.is_junction():
        raise ClientConnectionError("CLIENT_BINDING_PATH", "启动器连接目录不能使用目录链接")
    return directory


def atomic_json(path: Path, content: dict) -> None:
    if path.is_symlink() or path.is_junction():
        raise ClientConnectionError("CLIENT_BINDING_PATH", "启动器连接文件不能使用目录链接")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if temporary.is_symlink() or temporary.is_junction():
        raise ClientConnectionError("CLIENT_BINDING_PATH", "启动器临时文件不能使用目录链接")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(content, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class BindingStore:
    def __init__(self, settings):
        self.settings = settings

    @property
    def directory(self) -> Path:
        return private_directory(self.settings)

    def load(self) -> ClientBinding | None:
        path = self.directory / "binding.json"
        if not path.exists():
            return None
        if path.is_symlink() or path.is_junction():
            raise ClientConnectionError("CLIENT_BINDING_PATH", "启动器绑定文件不能使用目录链接")
        if path.stat().st_size > 8192:
            raise ClientConnectionError("INVALID_CLIENT_BINDING", "启动器账号绑定文件无效，请重新选择账号")
        try:
            binding = ClientBinding.model_validate_json(path.read_bytes())
            binding.validate_target()
            if (binding.client_profile, binding.gamedata_hash) != (
                    self.settings.client_profile, self.settings.gamedata_hash):
                raise ClientConnectionError("CLIENT_BINDING_VERSION", "存档兼容版本已变化，请重新确认客户端绑定")
            return binding
        except (ValidationError, ValueError, UnicodeError) as error:
            raise ClientConnectionError("INVALID_CLIENT_BINDING", "启动器账号绑定文件无效，请重新选择账号") from error

    def bind(self, runtime, account_id: int) -> ClientBinding:
        with runtime.maintenance, runtime.database.transaction(write=False) as session:
            account = session.get(m.Account, account_id)
            if account is None:
                raise ClientConnectionError("BOUND_ACCOUNT_MISSING", "请选择已有的本地账号")
            binding = ClientBinding(account_id=account.id, account_uid=account.uid,
                                    apk_sha256=expected_apk(self.settings.client_profile),
                                    client_profile=self.settings.client_profile,
                                    gamedata_hash=self.settings.gamedata_hash)
        atomic_json(self.directory / "binding.json", binding.model_dump())
        return binding

    def clear(self) -> None:
        for name in ("binding.json", "terralocal-login.json"):
            path = self.directory / name
            if path.is_symlink() or path.is_junction():
                raise ClientConnectionError("CLIENT_BINDING_PATH", "启动器连接文件不能使用目录链接")
            path.unlink(missing_ok=True)

    def credential(self, binding: ClientBinding) -> LocalCredential | None:
        path = self.directory / "terralocal-login.json"
        if path.is_symlink() or path.is_junction():
            raise ClientConnectionError("CLIENT_BINDING_PATH", "启动器登录文件不能使用目录链接")
        if not path.is_file():
            return None
        if path.stat().st_size > 8192:
            return None
        try:
            callback = json.loads(path.read_bytes())
            code = callback.get("code") if isinstance(callback, dict) else None
            if (not isinstance(code, str) or not 1 <= len(code) <= 256
                    or set(callback) != {"code", "isSuc", "type"} or callback["isSuc"] is not True
                    or type(callback["type"]) is not int or callback["type"] != 1):
                return None
            return LocalCredential(binding.account_id, binding.account_uid, code, 0)
        except (ValueError, UnicodeError):
            return None


def local_accounts(runtime) -> list[dict]:
    with runtime.maintenance, runtime.database.transaction(write=False) as session:
        return [{"id": account.id, "name": account.name, "preset": account.preset}
                for account in session.scalars(select(m.Account).order_by(m.Account.id))]


def bound_account_name(runtime, binding: ClientBinding) -> str:
    with runtime.maintenance, runtime.database.transaction(write=False) as session:
        account = session.get(m.Account, binding.account_id)
        if account is None or account.uid != binding.account_uid:
            raise ClientConnectionError("BOUND_ACCOUNT_MISSING", "绑定的存档已不存在，请重新选择账号")
        return account.name
