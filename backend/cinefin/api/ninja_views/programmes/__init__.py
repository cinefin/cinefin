from ninja import Router

from .creation import creation_api
from .management import management_api
from .playlists import playlists_api

programme_api = Router()

programme_api.add_router("/", creation_api)
programme_api.add_router("/", management_api)
programme_api.add_router("/", playlists_api)

__all__ = ["programme_api"]
