"""MPAA certificate lookups against filmratings.com (CARA).

Regex-parses the server-rendered search-results cards (rating = icon alt text). The admin-ajax backend only
serves infinite-scroll continuation pages, so the plain page fetch is the entry point. Throttled by the caller.
"""

import re

from ..base import RatingsProvider
from ..registry import register

_ITEM_RE = re.compile(r'<div class="item[^"]*">(.*?)<!--end-item-->', re.S)
_TITLE_RE = re.compile(r'<div class="item-title">(.*?)</div>', re.S)
_RATING_RE = re.compile(r'<div class="image-rating">.*?alt="([^"]*)"', re.S)
_YEAR_RATED_RE = re.compile(r'Year Rated:\s*</span>\s*<span class="text">\s*(\d{4})', re.S)


def _text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


@register
class MPAAProvider(RatingsProvider):
    system = "MPAA"
    display_name = "filmratings.com"
    search_url = "https://www.filmratings.com/search-results/"
    query_param = "search"

    def _search(self, query: str) -> list[dict]:
        # No results container = an unknown page: raise (retry later) rather than read a broken scrape as "no
        # rating". A container with no cards is a genuine empty result.
        text = self._fetch(query)
        if "section-movies" not in text:
            raise ValueError("filmratings.com answered but the results page looks unfamiliar (site redesign?)")
        candidates = []
        for chunk in _ITEM_RE.findall(text):
            title_m, rating_m = _TITLE_RE.search(chunk), _RATING_RE.search(chunk)
            if title_m and rating_m:
                year_m = _YEAR_RATED_RE.search(chunk)
                candidates.append(
                    {
                        "title": _text(title_m.group(1)),
                        "rating": _text(rating_m.group(1)).upper(),
                        "year": int(year_m.group(1)) if year_m else None,
                    }
                )
        return candidates
