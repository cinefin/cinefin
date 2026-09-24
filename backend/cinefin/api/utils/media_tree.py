"""The MEDIA_ROOT subdirectory tree the app writes into, plus a writability check.

Single source of truth shared by boot-time provisioning (ApiConfig._ensure_media_tree)
and the health page, so the two can't drift.
"""

import os

from django.conf import settings

# Created at boot (may be a freshly mounted, empty volume) and checked for writability.
MEDIA_SUBDIRS = (
    "certifications",  # generated rating cards
    "media",  # uploaded/downloaded media files
    "pos/bbfc",  # user-supplied thermal-printer rating logos
    "programme_title_images",  # title template images
    "programme_titles",  # generated title card videos
    "ratings",  # user overrides for rating card backgrounds
    "ratings/BBFC",  # user-supplied static certification videos (<cert>.mp4)
    "ratings/MPAA",  # user-supplied static certification videos (<cert>.mp4)
    "screenshots",  # movie screenshots
    "ticket_images",  # ticket image library (image elements in ticket designs)
    "ticket_logos/processed",  # ticket printer logos
    "trailers",  # downloaded/uploaded trailer files
)

# Deliberately NOT user-configurable: trailers always sit inside the user-media
# tree so a single mounted volume holds everything and the streaming allow-list needs no special case.
TRAILER_SUBDIR = "trailers"


def media_subdir_paths() -> list[str]:
    return [os.path.join(settings.MEDIA_ROOT, sub) for sub in MEDIA_SUBDIRS]


def trailer_dir() -> str:
    return os.path.join(settings.MEDIA_ROOT, TRAILER_SUBDIR)


def unwritable_media_subdirs() -> list[str]:
    """Existing media subdirs not writable by this process. Non-destructive."""
    return [p for p in media_subdir_paths() if os.path.isdir(p) and not os.access(p, os.W_OK)]
