"""Filesystem containment checks: a data-supplied path must never escape its root."""

import os


def contained_in(path: str, root: str) -> bool:
    """True if `path` (symlinks resolved) lives under `root`."""
    if not path or not root:
        return False
    real_path = os.path.realpath(path)
    real_root = os.path.realpath(root)
    try:
        return os.path.commonpath([real_path, real_root]) == real_root
    except ValueError:  # mixed absolute/relative or different drives
        return False
