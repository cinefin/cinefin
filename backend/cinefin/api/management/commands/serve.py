"""Run the app under uvicorn (ASGI) — the cross-platform production entrypoint.

ASGI is required for the real-time WebSocket (/ws/events). One process only: the
MPV service is a per-process singleton and the in-process event bus must reach
every client — so never scale with workers.
"""

from django.core.management.base import BaseCommand

DEFAULT_LISTEN = "0.0.0.0:8000"


class Command(BaseCommand):
    help = "Serve the app with uvicorn (single ASGI process) — the cross-platform entrypoint."

    def add_arguments(self, parser):
        parser.add_argument(
            "--listen",
            default=DEFAULT_LISTEN,
            help=f"host:port to bind, e.g. 127.0.0.1:8000 (default {DEFAULT_LISTEN})",
        )

    def handle(self, *args, **options):
        import uvicorn

        host, _, port = options["listen"].rpartition(":")
        host = host or "0.0.0.0"
        self.stdout.write(f"Serving on http://{options['listen']} (uvicorn, ASGI)")
        uvicorn.run("cinefin.asgi:application", host=host, port=int(port), log_level="info")
