"""Trailer library service — TMDB discovery, yt-dlp downloads, verify/ratings/rename."""

import logging
import os
import shutil
import time
from collections.abc import Callable
from typing import Any

import dateutil.parser
import yt_dlp
from django.conf import settings
from pymediainfo import MediaInfo
from tmdbv3api import Discover, Movie, TMDb

from cinefin.api.exceptions import ConflictError, UnprocessableEntityError, ValidationError
from cinefin.api.models import Genre, Settings, Trailer, TrailerTag
from cinefin.api.models import Movie as MovieModel
from cinefin.api.utils import media_tree
from cinefin.api.utils.media_paths import to_usermedia_relative, usermedia_abs_path

from . import trailer_naming

logger = logging.getLogger("cinefin.trailers")

# Keep rating-provider lookups gentle: they hit the classification bodies' public websites.
RATING_LOOKUP_DELAY_SECONDS = 1.0

# Give up early if the provider keeps failing with nothing found (site down/redesigned); nothing is marked so the
# next run retries cleanly.
RATING_LOOKUP_ABORT_AFTER = 5


class TrailerCancelled(Exception):
    """Raised by an injected ``check_cancelled`` hook to stop an operation."""


class TrailerService:
    def __init__(
        self,
        log: Callable[[str, str], None] | None = None,
        progress: Callable[[int, int, str], None] | None = None,
        check_cancelled: Callable[[], None] | None = None,
    ):
        self._log = log
        self._progress = progress
        self._check_cancelled = check_cancelled

        self.sync_counts: dict[str, int] = {}
        self.tmdb = TMDb()
        self.tmdb_movie = Movie()

        db_cfg = Settings.get("trailers") or {}

        # Fixed MEDIA_ROOT subdir (not user configurable), held relative to MEDIA_ROOT; resolved to absolute at I/O.
        self.trailer_dir = to_usermedia_relative(media_tree.trailer_dir())
        self.tmdb.api_key = db_cfg.get("tmdb_api_key") or getattr(settings, "TMDB_API_KEY", "")
        self.config = {
            "trailer_directory": usermedia_abs_path(self.trailer_dir),
            "tmdb_api_key": self.tmdb.api_key,
            "rating_lookup_enabled": db_cfg.get("rating_lookup_enabled", True),
            "download_quality": db_cfg.get("download_quality", "1080"),
            "upcoming_months_ahead": db_cfg.get("upcoming_months_ahead", 6),
            "auto_fetch_for_library": True,
            "filename_template": db_cfg.get("filename_template") or trailer_naming.DEFAULT_FILENAME_TEMPLATE,
            "folder_template": db_cfg.get("folder_template") or trailer_naming.DEFAULT_FOLDER_TEMPLATE,
            "allowed_video_formats": ["mp4", "mkv", "mov"],
        }

        self.filename_template = self.config.get("filename_template", trailer_naming.DEFAULT_FILENAME_TEMPLATE)
        self.folder_template = self.config.get("folder_template", trailer_naming.DEFAULT_FOLDER_TEMPLATE)

    def log(self, level: str, message: str):
        if self._log is not None:
            self._log(level, message)
        else:
            getattr(logger, level.lower(), logger.info)(message)

    def update_progress(self, current: int, total: int, message: str = ""):
        if self._progress is not None:
            self._progress(current, total, message)

    def check_cancelled(self):
        if self._check_cancelled is not None:
            self._check_cancelled()

    def _meta_for(self, **kwargs) -> dict:
        return {
            "title": kwargs.get("title", ""),
            "year": kwargs.get("year", ""),
            "month": kwargs.get("month", ""),
            "tmdbid": kwargs.get("tmdbid", ""),
            "certification": kwargs.get("certification", ""),
            "director": kwargs.get("director", ""),
        }

    def _target_path(self, **meta) -> str:
        return trailer_naming.render_full_path(
            self.trailer_dir, self._meta_for(**meta), self.filename_template, self.folder_template
        )

    def test_connection(self) -> bool:
        try:
            if not self.tmdb.api_key:
                self.log("error", "No TMDB API key configured")
                return False

            self.tmdb_movie.details(550)  # Fight Club
            self.log("info", "Successfully connected to TMDB API")
            return True
        except Exception as e:
            self.log("error", f"TMDB API connection failed: {str(e)}")
            return False

    def run_operation(self, operation: str, params: dict | None = None) -> bool:
        params = params or {}
        if operation == "verify":
            return self.verify_existing_trailers()
        if operation in ("discover", "upcoming"):  # "upcoming" = legacy name
            return self.fetch_discover_trailers(
                year=params.get("year"),
                months_ahead=params.get("months_ahead"),
                year_from=params.get("year_from"),
                year_to=params.get("year_to"),
                limit=params.get("limit"),
                sort_by=params.get("sort_by"),
                genres=params.get("genres"),
                min_rating=params.get("min_rating"),
                certification=params.get("certification"),
            )
        if operation == "library":
            return self.fetch_library_trailers()
        if operation == "single":
            return self.fetch_single_trailer(
                params.get("tmdbid"),
                video_key=params.get("video_key"),
                replace=bool(params.get("replace")),
            )
        if operation == "ratings":
            return self.update_ratings(scope=params.get("scope", "all"))
        if operation == "rename":
            return self.rename_existing_trailers()
        raise ValueError(f"Unknown trailer operation: {operation}")

    def verify_existing_trailers(self) -> bool:
        """Verify existing trailer files and create database entries for orphaned files."""
        try:
            abs_trailer_dir = usermedia_abs_path(self.trailer_dir)
            if not os.path.exists(abs_trailer_dir):
                self.log("error", f"Trailer directory not found: {abs_trailer_dir}")
                return False

            self.update_progress(0, 100, "Scanning trailer directory...")
            exts = tuple(
                "." + e.lstrip(".").lower() for e in self.config.get("allowed_video_formats", ["mp4", "mkv", "mov"])
            )
            files = []
            for root, _dirs, names in os.walk(abs_trailer_dir):
                for n in names:
                    if n.lower().endswith(exts):
                        files.append(os.path.join(root, n))
            total_files = len(files)

            # Reconcile by STORED PATH (relative) and tmdb id — not by name.
            trailers = list(Trailer.objects.all())
            by_path = {t.file_path: t for t in trailers}
            by_tmdb = {t.tmdbid: t for t in trailers}
            self.log("info", f"Found {total_files} files and {len(trailers)} database entries")

            processed = created = verified = relinked = invalid = errored = 0

            for path in files:
                self.check_cancelled()
                processed += 1
                # Isolate each file so one bad file can't abort the whole verify.
                try:
                    self.update_progress(
                        processed, total_files, f"Verifying {processed}/{total_files}: {os.path.basename(path)}"
                    )
                    rel = to_usermedia_relative(path)

                    if rel in by_path:
                        verified += 1
                        continue

                    tmdbid = trailer_naming.recover_tmdbid(os.path.basename(path))
                    known = by_tmdb.get(tmdbid) if tmdbid else None

                    # Known trailer whose file moved/was renamed -> relink the DB row.
                    if known:
                        known.file_path = rel
                        known.save(update_fields=["file_path"])
                        by_path[rel] = known
                        relinked += 1
                        self.log("info", f"Relinked {known.title}: {os.path.basename(path)}")
                        continue

                    if not tmdbid:
                        self.log("warning", f"Cannot identify (no tmdb id in name): {os.path.basename(path)}")
                        invalid += 1
                        continue

                    try:
                        details = self.tmdb_movie.details(int(tmdbid))
                    except Exception as e:
                        self.log("warning", f"Could not fetch TMDB details for {os.path.basename(path)}: {e}")
                        invalid += 1
                        continue

                    release_parts = (details.get("release_date") or "").split("-")
                    year = int(release_parts[0]) if release_parts[0] else 0
                    # Parse the real release month: hardcoding month=1 broke {month} filename tokens on verify.
                    month = int(release_parts[1]) if len(release_parts) > 1 and release_parts[1] else 1
                    certificates = self._get_certificates(details)
                    trailer = Trailer.objects.create(
                        title=details.get("title", f"Unknown ({tmdbid})"),
                        year=year,
                        file_path=rel,
                        certificates=certificates,
                        content_rating=certificates.get(Settings.get_ratings_system(), ""),
                        tmdbid=int(tmdbid),
                        month=month,
                        duration=self._get_video_duration(path),
                        director=self._get_director(details),
                    )
                    self._add_genres_to_trailer(trailer, details.get("genres", []))
                    by_path[rel] = trailer
                    by_tmdb[int(tmdbid)] = trailer
                    created += 1
                    self.log("info", f"Imported orphan file: {trailer.title}")

                except TrailerCancelled:
                    raise
                except Exception as e:
                    errored += 1
                    self.log("error", f"Skipped {os.path.basename(path)}: {e}")
                    continue

            db_only = 0
            for t in trailers:
                if not os.path.exists(usermedia_abs_path(t.file_path)):
                    db_only += 1
                    self.log("warning", f"Database entry without file: {t.title} ({t.file_path})")

            self.sync_counts = {
                "added": created,
                "updated": relinked,
                "skipped": verified,
                "failed": invalid + errored,
            }
            self.update_progress(total_files, total_files, "Verification complete")
            self.log("info", "Verification complete:")
            self.log("info", f"  - Files processed: {processed}")
            self.log("info", f"  - Verified: {verified}")
            self.log("info", f"  - Relinked (moved/renamed): {relinked}")
            self.log("info", f"  - Orphan files imported: {created}")
            self.log("info", f"  - Unidentifiable: {invalid}")
            self.log("info", f"  - Errored (skipped): {errored}")
            self.log("info", f"  - DB entries without files: {db_only}")
            return True

        except TrailerCancelled:
            raise
        except Exception as e:
            self.log("error", f"Verification failed: {str(e)}")
            return False

    def fetch_discover_trailers(
        self,
        year: int = None,
        months_ahead: int = None,
        year_from: int = None,
        year_to: int = None,
        limit: int = None,
        sort_by: str = None,
        genres: list = None,
        min_rating: float = None,
        certification: str = None,
    ) -> bool:
        """Discover films on TMDB (date window, genre, rating, certification) and fetch their trailers."""
        try:
            self.log(
                "info",
                f"fetch_discover_trailers called with: year_from={year_from}, year_to={year_to}, limit={limit}, sort_by={sort_by}, genres={genres}, min_rating={min_rating}",
            )

            if not self.tmdb.api_key:
                self.log("error", "No TMDB API key configured")
                return False

            import datetime

            current_date = datetime.datetime.now()

            # If EITHER side is given, default the other (current/next year) to match the preview endpoint rather
            # than reverting to the upcoming-months window.
            if year_from is not None or year_to is not None:
                y_from = year_from if year_from is not None else current_date.year
                y_to = year_to if year_to is not None else current_date.year + 1
                start_date_str = f"{y_from}-01-01"
                end_date_str = f"{y_to}-12-31"
                self.log("info", f"Searching for movies from {start_date_str} to {end_date_str}")
            else:
                if year is None:
                    year = current_date.year
                if months_ahead is None:
                    months_ahead = self.config.get("upcoming_months_ahead", 6)

                end_date = current_date + datetime.timedelta(days=months_ahead * 30)
                start_date_str = current_date.strftime("%Y-%m-%d")
                end_date_str = end_date.strftime("%Y-%m-%d")
                self.log("info", f"Searching for movies from {start_date_str} to {end_date_str}")

            self.update_progress(0, 100, "Searching for movies...")

            discover = Discover()

            discover_params = {
                "primary_release_date.gte": start_date_str,
                "primary_release_date.lte": end_date_str,
                "region": "GB",
                "include_adult": False,
            }

            if sort_by:
                discover_params["sort_by"] = sort_by
            if genres:
                discover_params["with_genres"] = ",".join(str(g) for g in genres)
            if min_rating:
                discover_params["vote_average.gte"] = float(min_rating)
                discover_params["vote_count.gte"] = 10
            if certification:
                cert_country = "US" if Settings.get_ratings_system() == "MPAA" else "GB"
                discover_params["certification_country"] = cert_country
                discover_params["certification"] = certification

            self.log("info", f"Discover params: {discover_params}")

            try:
                results = discover.discover_movies(discover_params)
                all_movies = list(results) if results else []
            except Exception as e:
                self.log("warning", f"Error fetching movies: {e}")
                all_movies = []

            target_count = limit if limit else 100
            if target_count and len(all_movies) > target_count:
                all_movies = all_movies[:target_count]

            total_movies = len(all_movies)
            if total_movies == 0:
                self.log("info", "No matching movies found")
                self.update_progress(100, 100, "No movies to process")
                return True

            self.log("info", f"Found {total_movies} matching movies to check for trailers")

            downloaded = 0
            skipped = 0
            errors = 0

            for i, movie in enumerate(all_movies):
                self.check_cancelled()

                movie_title = movie.get("title", "Unknown")
                progress_msg = f"Processing {i + 1}/{total_movies}: {movie_title}"
                self.update_progress(i + 1, total_movies, progress_msg)

                try:
                    trailer, was_created = self._download_and_create_trailer(movie)
                    if trailer and was_created:
                        downloaded += 1
                        self.log("info", f"Downloaded and created trailer for: {movie_title}")
                    elif trailer and not was_created:
                        skipped += 1
                    else:
                        skipped += 1
                except Exception as e:
                    self.log("error", f"Failed to process {movie_title}: {e}")
                    errors += 1

            self.update_progress(total_movies, total_movies, "Fetch complete")
            self.log("info", "Upcoming trailers fetch complete:")
            self.log("info", f"  - Movies checked: {total_movies}")
            self.log("info", f"  - Trailers downloaded: {downloaded}")
            self.log("info", f"  - Skipped (already exist): {skipped}")
            self.log("info", f"  - Errors: {errors}")

            return True

        except TrailerCancelled:
            raise
        except Exception as e:
            self.log("error", f"Upcoming trailer fetch failed: {str(e)}")
            return False

    def fetch_single_trailer(self, tmdbid: int | None, video_key: str | None = None, replace: bool = False) -> bool:
        """Download the trailer for one TMDB title. `video_key` pins a YouTube video; `replace` re-downloads."""
        try:
            if not tmdbid:
                self.log("error", "No TMDB id provided")
                return False
            if not self.tmdb.api_key:
                self.log("error", "No TMDB API key configured")
                return False

            self.update_progress(0, 1, "Fetching movie details...")
            try:
                details = self.tmdb_movie.details(int(tmdbid))
            except Exception as e:
                self.log("error", f"Could not fetch TMDB details for id {tmdbid}: {e}")
                return False

            # Replacing vs adding is decided by what exists NOW, so counts stay honest when replace meets an empty slot.
            had_row = Trailer.objects.filter(tmdbid=int(tmdbid)).exists()

            title = details.get("title") or f"Unknown ({tmdbid})"
            self.update_progress(0, 1, f"Downloading trailer: {title}")
            trailer, downloaded = self._download_and_create_trailer(
                {"id": int(tmdbid), "title": title, "release_date": details.get("release_date", "")},
                video_key=video_key,
                replace=replace,
            )

            if trailer and downloaded and had_row:
                self.sync_counts = {"updated": 1}
                self.log("info", f"Replaced trailer for: {trailer.title}")
            elif trailer and downloaded:
                self.sync_counts = {"added": 1}
                self.log("info", f"Downloaded trailer for: {trailer.title}")
            elif trailer:
                self.sync_counts = {"skipped": 1}
                self.log("info", f"Trailer already in the library: {trailer.title}")
            else:
                # No counts: a single fetch that got nothing is a failed job. _download_and_create_trailer logged why.
                self.log("warning", f"No trailer could be downloaded for {title}")
                return False

            self.update_progress(1, 1, "Fetch complete")
            return True

        except TrailerCancelled:
            raise
        except Exception as e:
            self.log("error", f"Trailer fetch failed: {str(e)}")
            return False

    def fetch_library_trailers(self) -> bool:
        """Download trailers for existing movies that don't have them."""
        try:
            self.update_progress(0, 100, "Loading movie library...")
            movies = MovieModel.objects.all()
            total_movies = movies.count()

            if total_movies == 0:
                self.log("info", "No movies in library")
                self.update_progress(100, 100, "No movies to process")
                return True

            self.update_progress(5, 100, "Checking which movies already have trailers...")
            existing_tmdb_ids = set(Trailer.objects.values_list("tmdbid", flat=True))
            self.log("info", f"Found {len(existing_tmdb_ids)} existing trailers")
            self.log("info", f"Checking {total_movies} movies for missing trailers")

            downloaded = 0
            skipped = 0
            errors = 0

            missing = [movie for movie in movies if movie.tmdbid not in existing_tmdb_ids]

            total_missing = len(missing)
            self.log("info", f"Found {total_missing} movies without trailers")

            if total_missing == 0:
                self.update_progress(100, 100, "All movies have trailers")
                return True

            for i, movie in enumerate(missing):
                self.check_cancelled()

                progress_msg = f"Downloading {i + 1}/{total_missing}: {movie.title}"
                self.update_progress(i + 1, total_missing, progress_msg)

                try:
                    movie_data = {
                        "id": movie.tmdbid,
                        "title": movie.title,
                        "release_date": movie.date_added.strftime("%Y-%m-%d") if movie.date_added else "2024-01-01",
                    }

                    trailer, was_created = self._download_and_create_trailer(movie_data)
                    if trailer and was_created:
                        downloaded += 1
                        self.log("info", f"Downloaded and created trailer for: {movie.title}")
                    elif trailer and not was_created:
                        skipped += 1
                    else:
                        skipped += 1

                except Exception as e:
                    self.log("warning", f"Could not download trailer for {movie.title}: {e}")
                    errors += 1

            self.update_progress(total_missing, total_missing, "Library sync complete")
            self.log("info", "Library trailer fetch complete:")
            self.log("info", f"  - Movies in library: {total_movies}")
            self.log("info", f"  - Movies missing trailers: {total_missing}")
            self.log("info", f"  - Trailers downloaded: {downloaded}")
            self.log("info", f"  - Skipped: {skipped}")
            self.log("info", f"  - Errors: {errors}")

            return True

        except TrailerCancelled:
            raise
        except Exception as e:
            self.log("error", f"Library trailer fetch failed: {str(e)}")
            return False

    def update_ratings(self, scope: str = "all") -> bool:
        """Fill/repair certificates via the active system's rating provider. `scope` is movies/trailers/all."""
        from cinefin.api.ratings import get_provider
        from cinefin.api.ratings.service import canonical_certificate

        try:
            if not self.config.get("rating_lookup_enabled", True):
                self.log("info", "Certificate rating lookups are disabled")
                self.update_progress(100, 100, "Rating lookups disabled")
                return True

            if scope not in ("movies", "trailers", "all"):
                self.log("error", f"Unknown ratings scope: {scope}")
                return False

            system = Settings.get_ratings_system()
            provider = get_provider(system)
            if provider is None:
                self.log("error", f"No rating provider is registered for the {system} system")
                return False

            self.update_progress(0, 100, "Loading items without a valid certificate...")

            valid = Settings.get_valid_ratings(system)

            def needs_lookup(item) -> bool:
                cert = item.certificate_for(system)
                if cert in valid:
                    return False
                # Missing or wrong-scheme: only a confident "no match" stops the re-query (a later sync may clobber).
                return (item.rating_lookups or {}).get(system) != "unmatched"

            scope_label = {"movies": "movies", "trailers": "trailers", "all": "movies and trailers"}[scope]
            pending = []
            if scope in ("trailers", "all"):
                pending += [t for t in Trailer.objects.all() if needs_lookup(t)]
            if scope in ("movies", "all"):
                pending += [m for m in MovieModel.objects.all() if needs_lookup(m)]

            total = len(pending)
            if total == 0:
                self.log("info", f"All {scope_label} have a valid {system} certificate or have been checked")
                self.update_progress(100, 100, "No items need rating updates")
                return True

            self.log("info", f"Found {total} {scope_label} missing a valid {system} certificate")
            self.log("info", f"Looking up {system} certificates via {provider.display_name}")

            updated = 0
            not_found = 0
            errors = 0
            queried = False
            consecutive_errors = 0

            for i, item in enumerate(pending):
                self.check_cancelled()

                kind = "trailer" if isinstance(item, Trailer) else "movie"
                self.update_progress(i + 1, total, f"Checking {i + 1}/{total}: {item.title}")

                # Case-only mismatches don't need the network.
                canonical = canonical_certificate(item.certificate_for(system), system)
                if canonical:
                    item.set_certificate(system, canonical, active_system=system)
                    item.save()
                    updated += 1
                    consecutive_errors = 0
                    self.log("info", f"Normalised {kind} {item.title}: {system} {canonical}")
                    continue

                # Be polite to the classification body's website: one spaced-out request per title.
                if queried:
                    time.sleep(RATING_LOOKUP_DELAY_SECONDS)
                queried = True

                try:
                    result = provider.lookup(item.title, year=item.year or None)
                    consecutive_errors = 0
                    if result:
                        item.set_certificate(system, result.rating, active_system=system)
                        item.mark_rating_lookup(system, "matched")
                        item.save()
                        updated += 1
                        self.log("info", f"Updated {kind} {item.title}: {system} {result.rating}")
                    else:
                        item.mark_rating_lookup(system, "unmatched")
                        item.save()
                        not_found += 1
                        self.log("debug", f"No {system} match found for {kind}: {item.title}")

                except Exception as e:
                    # Not marked: a transient failure should be retried next run, unlike a confident "no match".
                    self.log("warning", f"{system} lookup failed for {item.title}: {e}")
                    errors += 1
                    consecutive_errors += 1
                    # Site down or redesigned: stop before hammering the rest.
                    if consecutive_errors >= RATING_LOOKUP_ABORT_AFTER and updated == 0:
                        self.log(
                            "error",
                            f"{provider.display_name} looks unavailable — stopped after "
                            f"{consecutive_errors} consecutive failures. Nothing was marked; "
                            "the next run will retry.",
                        )
                        return False

            self.update_progress(total, total, "Rating update complete")
            self.log("info", "Certificate rating update complete:")
            self.log("info", f"  - Items checked: {total}")
            self.log("info", f"  - Certificates updated: {updated}")
            self.log("info", f"  - No match found: {not_found}")
            self.log("info", f"  - Errors: {errors}")

            return True

        except TrailerCancelled:
            raise
        except Exception as e:
            self.log("error", f"Rating update failed: {str(e)}")
            return False

    def iter_rename_targets(self):
        """Yield ``(trailer, old, new)`` for every DB trailer; used by the rename op and its dry-run preview."""
        for t in Trailer.objects.all():
            old = t.file_path or ""  # canonical MEDIA_ROOT-relative
            ext = os.path.splitext(old)[1].lstrip(".") or trailer_naming.DEFAULT_EXTENSION
            meta = self._meta_for(
                title=t.title,
                year=t.year,
                month=t.month,
                tmdbid=t.tmdbid,
                certification=t.content_rating,
                director=t.director,
            )
            new = trailer_naming.render_full_path(
                self.trailer_dir, meta, self.filename_template, self.folder_template, ext=ext
            )
            yield t, old, new

    def rename_existing_trailers(self) -> bool:
        """Rename existing trailer files to match the current naming template."""
        try:
            targets = list(self.iter_rename_targets())
            total = len(targets)
            renamed = skipped = missing = errors = 0

            for i, (t, old, new) in enumerate(targets):
                self.check_cancelled()
                self.update_progress(i + 1, total, f"Renaming {i + 1}/{total}: {t.title}")

                if old == new:
                    skipped += 1
                    continue
                abs_old = usermedia_abs_path(old)
                abs_new = usermedia_abs_path(new)
                if not old or not os.path.exists(abs_old):
                    missing += 1
                    self.log("warning", f"File missing for {t.title}: {old or '(no path)'}")
                    continue
                if os.path.exists(abs_new):
                    skipped += 1
                    self.log("warning", f"Target already exists, skipping: {os.path.relpath(new, self.trailer_dir)}")
                    continue
                try:
                    os.makedirs(os.path.dirname(abs_new), exist_ok=True)
                    # shutil.move (not os.rename) so it works across filesystems.
                    shutil.move(abs_old, abs_new)
                    t.file_path = new
                    t.save(update_fields=["file_path"])
                    renamed += 1
                    self.log("info", f"Renamed: {os.path.basename(old)} -> {os.path.relpath(new, self.trailer_dir)}")
                except Exception as e:  # noqa: BLE001
                    errors += 1
                    self.log("error", f"Failed to rename {t.title}: {e}")

            self.sync_counts = {"updated": renamed, "skipped": skipped, "failed": errors}
            self.update_progress(total, total, "Rename complete")
            self.log(
                "info", f"Rename complete: {renamed} renamed, {skipped} unchanged, {missing} missing, {errors} errors"
            )
            return errors == 0

        except TrailerCancelled:
            raise
        except Exception as e:  # noqa: BLE001
            self.log("error", f"Rename failed: {e}")
            return False

    def import_uploaded_trailer(
        self,
        file,
        *,
        title: str | None = None,
        tmdbid: int | None = None,
        tag_names: list[str] | None = None,
    ) -> Trailer:
        """
        Store an uploaded trailer file and create its Trailer row.

        With `tmdbid`, metadata is fetched from TMDB and the file lands at the naming-template path (`associated_movie`
        auto-set for a matching library movie); without it, `title` is required and the file keeps a sanitised name.
        Raises the structured API exceptions directly.
        """
        from cinefin.api.ninja_views.media.utils import get_media_duration, sanitize_filename

        title = (title or "").strip()
        if not tmdbid and not title:
            raise ValidationError("A title is required for unlinked uploads", error_code="TITLE_REQUIRED")

        # Validate against the allowed formats verify scans for — anything else would never reconcile.
        allowed = {e.lstrip(".").lower() for e in self.config.get("allowed_video_formats", ["mp4", "mkv", "mov"])}
        ext = os.path.splitext(file.name or "")[1].lstrip(".").lower()
        if ext not in allowed:
            raise ValidationError(
                f"Invalid file type '.{ext}'. Allowed: {', '.join(sorted('.' + e for e in allowed))}",
                error_code="INVALID_FILE_EXTENSION",
            )

        max_size_mb = getattr(settings, "MAX_MEDIA_UPLOAD_SIZE_MB", 500)
        if file.size and file.size > max_size_mb * 1024 * 1024:
            raise ValidationError(f"File too large. Maximum size: {max_size_mb}MB", error_code="FILE_TOO_LARGE")

        year = 0
        month = 1
        certificates: dict[str, str] = {}
        director = ""
        genres: list[dict] = []

        if tmdbid:
            existing = Trailer.objects.filter(tmdbid=tmdbid).first()
            if existing:
                raise ConflictError(
                    f"A trailer for this film already exists: {existing.title}",
                    error_code="TRAILER_EXISTS",
                )
            try:
                details = self.tmdb_movie.details(int(tmdbid), append_to_response="credits,release_dates")
            except Exception as e:
                raise UnprocessableEntityError(
                    f"Could not fetch TMDB metadata for id {tmdbid}: {e}", error_code="TMDB_FETCH_FAILED"
                ) from e
            title = (details.get("title") or title or f"Unknown ({tmdbid})").strip()
            release_date = details.get("release_date") or ""
            try:
                parsed = dateutil.parser.isoparse(release_date)
                year, month = parsed.year, parsed.month
            except (ValueError, TypeError):
                pass
            certificates = self._get_certificates(details)
            director = self._get_director(details)
            genres = details.get("genres", [])

        content_rating = certificates.get(Settings.get_ratings_system(), "")
        if tmdbid:
            # Same naming template Discover uses, so verify/rename recognise it.
            output_path = self._target_path(
                title=title, year=year, month=month, tmdbid=tmdbid, certification=content_rating, director=director
            )
            base, path_ext = os.path.splitext(output_path)
            if path_ext.lstrip(".").lower() != ext:
                output_path = f"{base}.{ext}"
        else:
            safe = sanitize_filename(f"{title}.{ext}")
            output_path = os.path.join(self.trailer_dir, safe)

        # Collision-safe: never overwrite an existing file.
        base, path_ext = os.path.splitext(output_path)
        counter = 1
        while os.path.exists(usermedia_abs_path(output_path)):
            output_path = f"{base} ({counter}){path_ext}"
            counter += 1
        abs_output = usermedia_abs_path(output_path)

        os.makedirs(os.path.dirname(abs_output), exist_ok=True)
        try:
            with open(abs_output, "wb") as dest:
                for chunk in file.chunks():
                    dest.write(chunk)
        except OSError as e:
            if os.path.exists(abs_output):
                os.unlink(abs_output)
            raise UnprocessableEntityError(f"Could not store the file: {e}", error_code="UPLOAD_STORE_FAILED") from e

        try:
            duration = int(get_media_duration(abs_output) or 0)

            trailer = Trailer.objects.create(
                title=title,
                year=year,
                month=month,
                file_path=output_path,
                certificates=certificates,
                content_rating=content_rating,
                tmdbid=int(tmdbid) if tmdbid else 0,
                duration=duration,
                director=director,
                associated_movie=MovieModel.objects.filter(tmdbid=tmdbid).first() if tmdbid else None,
            )
            self._add_genres_to_trailer(trailer, genres)

            for name in tag_names or []:
                name = name.strip()
                if not name:
                    continue
                tag = TrailerTag.objects.filter(name__iexact=name).first()
                if tag is None:
                    tag = TrailerTag.objects.create(name=name)
                trailer.trailer_tags.add(tag)
        except Exception:
            # Don't leave an orphaned file behind if the DB row failed.
            if os.path.exists(abs_output):
                os.unlink(abs_output)
            raise

        self.log("info", f"Imported uploaded trailer: {trailer.title} ({os.path.basename(output_path)})")
        return trailer

    def get_statistics(self) -> dict[str, Any]:
        trailers = Trailer.objects.all()

        years = {}
        for trailer in trailers:
            year = trailer.year
            years[year] = years.get(year, 0) + 1

        ratings = {}
        for trailer in trailers:
            rating = trailer.content_rating or "Unknown"
            ratings[rating] = ratings.get(rating, 0) + 1

        return {
            "total_trailers": trailers.count(),
            "by_year": years,
            "by_rating": ratings,
            "directory": usermedia_abs_path(self.trailer_dir),
            "api_key_configured": bool(self.tmdb.api_key),
            "configuration": {
                "trailer_directory": self.config.get("trailer_directory"),
                "download_quality": self.config.get("download_quality"),
                "rating_lookup_enabled": self.config.get("rating_lookup_enabled"),
                "upcoming_months_ahead": self.config.get("upcoming_months_ahead"),
                "filename_template": self.config.get("filename_template"),
            },
        }

    def _get_video_duration(self, file_path: str) -> int:
        try:
            media_info = MediaInfo.parse(file_path)
            for track in media_info.tracks:
                if track.track_type == "Video":
                    return int(float(track.duration) / 1000) if track.duration else 0
        except Exception as e:
            self.log("warning", f"Could not get duration for {file_path}: {e}")
        return 0

    def _ytdlp_fetch(self, video_key: str, dest_path: str) -> None:
        # YouTube serves mostly separate video+audio streams, so a bare "best" often fails; prefer merged
        # bestvideo+bestaudio, capped to download_quality. Merging needs ffmpeg.
        quality = str(self.config.get("download_quality") or "1080")
        if quality == "best":
            fmt = "bestvideo+bestaudio/best"
        else:
            h = quality if quality.isdigit() else "1080"
            fmt = f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/bestvideo+bestaudio/best"
        ytdl_opts = {
            "outtmpl": dest_path,
            "format": fmt,
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ytdl_opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_key}"])

    @staticmethod
    def _short_error(exc: Exception) -> str:
        """A one-line reason from a noisy exception (yt-dlp errors span lines with an "ERROR: " prefix)."""
        text = str(exc).strip()
        first = text.splitlines()[0] if text else exc.__class__.__name__
        first = first.removeprefix("ERROR: ").strip()
        return f"{first[:150]}…" if len(first) > 151 else first

    # One details call carries every country, so both systems' certificates are captured in a single pass.
    _CERT_COUNTRIES = {"BBFC": "GB", "MPAA": "US"}

    def _get_certificates(self, details: dict) -> dict[str, str]:
        """Extract per-system certificates from TMDB details, e.g. {"BBFC": "15", "MPAA": "R"}."""
        certificates: dict[str, str] = {}
        releases = (details.get("release_dates") or {}).get("results", [])
        # tmdbv3api wraps payloads in AsObj (NOT a dict subclass), so isinstance(r, dict) silently drops every
        # entry and no trailer ever gets a certificate. Duck-type on .get instead.
        by_country = {r.get("iso_3166_1"): r for r in releases if hasattr(r, "get")}
        for system, country in self._CERT_COUNTRIES.items():
            entries = (by_country.get(country) or {}).get("release_dates") or []
            for entry in entries:
                cert = (entry.get("certification") or "").strip()
                if cert:
                    certificates[system] = cert
                    break
        return certificates

    def _get_director(self, details: dict) -> str:
        try:
            crew = details.get("credits", {}).get("crew", [])
            for person in crew:
                if person.get("job") == "Director":
                    return person.get("name", "")
        except Exception:
            pass
        return ""

    def _add_genres_to_trailer(self, trailer: Trailer, genres: list[dict]):
        for genre_data in genres:
            genre_name = genre_data.get("name")
            if genre_name:
                genre, _ = Genre.objects.get_or_create(name=genre_name)
                trailer.genres.add(genre)

    def _download_and_create_trailer(
        self,
        movie_data: dict,
        cinema_month: int | None = None,
        video_key: str | None = None,
        replace: bool = False,
    ) -> tuple[Trailer | None, bool]:
        """Download a trailer and create its DB row. Returns (trailer, downloaded)."""
        try:
            tmdbid = movie_data["id"]
            title = movie_data["title"]
            release_date = movie_data.get("release_date", "")

            existing_trailer = Trailer.objects.filter(tmdbid=tmdbid).first()
            if existing_trailer and not replace:
                self.log("debug", f"Trailer already in database: {title}")
                return (existing_trailer, False)

            self.log("debug", f"Fetching TMDB details for: {title}")
            details = self.tmdb_movie.details(int(tmdbid), append_to_response="videos,credits,release_dates")

            if video_key:
                trailer_video = {"key": video_key}
            else:
                videos = details.get("videos", {}).get("results", [])

                # Pick the first YouTube trailer; the resolution is enforced at
                # download time by download_quality, not by TMDB's size label.
                trailer_video = next(
                    (v for v in videos if v.get("type") == "Trailer" and v.get("site") == "YouTube"),
                    None,
                )

            if not trailer_video:
                self.log("warning", f"No suitable trailer found for {title}")
                return (None, False)

            try:
                cinema_date = dateutil.parser.isoparse(release_date)
                year = cinema_date.year
                month = cinema_month or cinema_date.month
            except Exception:
                import datetime

                now = datetime.datetime.now()
                year = now.year
                month = cinema_month or now.month

            certificates = self._get_certificates(details)
            content_rating = certificates.get(Settings.get_ratings_system(), "")
            director = self._get_director(details)
            title_full = details.get("title", title)

            output_path = self._target_path(
                title=title_full, year=year, month=month, tmdbid=tmdbid, certification=content_rating, director=director
            )
            rel = os.path.relpath(output_path, self.trailer_dir)
            abs_output = usermedia_abs_path(output_path)
            os.makedirs(os.path.dirname(abs_output), exist_ok=True)

            if replace and existing_trailer:
                # Safe replace: fetch alongside the old file and only swap once it's on disk, so a failed download
                # leaves the original untouched (old code deleted first and could strand a film with no trailer).
                tmp_dir, tmp_name = os.path.split(abs_output)
                tmp_path = os.path.join(tmp_dir, f".incoming-{tmp_name}")
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                try:
                    self.log("info", f"Downloading replacement trailer for {title}")
                    self._ytdlp_fetch(trailer_video["key"], tmp_path)
                except Exception as e:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                    self.log(
                        "error", f"Replacement download failed — kept the existing trailer ({self._short_error(e)})"
                    )
                    return (None, False)

                if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                    self.log("error", "Replacement download produced no file — kept the existing trailer")
                    return (None, False)

                # Replacement is on disk: drop the old file (may sit elsewhere if metadata changed) and move in.
                duration = self._get_video_duration(tmp_path)
                old_path = existing_trailer.file_path
                if old_path and old_path != output_path:
                    abs_old = usermedia_abs_path(old_path)
                    if os.path.exists(abs_old):
                        os.remove(abs_old)
                os.replace(tmp_path, abs_output)
                # Row keeps its identity (tags, movie link) — only the file and derived fields change.
                existing_trailer.file_path = output_path
                existing_trailer.duration = duration
                existing_trailer.save(update_fields=["file_path", "duration"])
                self.log("info", f"Replaced trailer video for: {title_full}")
                return (existing_trailer, True)

            # Fresh download: reuse a file already at the target path (a prior partial), else fetch.
            if os.path.exists(abs_output):
                self.log("info", f"Trailer file already exists: {rel}")
                duration = self._get_video_duration(abs_output)
            else:
                self.log("info", f"Downloading trailer for {title}")
                self._ytdlp_fetch(trailer_video["key"], abs_output)
                self.log("info", f"Downloaded trailer: {rel}")
                duration = self._get_video_duration(abs_output)

            trailer = Trailer.objects.create(
                title=title_full,
                year=year,
                file_path=output_path,
                certificates=certificates,
                content_rating=content_rating,
                tmdbid=int(tmdbid),
                month=month,
                duration=duration,
                director=director,
            )

            self._add_genres_to_trailer(trailer, details.get("genres", []))

            self.log("info", f"Created database entry for: {title}")
            return (trailer, True)

        except Exception as e:
            self.log("error", f"Failed to download/create trailer for {movie_data.get('title', 'unknown')}: {e}")
            return (None, False)
