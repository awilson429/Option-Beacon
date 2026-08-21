from functools import lru_cache

from fastapi import Request

from api.services import OptionBeaconReadService


@lru_cache
def default_service() -> OptionBeaconReadService:
    return OptionBeaconReadService()


def get_service(request: Request) -> OptionBeaconReadService:
    return getattr(request.app.state, "service", None) or default_service()
