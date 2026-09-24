"""MPAA certificate lookups against filmratings.com (CARA).

Regex-parses the server-rendered search-results cards (rating = icon alt text).
The admin-ajax backend only serves infinite-scroll continuation pages, so the
plain page fetch is the entry point. Throttled by the caller.
"""

import logging
import re

import requests

from cinefin.api.models import Settings

from ..base import RatingResult, RatingsProvider
from ..matching import pick_best
from ..registry import register

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.filmratings.com/search-results/"
TIMEOUT = 15
USER_AGENT = "Cinefin (home cinema; +https://github.com/cinefin/cinefin)"

_ITEM_RE = re.compile(r'<div class="item[^"]*">(.*?)<!--end-item-->', re.S)
_TITLE_RE = re.compile(r'<div class="item-title">(.*?)</div>', re.S)
_RATING_RE = re.compile(r'<div class="image-rating">.*?alt="([^"]*)"', re.S)
_YEAR_RATED_RE = re.compile(r'Year Rated:\s*</span>\s*<span class="text">\s*(\d{4})', re.S)
_REASON_RE = re.compile(r'Reason:\s*</span>\s*<span class="text">(.*?)</span>', re.S)


def _text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


@register
class MPAAProvider(RatingsProvider):
    system = "MPAA"
    display_name = "filmratings.com"

    def lookup(self, title: str, year: int | None = None) -> RatingResult | None:
        candidates = self._search(title)
        best = pick_best(candidates, title, year)
        if not best:
            return None
        rating = best["rating"]
        if rating not in Settings.get_valid_ratings("MPAA"):
            logger.warning("filmratings.com returned unknown rating %r for %r", rating, title)
            return None
        return RatingResult(
            system="MPAA",
            rating=rating,
            matched_title=best["title"],
            year=best["year"],
            extra={"reason": best["reason"]},
        )

    def check(self) -> dict:
        # Run the real parser so a redesign that breaks lookup() also fails the
        # health check, rather than passing on a shallow string match.
        try:
            self._search("test")
        except requests.exceptions.Timeout:
            return {"ok": False, "message": "filmratings.com did not respond — try again later"}
        except requests.exceptions.RequestException:
            return {"ok": False, "message": "Could not reach filmratings.com — check your network connection"}
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}
        return {"ok": True, "message": "filmratings.com is reachable"}

    @staticmethod
    def _search(query: str) -> list[dict]:
        # Missing results container = unknown page → raise ValueError (retry
        # later) instead of reading a broken scrape as "no rating". Container
        # present but no cards is a genuine empty result → [].
        response = requests.get(
            SEARCH_URL, params={"search": query}, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
        )
        response.raise_for_status()
        if "section-movies" not in response.text:
            raise ValueError("filmratings.com answered but the results page looks unfamiliar (site redesign?)")
        candidates = []
        for chunk in _ITEM_RE.findall(response.text):
            title_m = _TITLE_RE.search(chunk)
            rating_m = _RATING_RE.search(chunk)
            if not title_m or not rating_m:
                continue
            year_m = _YEAR_RATED_RE.search(chunk)
            reason_m = _REASON_RE.search(chunk)
            candidates.append(
                {
                    "title": _text(title_m.group(1)),
                    "rating": _text(rating_m.group(1)).upper(),
                    "year": int(year_m.group(1)) if year_m else None,
                    "reason": _text(reason_m.group(1)) if reason_m else "",
                }
            )
        return candidates
