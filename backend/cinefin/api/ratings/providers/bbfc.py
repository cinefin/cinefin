"""BBFC certificate lookups against bbfc.co.uk.

Parses the search page's embedded `__NEXT_DATA__` JSON — stable across deploys,
unlike the /_next/data/<buildId>/ routes whose buildId churns per release.
Throttled by the caller; this reads a third party's public website.
"""

import json
import logging
import re

import requests

from cinefin.api.models import Settings

from ..base import RatingResult, RatingsProvider
from ..matching import pick_best
from ..registry import register

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.bbfc.co.uk/search"
TIMEOUT = 15
USER_AGENT = "Cinefin (home cinema; +https://github.com/cinefin-dev/cinefin)"

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_TITLE_YEAR_RE = re.compile(r"^(?P<title>.*?)\s*\((?P<year>\d{4})\)\s*$")


@register
class BBFCProvider(RatingsProvider):
    system = "BBFC"
    display_name = "bbfc.co.uk"

    def lookup(self, title: str, year: int | None = None) -> RatingResult | None:
        results = self._search(title)
        candidates = []
        for result in results:
            # Releases + films only — the index also carries TV, news, education.
            if result.get("dataType") != "release" or result.get("type") != "Film":
                continue
            listed_title = result.get("title") or ""
            match = _TITLE_YEAR_RE.match(listed_title)
            candidates.append(
                {
                    "title": match.group("title") if match else listed_title,
                    "year": int(match.group("year")) if match else None,
                    "classification": (result.get("classification") or "").upper(),
                    "listed_title": listed_title,
                }
            )

        best = pick_best(candidates, title, year)
        if not best:
            return None
        rating = best["classification"]
        if rating not in Settings.get_valid_ratings("BBFC"):
            logger.warning("BBFC returned unknown classification %r for %r", rating, title)
            return None
        return RatingResult(system="BBFC", rating=rating, matched_title=best["listed_title"], year=best["year"])

    def check(self) -> dict:
        try:
            self._search("test")
        except requests.exceptions.Timeout:
            return {"ok": False, "message": "bbfc.co.uk did not respond — try again later"}
        except requests.exceptions.RequestException:
            return {"ok": False, "message": "Could not reach bbfc.co.uk — check your network connection"}
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}
        return {"ok": True, "message": "bbfc.co.uk is reachable"}

    @staticmethod
    def _search(query: str) -> list[dict]:
        response = requests.get(SEARCH_URL, params={"q": query}, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        match = _NEXT_DATA_RE.search(response.text)
        if not match:
            raise ValueError("bbfc.co.uk answered but the page had no embedded search data (site redesign?)")
        data = json.loads(match.group(1))
        try:
            return data["props"]["pageProps"]["searchResults"]["results"]
        except (KeyError, TypeError) as exc:
            # Data present but wrong shape — treat as a redesign (ValueError =
            # retry-later), not a KeyError escaping.
            raise ValueError(
                "bbfc.co.uk answered but its search data was in an unexpected shape (site redesign?)"
            ) from exc
