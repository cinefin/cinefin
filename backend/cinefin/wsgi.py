"""WSGI entrypoint (runserver); deployments run the ASGI app in asgi.py."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cinefin.settings")

application = get_wsgi_application()
