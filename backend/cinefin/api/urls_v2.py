"""The /api/v2/ URL conf: everything is the Django Ninja API (real time rides the /ws/events WebSocket)."""

from django.urls import path

from cinefin.api.ninja_api import api as ninja_api

urlpatterns = [path("", ninja_api.urls)]
