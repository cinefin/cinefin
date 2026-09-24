"""Escape hatch for the optional auth gate (issue #124): (re)set the single account's
password and optionally flip security.auth_enabled. One-stop lockout recovery."""

from getpass import getpass

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management.base import BaseCommand, CommandError

from cinefin.api.services import auth_service


class Command(BaseCommand):
    help = "Set the single admin account's password and optionally enable/disable authentication."

    def add_arguments(self, parser):
        parser.add_argument("--username", help="Account username (defaults to 'admin' / the existing account)")
        parser.add_argument("--password", help="New password (omit to be prompted; hidden input)")
        parser.add_argument("--enable", action="store_true", help="Enable authentication after setting the password")
        parser.add_argument(
            "--disable-auth",
            action="store_true",
            help="Disable authentication (no password change needed — the lockout recovery direction)",
        )

    def handle(self, *args, **options):
        if options["disable_auth"] and not options["password"] and not options["enable"]:
            auth_service.disable_auth()
            self.stdout.write(self.style.SUCCESS("Authentication disabled."))
            return

        password = options.get("password")
        if not password:
            password = getpass("New password: ")
            confirm = getpass("Confirm password: ")
            if password != confirm:
                raise CommandError("Passwords do not match.")

        try:
            user = auth_service.set_password(password, username=options.get("username"))
        except DjangoValidationError as e:
            raise CommandError("; ".join(e.messages)) from None

        self.stdout.write(self.style.SUCCESS(f"Password set for '{user.username}'."))

        if options["disable_auth"]:
            auth_service.disable_auth()
            self.stdout.write(self.style.SUCCESS("Authentication disabled."))
        elif options["enable"]:
            auth_service.enable_auth()
            self.stdout.write(self.style.SUCCESS("Authentication enabled."))
        else:
            state = "ON" if auth_service.auth_is_active() else "OFF"
            self.stdout.write(f"Authentication is currently {state}. Use --enable to turn it on.")
