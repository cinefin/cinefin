"""Seed the initial PlayoutHost row (Phase 5, additive/reversible).

If the ``playout.agent.*`` settings describe an agent, seed a PlayoutHost from
them (active). Otherwise seed a default loopback host (inactive). The
``playout.agent.*`` settings are deliberately left in place — the later cutover
removes them, not this migration.

Reverse deletes only the row this migration seeded (matched by a marker so a
user-edited fleet is never clobbered).
"""

from django.db import migrations

# Marker stashed on the seeded row so the reverse only removes what we created.
SEED_NAME = "Playout host"
SEED_DEFAULT_URL = "http://127.0.0.1:8089"


def _read_agent_settings(apps):
    """Best-effort read of playout.agent.{url,token,enabled} from the singleton
    Settings row, without importing the live model (migration-safe)."""
    Settings = apps.get_model("api", "Settings")
    row = Settings.objects.first()
    data = (row.data if row else {}) or {}
    agent = ((data.get("playout") or {}).get("agent")) or {}
    return {
        "url": (agent.get("url") or "").strip(),
        "token": agent.get("token") or "",
        "enabled": bool(agent.get("enabled", True)),
    }


def seed_playout_host(apps, schema_editor):
    PlayoutHost = apps.get_model("api", "PlayoutHost")
    # Idempotent: never seed twice (e.g. re-run after a partial migrate).
    if PlayoutHost.objects.exists():
        return

    agent = _read_agent_settings(apps)
    if agent["url"]:
        # A configured agent → active host carrying its url/token/enabled.
        PlayoutHost.objects.create(
            name=SEED_NAME,
            base_url=agent["url"],
            token=agent["token"],
            enabled=agent["enabled"],
            is_active=True,
        )
    else:
        # No agent configured → an inactive default loopback host, enabled and
        # ready to be pointed at an agent later.
        PlayoutHost.objects.create(
            name=SEED_NAME,
            base_url=SEED_DEFAULT_URL,
            token="",
            enabled=True,
            is_active=False,
        )


def unseed_playout_host(apps, schema_editor):
    PlayoutHost = apps.get_model("api", "PlayoutHost")
    PlayoutHost.objects.filter(name=SEED_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0018_playouthost"),
    ]

    operations = [
        migrations.RunPython(seed_playout_host, unseed_playout_host),
    ]
