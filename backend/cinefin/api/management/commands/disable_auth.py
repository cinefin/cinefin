"""Lockout recovery: turn the optional auth gate off (issue #124)."""

from django.core.management.base import BaseCommand

from cinefin.api.services import auth_service


class Command(BaseCommand):
    help = "Disable authentication (security.auth_enabled = False) so the UI/API are open again."

    def handle(self, *args, **options):
        auth_service.disable_auth()
        self.stdout.write(self.style.SUCCESS("Authentication disabled. The app is open again."))
