import logging
import re

logger = logging.getLogger(__name__)

# Media servers sometimes prefix a certificate with an ISO country code (Plex's "gb/15", "us/PG-13").
_COUNTRY_PREFIX_RE = re.compile(r"^[A-Za-z]{2}/")


def canonical_certificate(value: str | None, system: str) -> str | None:
    """Canonical form within a system ('pg' → 'PG'), else None."""
    from cinefin.api.models import Settings

    value = (value or "").strip().upper()
    return next((valid for valid in Settings.get_valid_ratings(system) if value and value == valid.upper()), None)


def file_source_certificate(item, raw: str | None) -> None:
    """File a media-server-reported rating into the right system slot of `item.certificates` (does not save).

    Filing blindly under the configured system would pollute it with a foreign scheme (MPAA "R" on a BBFC
    install) and clobber provider-fetched certs on re-sync. So: valid for a system → that system's slot (the
    configured one first); unrecognised → the configured slot only when empty.
    """
    from cinefin.api.models import Settings

    raw = _COUNTRY_PREFIX_RE.sub("", (raw or "").strip())
    if not raw:
        return

    active = Settings.get_ratings_system()
    for system in (active, *(s for s in Settings.VALID_RATINGS_SYSTEMS if s != active)):
        if canonical := canonical_certificate(raw, system):
            item.set_certificate(system, canonical, active_system=active)
            return

    if not item.certificate_for(active):
        item.set_certificate(active, raw, active_system=active)


def denormalize_certificates(system: str | None = None) -> int:
    """Refresh Movie.certification / Trailer.content_rating from the per-system store when
    `cinema.ratings_system` changes. Returns rows updated."""
    from cinefin.api.models import Movie, Settings, Trailer

    system = system or Settings.get_ratings_system()
    updated = 0

    for model, field in ((Movie, "certification"), (Trailer, "content_rating")):
        changed = []
        for item in model.objects.all():
            value = item.certificate_for(system)
            if getattr(item, field) != value:
                setattr(item, field, value)
                changed.append(item)
        if changed:
            model.objects.bulk_update(changed, [field])
            updated += len(changed)

    if updated:
        logger.info("Re-denormalised %d certificate fields for the %s system", updated, system)
    return updated


def denormalize_certificate(item, system: str | None = None) -> None:
    """One-row denormalize_certificates() for single-item edits (a full rescan would blank hand-set scalars
    on legacy rows whose store is empty)."""
    from cinefin.api.models import Movie, Settings

    system = system or Settings.get_ratings_system()
    field = "certification" if isinstance(item, Movie) else "content_rating"
    value = item.certificate_for(system)
    if getattr(item, field) != value:
        setattr(item, field, value)
        item.save(update_fields=[field])
