import re
import unicodedata

# Classification years can trail the release year (re-ratings, festival vs
# general release), so a match within this window still counts.
YEAR_TOLERANCE = 1


def normalize_title(title: str) -> str:
    title = unicodedata.normalize("NFKD", title)
    title = "".join(c for c in title if not unicodedata.combining(c))
    title = title.lower()
    title = re.sub(r"&", " and ", title)
    title = re.sub(r"[^a-z0-9]+", " ", title)
    return " ".join(title.split())


def pick_best(candidates: list[dict], title: str, year: int | None = None) -> dict | None:
    # Only exact normalised-title matches count — a fuzzy match risks stamping
    # the wrong film's certificate onto a feature, worse than no certificate.
    wanted = normalize_title(title)
    matches = [c for c in candidates if normalize_title(c.get("title", "")) == wanted]
    if not matches:
        return None
    if year is None:
        return matches[0]

    def year_distance(candidate: dict) -> int:
        c_year = candidate.get("year")
        return abs(c_year - year) if c_year else YEAR_TOLERANCE + 1

    best = min(matches, key=year_distance)
    # A wildly different year is a different film (remakes share titles).
    if best.get("year") and year_distance(best) > YEAR_TOLERANCE:
        return None
    return best
