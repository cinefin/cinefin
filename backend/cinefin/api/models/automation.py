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
        default=0, help_text="Seconds between the lead-in starting and the programme playing"
    )
    preshow = models.JSONField(
        default=list, blank=True, help_text='Lead-in steps: [{"command": id} | {"cue": true}]; none = just the cue'
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

    def play_time(self):
        """start_time is when the lead-in begins; the programme plays lead_in seconds later."""
        return self.start_time + timedelta(seconds=self.lead_in)

    def end_time(self):
        return self.play_time() + timedelta(minutes=self.runtime)
