"""Prune old terminal-state background Job rows (sync + trailer history)."""

from django.core.management.base import BaseCommand

from cinefin.api.sync.retention import DEFAULT_KEEP_COUNT, DEFAULT_KEEP_DAYS, prune_jobs


class Command(BaseCommand):
    help = (
        "Delete terminal-state Job rows that are BOTH older than --days and "
        "outside the --keep most recent of their kind. Active jobs are never touched."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=DEFAULT_KEEP_DAYS, help=f"Keep anything younger (default {DEFAULT_KEEP_DAYS})"
        )
        parser.add_argument(
            "--keep",
            type=int,
            default=DEFAULT_KEEP_COUNT,
            help=f"Keep the N most recent per kind regardless of age (default {DEFAULT_KEEP_COUNT})",
        )
        parser.add_argument("--dry-run", action="store_true", help="Only report what would be deleted")

    def handle(self, *args, **options):
        deleted = prune_jobs(days=options["days"], keep=options["keep"], dry_run=options["dry_run"])
        verb = "Would delete" if options["dry_run"] else "Deleted"
        total = sum(deleted.values())
        per_kind = ", ".join(f"{kind}: {count}" for kind, count in deleted.items())
        self.stdout.write(self.style.SUCCESS(f"{verb} {total} job row(s) ({per_kind})"))
