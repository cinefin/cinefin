"""Resolve stored user-media paths to/from absolute filesystem paths.

User-media paths are stored relative to MEDIA_ROOT so a restore onto a different
layout keeps working: they resolve against the current MEDIA_ROOT at read time.
An absolute path (external file, or legacy row) passes through unchanged.
"""

from __future__ import annotations

import os

from django.conf import settings


def usermedia_abs_path(stored: str) -> str:
    if not stored or os.path.isabs(stored):
        return stored
    return os.path.join(settings.MEDIA_ROOT, stored)


def to_usermedia_relative(path: str) -> str:
    """MEDIA_ROOT-relative form of a path, for storage."""
    if not path or not os.path.isabs(path):
        return path
    root = str(settings.MEDIA_ROOT)
    if path == root or path.startswith(root + os.sep):
        return os.path.relpath(path, root)
    return path
