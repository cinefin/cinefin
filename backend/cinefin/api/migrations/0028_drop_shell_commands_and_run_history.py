"""Retire the shell command provider and the persisted run history.

Commands now reach the outside world only over HTTP (REST) or Home Assistant.
Shell commands ran arbitrary strings through ``subprocess`` with ``shell=True``
as the web process' user, which is a lot of blast radius for a home cinema
automation, and nothing in the product needed it that REST could not do.

Shell command rows are DELETED rather than retired, so the references they
leave behind are tidied here rather than left dangling:

* a command BLOCK in a running order is removed with its command (the block
  has nothing left to run) — the programme's playlist regenerates from the
  blocks on its next save or playout load;
* the same for a command item in a template;
* a credits marker or playlist-item reference is nulled by the FK's own
  ``on_delete=SET_NULL``;
* the pre-show list in Settings is a JSON list of ids, which no FK maintains,
  so stale ids are stripped explicitly.

``CommandRun`` (and its table) goes entirely: execution outcomes are logged to
``cinefin.automation`` and handed back inline to whoever asked for the run.
"""

from django.db import migrations, models


def drop_shell_commands(apps, schema_editor):
    Command = apps.get_model("api", "Command")
    ProgrammeBlock = apps.get_model("api", "ProgrammeBlock")
    ProgrammeTemplateItem = apps.get_model("api", "ProgrammeTemplateItem")
    Settings = apps.get_model("api", "Settings")

    shell_ids = list(Command.objects.filter(provider="shell").values_list("id", flat=True))
    if not shell_ids:
        return

    # Blocks/items whose whole purpose was to run one of these.
    ProgrammeBlock.objects.filter(content_type="command", command_id__in=shell_ids).delete()
    ProgrammeTemplateItem.objects.filter(item_type="command", command_id__in=shell_ids).delete()

    # The pre-show list is plain JSON — no FK keeps it honest.
    for row in Settings.objects.all():
        data = row.data or {}
        scheduler = data.get("scheduler")
        if not isinstance(scheduler, dict):
            continue
        preshow = scheduler.get("preshow_commands")
        if not isinstance(preshow, list):
            continue
        kept = [i for i in preshow if i not in shell_ids]
        if kept != preshow:
            scheduler["preshow_commands"] = kept
            row.data = data
            row.save(update_fields=["data"])

    Command.objects.filter(id__in=shell_ids).delete()


def noop_reverse(apps, schema_editor):
    """Nothing to restore — the definitions are gone, not archived."""


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0027_playouthost_kind_playouthost_socket_path_and_more"),
    ]

    operations = [
        migrations.RunPython(drop_shell_commands, noop_reverse),
        migrations.AlterField(
            model_name="command",
            name="provider",
            field=models.CharField(
                choices=[("rest", "REST Request"), ("homeassistant", "Home Assistant")],
                default="rest",
                max_length=20,
            ),
        ),
        migrations.DeleteModel(name="CommandRun"),
    ]
