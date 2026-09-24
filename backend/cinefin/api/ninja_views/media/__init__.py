from ninja import Router

from .downloads import downloads_api
from .management import management_api
from .movies import movies_api
from .uploads import uploads_api

media_api = Router()

# Order matters: specific patterns before catch-all; management last (/{media_id} catch-all).
media_api.add_router("/", uploads_api)
media_api.add_router("/", downloads_api)
media_api.add_router("/", movies_api)
media_api.add_router("/", management_api)

__all__ = ["media_api"]
