import logging
from dataclasses import dataclass

import requests

from .matching import pick_best

logger = logging.getLogger(__name__)

TIMEOUT = 15
USER_AGENT = "Cinefin (home cinema; +https://github.com/cinefin/cinefin)"


@dataclass
class RatingResult:
    system: str
    rating: str
    matched_title: str = ""
    year: int | None = None


class RatingsProvider:
    #: Must match Settings.VALID_RATINGS_SYSTEMS.
    system: str = ""
    display_name: str = ""
    search_url: str = ""
    query_param: str = "q"

    def _fetch(self, query: str) -> str:
        response = requests.get(
            self.search_url, params={self.query_param: query}, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
        )
        response.raise_for_status()
        return response.text

    def _search(self, query: str) -> list[dict]:
        """Candidates ``{title, year, rating, matched_title?}``; ValueError when the page is unrecognisable."""
        raise NotImplementedError

    def lookup(self, title: str, year: int | None = None) -> RatingResult | None:
        """None = checked, no confident match (not re-queried); raises on network/parse error (retried next run)."""
        from cinefin.api.models import Settings

        best = pick_best(self._search(title), title, year)
        if not best:
            return None
        if best["rating"] not in Settings.get_valid_ratings(self.system):
            logger.warning("%s returned unknown rating %r for %r", self.display_name, best["rating"], title)
            return None
        return RatingResult(
            system=self.system,
            rating=best["rating"],
            matched_title=best.get("matched_title", best["title"]),
            year=best["year"],
        )
