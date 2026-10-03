"""ASGI entrypoint: Django serves all HTTP; the /ws/events WebSocket is a small raw-ASGI app beside it."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cinefin.settings")

# Readies Django (apps, settings) as a side effect — must run before importing
# anything that touches models/services.
_django_app = get_asgi_application()


async def application(scope, receive, send):
    if scope["type"] == "websocket" and scope.get("path") == "/ws/events":
        from cinefin.api.views.ws_events import events_ws_app

        await events_ws_app(scope, receive, send)
        return
    await _django_app(scope, receive, send)
