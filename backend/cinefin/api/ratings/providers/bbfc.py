"""BBFC certificate lookups against bbfc.co.uk.

Parses the search page's embedded `__NEXT_DATA__` JSON — stable across deploys, unlike the
/_next/data/<buildId>/ routes whose buildId churns per release. Throttled by the caller.
"""

import json
import re

from ..base import RatingsProvider
from ..registry import register

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_TITLE_YEAR_RE = re.compile(r"^(?P<title>.*?)\s*\((?P<year>\d{4})\)\s*$")


@register
class BBFCProvider(RatingsProvider):
    system = "BBFC"
    display_name = "bbfc.co.uk"
    search_url = "https://www.bbfc.co.uk/search"

    def _search(self, query: str) -> list[dict]:
        match = _NEXT_DATA_RE.search(self._fetch(query))
        if not match:
            raise ValueError("bbfc.co.uk answered but the page had no embedded search data (site redesign?)")
        data = json.loads(match.group(1))
        try:
            results = data["props"]["pageProps"]["searchResults"]["results"]
        except (KeyError, TypeError) as exc:
            # Wrong shape = a redesign (ValueError = retry later), not a KeyError escaping.
            raise ValueError(
                "bbfc.co.uk answered but its search data was in an unexpected shape (site redesign?)"
            ) from exc
        candidates = []
        for result in results:
            # Releases + films only — the index also carries TV, news, education.
            if result.get("dataType") != "release" or result.get("type") != "Film":
                continue
            listed_title = result.get("title") or ""
            m = _TITLE_YEAR_RE.match(listed_title)
            candidates.append(
                {
                    "title": m.group("title") if m else listed_title,
                    "year": int(m.group("year")) if m else None,
                    "rating": (result.get("classification") or "").upper(),
                    "matched_title": listed_title,
                }
            )
        return candidates
