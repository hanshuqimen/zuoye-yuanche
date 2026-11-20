from fastapi import APIRouter, Request

from terralocal.server.api.schemas import Command
from terralocal.server.domain import crisis_v2


class GetInfo(Command):
    pass


def router(runtime):
    api = APIRouter()

    @api.post("/crisisV2/getInfo")
    def get_info(payload: GetInfo, request: Request):
        from terralocal.server.main import credentials

        return runtime.mutate(*credentials(request), request.headers.get("seqnum", ""),
                              "crisis-v2-get-info", payload.model_dump(), crisis_v2.get_info)

    return api
