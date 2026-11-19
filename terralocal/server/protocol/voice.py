"""Observed global voice selection and reference-level per-character adapter."""

from fastapi import APIRouter, Request
from pydantic import Field, PositiveInt

from terralocal.server.api.schemas import Command
from terralocal.server.domain import voice


class BatchVoice(Command):
    voiceLan: str = Field(min_length=1, max_length=32)


class CharacterVoice(BatchVoice):
    charList: list[PositiveInt] = Field(min_length=1, max_length=1000)


def router(runtime) -> APIRouter:
    api = APIRouter()

    def mutate(request, payload, operation, action):
        from terralocal.server.main import credentials

        return runtime.mutate(*credentials(request), request.headers.get("seqnum", ""),
                              operation, payload.model_dump(), action)

    @api.post("/charBuild/batchSetCharVoiceLan")
    def batch_voice(payload: BatchVoice, request: Request):
        return mutate(request, payload, "batch-voice", lambda ctx: voice.batch_set(ctx, payload.voiceLan))

    @api.post("/charBuild/setCharVoiceLan")
    def character_voice(payload: CharacterVoice, request: Request):
        return mutate(request, payload, "character-voice", lambda ctx: voice.set_for_operators(
            ctx, payload.voiceLan, payload.charList))

    return api
