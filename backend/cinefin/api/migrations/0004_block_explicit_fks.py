# Replace the GenericForeignKey double-encoding on ProgrammeBlock and
# PlaylistItem with explicit typed foreign keys.
#
# Order of operations:
#   1. Add the new nullable typed FK columns.
#   2. RunPython copies each (specific_content_type, specific_object_id) pair
#      into the FK matching the ContentType's model. Dangling references
#      (the old GFK never cascaded, so deleting a Movie left a stale id
#      behind) are counted, logged and left NULL — which is exactly what the
#      GFK accessor used to resolve them to (None).
#   3. Drop the old GFK columns.
#
# on_delete=SET_NULL on all the new FKs deliberately preserves the GFK's
# "row survives target deletion" behaviour while adding integrity.

import logging

import django.db.models.deletion
from django.db import migrations, models

logger = logging.getLogger(__name__)

# ContentType.model (lowercase) -> ProgrammeBlock FK field.
# Production writes only ever stored Movie (for "movie" AND "certification"
# blocks — cert blocks reference the movie being certified), Bumper, Command
# and Trailer; "certification" is included defensively for legacy admin rows
# that pointed at a Certification clip directly.
BLOCK_FIELD_BY_MODEL = {
    "movie": "movie",
    "bumper": "bumper",
    "command": "command",
    "trailer": "trailer",
    "certification": "certification",
}

# ContentType.model -> PlaylistItem FK field. "movie" items wrap the film in
# a MoviePlayback row; legacy certification items that pointed at a Movie are
# handled separately below.
ITEM_FIELD_BY_MODEL = {
    "movieplayback": "movie_playback",
    "trailer": "trailer",
    "bumper": "bumper",
    "command": "command",
    "certification": "certification",
}


def _copy_gfk_to_fks(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    ProgrammeBlock = apps.get_model("api", "ProgrammeBlock")
    PlaylistItem = apps.get_model("api", "PlaylistItem")
    Certification = apps.get_model("api", "Certification")

    ct_by_id = {ct.id: (ct.app_label, ct.model) for ct in ContentType.objects.all()}

    def target_exists(app_label, model_name, pk):
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:
            return False
        return model.objects.filter(pk=pk).exists()

    dangling = {"blocks": 0, "items": 0}
    unknown = {"blocks": 0, "items": 0}

    blocks = ProgrammeBlock.objects.exclude(specific_content_type=None).exclude(specific_object_id=None)
    for block in blocks.iterator():
        app_label, model_name = ct_by_id.get(block.specific_content_type_id, (None, None))
        field = BLOCK_FIELD_BY_MODEL.get(model_name)
        if field is None:
            # GFK points at a model no block should ever reference.
            unknown["blocks"] += 1
            logger.warning(
                "ProgrammeBlock %s: unexpected GFK target %s.%s (content_type=%r); leaving unlinked",
                block.id,
                app_label,
                model_name,
                block.content_type,
            )
            continue
        # Cross-check: the content_type discriminator should agree with the
        # GFK model ("certification" blocks legitimately point at a Movie).
        mismatch = block.content_type and block.content_type != field
        if mismatch and not (field == "movie" and block.content_type == "certification"):
            logger.warning(
                "ProgrammeBlock %s: content_type=%r but GFK points at %s; trusting the GFK target",
                block.id,
                block.content_type,
                model_name,
            )
        if target_exists(app_label, model_name, block.specific_object_id):
            setattr(block, f"{field}_id", block.specific_object_id)
            block.save(update_fields=[f"{field}_id"])
        else:
            # Dangling GFK: target was deleted. Keep the block (matches the
            # old behaviour where content_object resolved to None).
            dangling["blocks"] += 1

    items = PlaylistItem.objects.exclude(specific_content_type=None).exclude(specific_object_id=None)
    for item in items.iterator():
        app_label, model_name = ct_by_id.get(item.specific_content_type_id, (None, None))

        if model_name == "movie" and item.content_type == "certification":
            # Legacy certification items pointed at the Movie itself; remap to
            # the movie's certification clip when one exists.
            cert = Certification.objects.filter(movie_id=item.specific_object_id).first()
            if cert is not None:
                item.certification_id = cert.id
                item.save(update_fields=["certification_id"])
            else:
                dangling["items"] += 1
            continue

        field = ITEM_FIELD_BY_MODEL.get(model_name)
        if field is None:
            unknown["items"] += 1
            logger.warning(
                "PlaylistItem %s: unexpected GFK target %s.%s (content_type=%r); leaving unlinked",
                item.id,
                app_label,
                model_name,
                item.content_type,
            )
            continue
        if target_exists(app_label, model_name, item.specific_object_id):
            setattr(item, f"{field}_id", item.specific_object_id)
            item.save(update_fields=[f"{field}_id"])
        else:
            dangling["items"] += 1

    if any(dangling.values()) or any(unknown.values()):
        logger.warning(
            "GFK->FK migration: %s dangling block ref(s), %s dangling item ref(s), "
            "%s unknown block target(s), %s unknown item target(s) left NULL",
            dangling["blocks"],
            dangling["items"],
            unknown["blocks"],
            unknown["items"],
        )


def _copy_fks_to_gfk(apps, schema_editor):
    """Reverse: repopulate the GFK columns from the typed FKs."""
    ContentType = apps.get_model("contenttypes", "ContentType")
    ProgrammeBlock = apps.get_model("api", "ProgrammeBlock")
    PlaylistItem = apps.get_model("api", "PlaylistItem")

    def ct_id(model_name):
        ct = ContentType.objects.filter(app_label="api", model=model_name).first()
        return ct.id if ct else None

    for model, field_by_model in ((ProgrammeBlock, BLOCK_FIELD_BY_MODEL), (PlaylistItem, ITEM_FIELD_BY_MODEL)):
        for model_name, field in field_by_model.items():
            type_id = ct_id(model_name)
            if type_id is None:
                continue
            for row in model.objects.exclude(**{field: None}).iterator():
                row.specific_content_type_id = type_id
                row.specific_object_id = getattr(row, f"{field}_id")
                row.save(update_fields=["specific_content_type_id", "specific_object_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0003_unify_jobs"),
    ]

    operations = [
        # 1. Add the new typed FK columns (nullable, SET_NULL — see header).
        migrations.AddField(
            model_name="playlistitem",
            name="bumper",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="api.bumper"
            ),
        ),
        migrations.AddField(
            model_name="playlistitem",
            name="certification",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="api.certification",
            ),
        ),
        migrations.AddField(
            model_name="playlistitem",
            name="command",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="api.command"
            ),
        ),
        migrations.AddField(
            model_name="playlistitem",
            name="movie_playback",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="api.movieplayback",
            ),
        ),
        migrations.AddField(
            model_name="playlistitem",
            name="trailer",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="api.trailer"
            ),
        ),
        migrations.AddField(
            model_name="programmeblock",
            name="bumper",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="api.bumper"
            ),
        ),
        migrations.AddField(
            model_name="programmeblock",
            name="certification",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="api.certification",
            ),
        ),
        migrations.AddField(
            model_name="programmeblock",
            name="command",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="api.command"
            ),
        ),
        migrations.AddField(
            model_name="programmeblock",
            name="movie",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="api.movie"
            ),
        ),
        migrations.AddField(
            model_name="programmeblock",
            name="trailer",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="api.trailer"
            ),
        ),
        # 2. Copy the GFK references into the typed FKs.
        migrations.RunPython(_copy_gfk_to_fks, _copy_fks_to_gfk),
        # 3. Drop the GFK columns.
        migrations.RemoveField(
            model_name="playlistitem",
            name="specific_content_type",
        ),
        migrations.RemoveField(
            model_name="playlistitem",
            name="specific_object_id",
        ),
        migrations.RemoveField(
            model_name="programmeblock",
            name="specific_content_type",
        ),
        migrations.RemoveField(
            model_name="programmeblock",
            name="specific_object_id",
        ),
        # 4. Record the widened content_type choices (no schema change).
        migrations.AlterField(
            model_name="playlistitem",
            name="content_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("movie", "MoviePlayback"),
                    ("bumper", "Bumper"),
                    ("command", "Command"),
                    ("trailer_rule", "Trailer Rule"),
                    ("certification", "Certification"),
                    ("trailer", "Trailer"),
                    ("system", "System"),
                ],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="programmeblock",
            name="content_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("movie", "Movie"),
                    ("bumper", "Bumper"),
                    ("command", "Command"),
                    ("trailer_rule", "Trailer Rule"),
                    ("certification", "Certification"),
                    ("trailer", "Trailer"),
                    ("random_movie", "Random Movie"),
                    ("random_bumper", "Random Bumper"),
                    ("audio_bumper", "Audio Bumper"),
                ],
                max_length=20,
            ),
        ),
    ]
