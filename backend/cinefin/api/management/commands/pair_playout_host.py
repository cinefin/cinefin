"""Pair a playout agent non-interactively, with the code on the player's screen.

Creates (or re-pairs) the PlayoutHost and makes it the active host. A host is
matched by the agent's id, then by base_url, so re-running is idempotent and the
seeded default loopback row (migration 0019) is adopted rather than duplicated.
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from cinefin.api.exceptions import APIException
from cinefin.api.models import PlayoutHost
from cinefin.api.services.playout_agent_service import PlayoutAgentService

DEFAULT_NAME = "Playout host"


class Command(BaseCommand):
    help = "Pair a playout agent by its on-screen code and make it the active host."

    def add_arguments(self, parser):
        parser.add_argument("--url", required=True, help="Agent base URL, e.g. http://10.0.0.5:8089")
        parser.add_argument("--code", required=True, help="The 6-digit code shown on the player's screen")
        parser.add_argument("--name", default=None, help="Name for the host (default: the player's own name)")

    def handle(self, *args, **options):
        base_url = options["url"].strip().rstrip("/")
        try:
            answer = PlayoutAgentService.pair(base_url, options["code"])
        except APIException as e:
            raise CommandError(e.message) from e

        agent_id = str(answer.get("id") or "")
        host = PlayoutHost.objects.filter(kind=PlayoutHost.KIND_AGENT, agent_id=agent_id).first() if agent_id else None
        host = host or PlayoutHost.objects.filter(base_url=base_url).first()
        created = host is None
        if created:
            host = PlayoutHost(base_url=base_url)
        if options["name"] or created:
            host.name = options["name"] or str(answer.get("name") or "") or DEFAULT_NAME

        host.kind = PlayoutHost.KIND_AGENT
        host.base_url = base_url
        host.token = answer["token"]
        host.agent_id = agent_id
        host.enabled = True
        host.last_seen_at = timezone.now()
        host.is_active = True  # save() clears is_active on every other row
        host.save()

        verb = "Paired new" if created else "Re-paired"
        self.stdout.write(self.style.SUCCESS(f"{verb} active playout host '{host.name}' @ {host.base_url}"))
