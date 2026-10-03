"""Trailer filename templating. Identity lives in the DB; the on-disk name is a cosmetic, user-configurable template."""

import os
import re
import string
from typing import Any

DEFAULT_FILENAME_TEMPLATE = "{title} ({year}) [tmdb-{tmdbid}]"
DEFAULT_FOLDER_TEMPLATE = "{year}"  # '' = flat
DEFAULT_EXTENSION = "mp4"

AVAILABLE_TOKENS: list[dict[str, str]] = [
    {"token": "{title}", "description": "Movie title"},
    {"token": "{year}", "description": "Release year"},
    {"token": "{month}", "description": "Release month (1-12)"},
    {"token": "{month:02d}", "description": "Release month, zero-padded (03)"},
    {"token": "{tmdbid}", "description": "TMDB id"},
    {"token": "{certification}", "description": "Certificate in the active ratings system"},
    {"token": "{director}", "description": "Director name"},
]

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_TMDB_BRACKET = re.compile(r"tmdb-(\d+)", re.IGNORECASE)
_LEGACY_SUFFIX = re.compile(r"_(\d+)\.[A-Za-z0-9]+$")  # old YYYY-MM_<tmdbid>.ext


class _SafeFormatter(string.Formatter):
    def get_value(self, key, args, kwargs):
        if isinstance(key, str):
            return kwargs.get(key, "")
        return super().get_value(key, args, kwargs)

    def format_field(self, value, format_spec):
        if value == "":
            return ""
        try:
            return super().format_field(value, format_spec)
        except (ValueError, TypeError):
            return str(value)


_FORMATTER = _SafeFormatter()


def sanitize_component(value: Any, max_len: int = 180) -> str:
    s = _ILLEGAL.sub("", str(value or ""))
    s = re.sub(r"\s+", " ", s).strip()
    s = s.strip(" .")  # Windows dislikes trailing dots/spaces
    return s[:max_len].strip(" .")


def _cleanup(name: str) -> str:
    name = re.sub(r"\[\s*tmdb-\s*\]", "", name)  # empty [tmdb-]
    name = re.sub(r"\(\s*\)", "", name)  # empty ()
    name = re.sub(r"\[\s*\]", "", name)  # empty []
    name = re.sub(r"\s{2,}", " ", name)
    name = name.strip()
    name = re.sub(r"[\s\-]+$", "", name)  # dangling separators
    return name.strip()


def render_full_path(
    trailer_dir: str, src: dict[str, Any], filename_template: str, folder_template: str, ext: str = DEFAULT_EXTENSION
) -> str:
    meta = {
        "title": sanitize_component(src.get("title", "")),
        "director": sanitize_component(src.get("director", "")),
        "certification": sanitize_component(src.get("certification", "")),
        "year": src.get("year") or "",
        "month": src.get("month") or "",
        "tmdbid": src.get("tmdbid") or "",
    }
    name = _cleanup(_FORMATTER.format(filename_template, **meta)).replace("/", "-").replace("\\", "-")
    if not name:
        name = f"tmdb-{meta['tmdbid']}" if meta["tmdbid"] else "trailer"
    folders = (
        [sanitize_component(seg) for seg in _FORMATTER.format(folder_template, **meta).split("/")]
        if folder_template
        else []
    )
    return os.path.join(trailer_dir, *[f for f in folders if f], f"{name}.{ext.lstrip('.')}")


def recover_tmdbid(filename: str) -> int | None:
    """Best-effort TMDB id recovery from a filename (new [tmdb-NNNN] and legacy YYYY-MM_NNNN.ext forms)."""
    m = _TMDB_BRACKET.search(filename) or _LEGACY_SUFFIX.search(filename)
    return int(m.group(1)) if m else None
