"""
API v2 URL Configuration - Fully migrated to Django Ninja
"""

from django.urls import path

# Import Django Ninja API
from cinefin.api.ninja_api import api as ninja_api

# All real-time now rides the single WebSocket (/ws/events, see cinefin.asgi +
# api/views/ws_events.py): playout status, job progress and resource-change
# invalidations. No SSE endpoints remain — the in-app log viewer reads the
# snapshot GET /api/v2/logs (Ninja) instead of the old /logs/stream SSE.

urlpatterns = [
    # Django Ninja API - All V2 endpoints now use Django Ninja
    path("", ninja_api.urls),
]
