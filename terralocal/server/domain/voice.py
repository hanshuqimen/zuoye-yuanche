"""Voice preferences constrained by the frozen character voice catalog."""

from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence import models as m


def choices(ctx: Context, char_id: str) -> dict:
    table = ctx.data.table("charword_table")
    row = table["voiceLangDict"].get(char_id)
    if row is None:
        raise DomainError("VOICE_CATALOG_MISSING", "此干员缺少匹配版本的语音数据", 503)
    available = dict(row["dict"])
    for language, windows in table.get("startTimeWithTypeDict", {}).items():
        if any(char_id in window["charSet"] and window["timestamp"] > ctx.now for window in windows):
            available.pop(language, None)
    return available


def validate_language(ctx: Context, language: str) -> None:
    if language not in ctx.data.table("charword_table")["voiceLangTypeDict"]:
        raise DomainError("INVALID_VOICE_LANGUAGE", "语音类型不在当前版本的数据中")


def initial_language(ctx: Context, char_id: str) -> str:
    available = choices(ctx, char_id)
    preferred = ctx.profile.flags.get("voiceLan")
    if preferred in available:
        return preferred
    default = ctx.data.table("charword_table")["charDefaultTypeDict"].get(char_id)
    if default not in available:
        raise DomainError("VOICE_DEFAULT_INVALID", "干员默认语音不可用", 503)
    return default


def batch_set(ctx: Context, language: str) -> dict:
    validate_language(ctx, language)
    for op in ctx.rows(m.Operator):
        available = choices(ctx, op.char_id)
        if language in available:
            op.voice_language = language
        elif op.voice_language not in available:
            default = ctx.data.table("charword_table")["charDefaultTypeDict"].get(op.char_id)
            if default not in available:
                raise DomainError("VOICE_DEFAULT_INVALID", "干员默认语音不可用", 503)
            op.voice_language = default
    ctx.profile.flags = {**ctx.profile.flags, "voiceLan": language}
    ctx.emit("GlobalVoiceChanged", language=language)
    # The historical batch response has an object-valued result. The actual
    # preferences are committed and included in playerDataDelta by Runtime.
    return {"result": {}}


def set_for_operators(ctx: Context, language: str, operator_ids: list[int]) -> dict:
    validate_language(ctx, language)
    checked = []
    for operator_id in set(operator_ids):
        op = ctx.operator(operator_id)
        if language not in choices(ctx, op.char_id):
            raise DomainError("VOICE_UNAVAILABLE", "该干员没有已开放的此语音")
        checked.append(op)
    for op in checked:
        op.voice_language = language
    return {}
