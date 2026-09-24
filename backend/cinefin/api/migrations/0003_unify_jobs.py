# Merge SyncJob + TrailerJob into a single Job table with a `kind` column.
#
# Written by hand as: create the new table, data-migrate the rows from both old
# tables (sync jobs keep their source/schedule FKs; trailer jobs get
# kind="trailer" and NULL source), then drop the old tables.
#
# Rows get fresh autoincrement ids: nothing references job ids persistently
# (the frontend only holds an id for the lifetime of a page session), and the
# combined insert is ordered by created_at so id order still matches history.
# created_at is restored with a post-insert UPDATE because auto_now_add would
# otherwise stamp migration time.

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


def copy_jobs_forward(apps, schema_editor):
    Job = apps.get_model("api", "Job")
    SyncJob = apps.get_model("api", "SyncJob")
    TrailerJob = apps.get_model("api", "TrailerJob")

    common = (
        "operation",
        "params",
        "state",
        "worker",
        "phase",
        "current",
        "total",
        "current_item",
        "counts",
        "error",
        "log",
        "started_at",
        "finished_at",
    )
    sync_only = ("schedule_id", "dry_run", "priority", "attempts", "max_attempts", "scheduled_for")

    rows = []
    for j in SyncJob.objects.order_by("created_at", "id").iterator():
        fields = {name: getattr(j, name) for name in common + sync_only}
        fields["source_id"] = j.source_id
        rows.append((j.created_at, {"kind": "sync", **fields}))
    for j in TrailerJob.objects.order_by("created_at", "id").iterator():
        fields = {name: getattr(j, name) for name in common}
        fields["cancel_requested"] = j.cancel_requested
        rows.append((j.created_at, {"kind": "trailer", **fields}))

    rows.sort(key=lambda pair: pair[0])
    for created_at, fields in rows:
        obj = Job.objects.create(**fields)
        # auto_now_add stamped "now" on insert; restore the original timestamp.
        Job.objects.filter(pk=obj.pk).update(created_at=created_at)


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0002_remove_syncsource_is_syncing"),
    ]

    operations = [
        migrations.CreateModel(
            name="Job",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "kind",
                    models.CharField(choices=[("sync", "Sync"), ("trailer", "Trailer")], db_index=True, max_length=20),
                ),
                ("operation", models.CharField(default="sync", max_length=40)),
                ("params", models.JSONField(blank=True, default=dict)),
                ("dry_run", models.BooleanField(default=False)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("running", "Running"),
                            ("cancelling", "Cancelling"),
                            ("success", "Success"),
                            ("partial", "Partial"),
                            ("failed", "Failed"),
                            ("cancelled", "Cancelled"),
                        ],
                        db_index=True,
                        default="queued",
                        max_length=20,
                    ),
                ),
                ("priority", models.IntegerField(default=0)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("max_attempts", models.PositiveIntegerField(default=1)),
                ("scheduled_for", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("worker", models.CharField(blank=True, default="", max_length=80)),
                ("cancel_requested", models.BooleanField(default=False)),
                ("phase", models.CharField(blank=True, default="", max_length=160)),
                ("current", models.IntegerField(default=0)),
                ("total", models.IntegerField(default=0)),
                ("current_item", models.CharField(blank=True, default="", max_length=300)),
                ("counts", models.JSONField(blank=True, default=dict)),
                ("plan", models.JSONField(blank=True, default=dict)),
                ("error", models.TextField(blank=True, default="")),
                ("log", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "schedule",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="jobs",
                        to="api.syncschedule",
                    ),
                ),
                (
                    "source",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="jobs",
                        to="api.syncsource",
                    ),
                ),
            ],
            options={
                "verbose_name": "Job",
                "verbose_name_plural": "Jobs",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="job",
            index=models.Index(fields=["kind", "state", "scheduled_for"], name="api_job_kind_0265d0_idx"),
        ),
        migrations.AddIndex(
            model_name="job",
            index=models.Index(fields=["source", "-created_at"], name="api_job_source__efcd0a_idx"),
        ),
        # Copy the rows from both legacy tables while they still exist.
        migrations.RunPython(copy_jobs_forward, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="syncjob",
            name="schedule",
        ),
        migrations.RemoveField(
            model_name="syncjob",
            name="source",
        ),
        migrations.DeleteModel(
            name="TrailerJob",
        ),
        migrations.DeleteModel(
            name="SyncJob",
        ),
    ]
