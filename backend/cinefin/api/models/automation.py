"""Automation models: executable command definitions and programme schedules.
Commands are pure definitions; execution lives in services.command_runner."""

from datetime import timedelta

from django.db import models


class Command(models.Model):
    name = models.CharField(max_length=255)
    # A provider id from the cinefin.plugins registry (built-in or contrib); not a fixed choice list.
    provider = models.CharField(max_length=40, default="rest")
    config = models.JSONField(default=dict, blank=True, help_text="Provider-specific configuration")
    duration = models.FloatField(default=0.0, help_text="Duration in seconds that this command takes to execute")

    def __str__(self):
        return self.name


class ProgrammeSchedule(models.Model):
    programme = models.ForeignKey("Programme", on_delete=models.CASCADE, related_name="schedules")
    start_time = models.DateTimeField()
    runtime = models.PositiveIntegerField(default=0, help_text="Duration in minutes")
    lead_in = models.PositiveIntegerField(
        null=True, blank=True, help_text="Seconds before the programme plays; null = the scheduler.lead_in default"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        default="scheduled",
        choices=[
            ("scheduled", "Scheduled"),
            ("running", "Running"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
            ("failed", "Failed"),
            ("missed", "Missed"),
        ],
    )
    last_error = models.TextField(blank=True, default="", help_text="Reason a run failed, if any")

    class Meta:
        ordering = ["start_time"]

    def __str__(self):
        return f"{self.programme.name} - Scheduled for {self.start_time.strftime('%Y-%m-%d %H:%M')}"

    def lead_in_seconds(self, default: int | None = None) -> int:
        """This screening's lead-in: its override, else the global default (pass it in to save a query)."""
        if self.lead_in is not None:
            return self.lead_in
        return default_lead_in() if default is None else default

    def play_time(self, default: int | None = None):
        """start_time is when the lead-in begins; the programme plays this much later."""
        return self.start_time + timedelta(seconds=self.lead_in_seconds(default))

    def end_time(self, default: int | None = None):
        return self.play_time(default) + timedelta(minutes=self.runtime)


def default_lead_in() -> int:
    from .settings import Settings

    value = Settings.get("scheduler.lead_in")
    return int(value) if isinstance(value, int | float) and value > 0 else 0
