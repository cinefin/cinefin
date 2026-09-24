"""Pair a playout agent non-interactively (create/update + activate a PlayoutHost).

Matching is by base_url, so re-running is idempotent and the seeded default
loopback row (migration 0019) is adopted rather than duplicated.
"""

from django.core.management.base import BaseCommand

from cinefin.api.models import PlayoutHost

DEFAULT_NAME = "Playout host"


class Command(BaseCommand):
    help = "Create or update a PlayoutHost by URL, set its token, and make it the active host."

    def add_arguments(self, parser):
        parser.add_argument("--url", required=True, help="Agent base URL, e.g. http://127.0.0.1:8089")
        parser.add_argument("--token", required=True, help="Agent bearer token (from the agent's config.toml)")
        parser.add_argument(
            "--name", default=None, help=f'Friendly name for a newly created host (default "{DEFAULT_NAME}")'
        )

    def handle(self, *args, **options):
        base_url = options["url"].strip().rstrip("/")

        host = PlayoutHost.objects.filter(base_url=base_url).first()
        created = host is None
        if created:
            host = PlayoutHost(base_url=base_url, name=options["name"] or DEFAULT_NAME)
        elif options["name"]:
            host.name = options["name"]

        host.token = options["token"]
        host.enabled = True
        host.is_active = True  # save() clears is_active on every other row
        host.save()

        verb = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{verb} active playout host '{host.name}' @ {host.base_url}"))
