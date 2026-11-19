"""Portable configuration. No official endpoints or credentials are runtime dependencies."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


def default_data_dir() -> Path:
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    return Path(os.environ.get("TERRALOCAL_DATA_DIR", str(base / "data"))).resolve()


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data_dir: Path = Field(default_factory=default_data_dir)
    game_host: str = "127.0.0.1"
    game_port: int = Field(default=8443, ge=1024, le=65535)
    admin_host: str = "127.0.0.1"
    admin_port: int = Field(default=8080, ge=1024, le=65535)
    advertised_url: str = "https://127.0.0.1:8443"
    client_profile: str = Field(default="cn-android-2.7.71", pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
    gamedata_hash: str | None = None
    log_level: str = "INFO"
    tls: bool = True
    tls_dns_names: list[str] = Field(default_factory=list, max_length=32)
    admin_password_hash: str | None = None
    request_limit: int = Field(default=8 * 1024 * 1024, ge=1024, le=32 * 1024 * 1024)
    session_ttl: int = Field(default=86400, ge=60, le=7 * 86400)
    emulator_dir: Path | None = None
    emulator_index: int | None = None

    @field_validator("data_dir")
    @classmethod
    def resolve_data_dir(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @field_validator("gamedata_hash")
    @classmethod
    def validate_hash(cls, value: str | None) -> str | None:
        if value is not None and (len(value) != 64 or any(c not in "0123456789abcdef" for c in value)):
            raise ValueError("gamedata_hash 必须为 SHA-256")
        return value

    @field_validator("advertised_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise ValueError("advertised_url 必须是本地服务器的 http(s) 地址")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("advertised_url 不能包含路径、查询或 fragment")
        return value.rstrip("/")

    @field_validator("tls_dns_names")
    @classmethod
    def validate_dns_names(cls, value: list[str]) -> list[str]:
        import re

        if any(not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,251}[a-zA-Z0-9])?", name)
               for name in value):
            raise ValueError("TLS DNS 名称非法")
        return sorted(set(value))

    @property
    def database_path(self) -> Path:
        return self.data_dir / "terralocal.sqlite3"

    def validate_startup(self) -> None:
        if self.admin_host != "127.0.0.1" and not self.admin_password_hash:
            raise ValueError("管理面板开放 LAN 前必须配置密码")
        if self.game_port == self.admin_port:
            raise ValueError("游戏端口与管理端口必须不同")

    def prepare(self) -> None:
        self.validate_startup()
        for name in ("cache", "profiles", "logs", "backups", "client", "fixtures", "certs"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        self.prepare()
        path = self.data_dir / "settings.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary, path)


def load_settings(data_dir: Path | None = None) -> Settings:
    directory = (data_dir or default_data_dir()).resolve()
    path = directory / "settings.json"
    content = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(content, dict):
        raise ValueError("settings.json 必须是 JSON 对象")
    content["data_dir"] = directory
    return Settings.model_validate(content)
