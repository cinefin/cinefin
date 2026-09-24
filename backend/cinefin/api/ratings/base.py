from dataclasses import dataclass, field


@dataclass
class RatingResult:
    system: str
    rating: str
    matched_title: str = ""
    year: int | None = None
    extra: dict = field(default_factory=dict)


class RatingsProvider:
    #: Must match Settings.VALID_RATINGS_SYSTEMS.
    system: str = ""
    display_name: str = ""

    def lookup(self, title: str, year: int | None = None) -> RatingResult | None:
        # None = checked, no confident match (title won't be re-queried); raise
        # on network/parse error so the caller retries next run.
        raise NotImplementedError

    def check(self) -> dict:
        # Returns {"ok": bool, "message": str}. Must not raise.
        raise NotImplementedError
