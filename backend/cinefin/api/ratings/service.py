import logging
import re

logger = logging.getLogger(__name__)

# Media servers sometimes prefix a certificate with an ISO country code,
# e.g. Plex's "gb/15" or "us/PG-13". Stripped before canonicalising.
_COUNTRY_PREFIX_RE = re.compile(r"^[A-Za-z]{2}/")


def canonical_certificate(value: str | None, system: str) -> str | None:
    # Canonical form within a system ('pg' → 'PG'), else None.
    from cinefin.api.models import Settings

    value = (value or "").strip()
    if not value:
        return None
    for valid in Settings.get_valid_ratings(system):
        if value.upper() == valid.upper():
            return valid
    return None


def file_source_certificate(item, raw: str | None) -> None:
    """File a media-server-reported rating into the right system slot of
    `item.certificates` (does not save).

    Filing blindly under the configured system would pollute it with a foreign
    scheme (MPAA "R" on a BBFC install) and clobber provider-fetched certs on
    re-sync. So: valid-for-configured → its slot; valid-for-another → that
    system's slot (leaving configured for providers to backfill); unrecognised
    → configured slot only when empty (never overwrites a good certificate).
    """
    from cinefin.api.models import Settings

    raw = _COUNTRY_PREFIX_RE.sub("", (raw or "").strip())
    if not raw:
        return

    active = Settings.get_ratings_system()
    canonical = canonical_certificate(raw, active)
    if canonical:
        item.set_certificate(active, canonical, active_system=active)
        return

    for system in Settings.VALID_RATINGS_SYSTEMS:
        if system == active:
            continue
        canonical = canonical_certificate(raw, system)
        if canonical:
            item.set_certificate(system, canonical, active_system=active)
            return

    if not item.certificate_for(active):
        item.set_certificate(active, raw, active_system=active)


def denormalize_certificates(system: str | None = None) -> int:
    # Refresh the denormalised scalar cert fields (Movie.certification,
    # Trailer.content_rating) from the per-system store for the display system.
    # Called when `cinema.ratings_system` changes. Returns rows updated.
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
    # One-row form of denormalize_certificates() for single-item edits: the
    # full-table rescan is wasteful and would blank hand-set scalars on legacy
    # rows whose store is empty.
    from cinefin.api.models import Movie, Settings

    system = system or Settings.get_ratings_system()
    field = "certification" if isinstance(item, Movie) else "content_rating"
    value = item.certificate_for(system)
    if getattr(item, field) != value:
        setattr(item, field, value)
        item.save(update_fields=[field])
