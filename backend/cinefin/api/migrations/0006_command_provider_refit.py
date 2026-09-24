# Command provider refit: command_type/command/http_config/shell collapse into
# provider + config, and CommandRun (execution history) is created. Ordered so
# the data conversion reads the old columns before they are dropped.

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


def convert_commands_forward(apps, schema_editor):
    Command = apps.get_model("api", "Command")
    for cmd in Command.objects.all():
        if cmd.command_type == "http":
            http = cmd.http_config or {}
            cmd.provider = "rest"
            cmd.config = {
                "method": (http.get("method") or "GET").upper(),
                "url": cmd.command,
                "headers": http.get("headers") or {},
                "body": http.get("body") or {},
            }
        else:
            cmd.provider = "shell"
            cmd.config = {"command": cmd.command}
        cmd.save(update_fields=["provider", "config"])


def convert_commands_backward(apps, schema_editor):
    Command = apps.get_model("api", "Command")
    for cmd in Command.objects.all():
        if cmd.provider == "rest":
            cmd.command_type = "http"
            cmd.command = cmd.config.get("url", "")
            cmd.http_config = {
                "method": cmd.config.get("method", "GET"),
                "headers": cmd.config.get("headers", {}),
                "body": cmd.config.get("body", {}),
            }
            cmd.shell = False
        else:  # shell and homeassistant both degrade to shell
            cmd.command_type = "shell"
            cmd.command = cmd.config.get("command", "")
            cmd.shell = True
        cmd.save(update_fields=["command_type", "command", "http_config", "shell"])


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0005_playoutsession"),
    ]

    operations = [
        migrations.AddField(
            model_name="command",
            name="config",
            field=models.JSONField(blank=True, default=dict, help_text="Provider-specific configuration"),
        ),
        migrations.AddField(
            model_name="command",
            name="provider",
            field=models.CharField(
                choices=[("shell", "Shell Command"), ("rest", "REST Request"), ("homeassistant", "Home Assistant")],
                default="shell",
                max_length=20,
            ),
        ),
        migrations.RunPython(convert_commands_forward, convert_commands_backward),
        migrations.RemoveField(model_name="command", name="command"),
        migrations.RemoveField(model_name="command", name="command_type"),
        migrations.RemoveField(model_name="command", name="http_config"),
        migrations.RemoveField(model_name="command", name="shell"),
        migrations.CreateModel(
            name="CommandRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("command_name", models.CharField(max_length=255)),
                ("provider", models.CharField(max_length=20)),
                (
                    "trigger",
                    models.CharField(
                        help_text="What fired it: test / remote / block / credits / preshow", max_length=40
                    ),
                ),
                ("started_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("ok", models.BooleanField(default=False)),
                ("detail", models.CharField(blank=True, default="", max_length=200)),
                ("output", models.TextField(blank=True, default="")),
                (
                    "command",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="runs",
                        to="api.command",
                    ),
                ),
            ],
            options={
                "ordering": ["-started_at"],
            },
        ),
    ]
