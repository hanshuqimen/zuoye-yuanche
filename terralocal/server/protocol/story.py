from fastapi import APIRouter, Request
from pydantic import Field

from terralocal.server.api.schemas import Command
from terralocal.server.domain import story


class FinishStory(Command):
    storyId: str = Field(min_length=1, max_length=160)


def router(runtime):
    api = APIRouter()

    @api.post("/story/finishStory")
    def finish_story(payload: FinishStory, request: Request):
        from terralocal.server.main import credentials

        return runtime.mutate(*credentials(request), request.headers.get("seqnum", ""),
                              "story-finish", payload.model_dump(), lambda ctx: story.finish(ctx, payload.storyId))

    return api
