"""A library has ONE source: keep the first enabled one, drop the rest.

Two sources were never really supported: both plugins look a film up by
``Movie.objects.filter(tmdbid=...)`` — globally, not per source — so the same
film on Plex and Jellyfin matched one row and whichever server synced last
silently overwrote the other's file path, resolution, size and track lists.
The library flip-flopped with whichever sync ran most recently.

Rather than model several servers properly, the product now takes one. This
migration makes existing installs match: the first ENABLED source survives
(falling back to the lowest-id source when none are enabled), and any others
are deleted along with their schedules and job history.

Films from a deleted source are NOT deleted — ``Movie.sync_source`` is
SET_NULL, so they stay in the library with their metadata and their programme
blocks intact. They simply stop being synced, and will show as belonging to
no source until they are removed or re-imported from the surviving server.
Deleting someone's films as a side effect of an upgrade would be far worse
than leaving them a tidy-up.

Almost every install has exactly one source, in which case this does nothing.
"""

from django.db import migrations


def keep_one_source(apps, schema_editor):
    SyncSource = apps.get_model("api", "SyncSource")

    sources = list(SyncSource.objects.order_by("id"))
    if len(sources) < 2:
        return

    keeper = next((s for s in sources if s.enabled), sources[0])
    doomed = [s for s in sources if s.id != keeper.id]

    Movie = apps.get_model("api", "Movie")
    orphaned = Movie.objects.filter(sync_source_id__in=[s.id for s in doomed]).count()
    print(
        f"\n  Single library source: keeping '{keeper.name}', removing "
        f"{len(doomed)} other source(s). {orphaned} film(s) will remain in the "
        f"library without a source."
    )
    SyncSource.objects.filter(id__in=[s.id for s in doomed]).delete()


class Migration(migrations.Migration):
    dependencies = [("api", "0028_drop_shell_commands_and_run_history")]

    operations = [
        # Irreversible by nature: the removed sources' tokens and libraries are
        # gone, and inventing them back is not possible.
        migrations.RunPython(keep_one_source),
    ]
