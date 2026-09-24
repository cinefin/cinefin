from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from cinefin.api.utils.urls import cinefin_base_url

from .settings import Settings

FIRST_MOVIE_YEAR = 1888


class CertificateStoreMixin(models.Model):
    """Per-system certificate storage; CERT_FIELD is a denormalised scalar copy for the active display system."""

    certificates = models.JSONField(default=dict, blank=True)
    rating_lookups = models.JSONField(default=dict, blank=True)

    CERT_FIELD: str = ""

    class Meta:
        abstract = True

    def certificate_for(self, system: str) -> str:
        return (self.certificates or {}).get(system, "")

    def set_certificate(self, system: str, value: str, active_system: str | None = None) -> None:
        certs = dict(self.certificates or {})
        certs[system] = value
        self.certificates = certs
        active = active_system or Settings.get_ratings_system()
        if system == active:
            setattr(self, self.CERT_FIELD, value)

    def mark_rating_lookup(self, system: str, outcome: str) -> None:
        lookups = dict(self.rating_lookups or {})
        lookups[system] = outcome
        self.rating_lookups = lookups


class Genre(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name


class VideoContent(models.Model):
    title = models.CharField(max_length=255)
    file_path = models.CharField(max_length=1000)
    duration = models.PositiveIntegerField(default=0, help_text="Duration in seconds")

    class Meta:
        abstract = True

    def __str__(self):
        return self.title


class Movie(CertificateStoreMixin, VideoContent):
    CERT_FIELD = "certification"

    director = models.CharField(max_length=255)
    year = models.PositiveIntegerField(validators=[MinValueValidator(FIRST_MOVIE_YEAR)])
    genres = models.ManyToManyField(Genre)
    description = models.TextField(blank=True)
    certification = models.CharField(max_length=10, blank=True)

    # Live poster handle (Plex thumb key / Jellyfin image tag), never stored bytes. See poster_service.
    poster_key = models.CharField(
        max_length=500, blank=True, default="", help_text="Media-server poster reference (art key / image tag)"
    )
    tmdbid = models.PositiveIntegerField(default=0)
    runtime = models.PositiveIntegerField(default=0)
    resolution = models.CharField(max_length=10, blank=True)
    file_size = models.PositiveBigIntegerField(default=0)
    date_added = models.DateTimeField(default=timezone.now)

    # Media-server-reported stream info; 0/blank = not reported. Bitrate in bits/sec.
    video_codec = models.CharField(max_length=50, blank=True)
    video_width = models.PositiveIntegerField(default=0)
    video_height = models.PositiveIntegerField(default=0)
    video_framerate = models.FloatField(default=0)
    video_bitrate = models.PositiveBigIntegerField(default=0)

    credits_marker = models.PositiveIntegerField(
        default=0, help_text="Time when credits start in seconds (0 = no marker)"
    )

    kiosk_display = models.BooleanField(default=False)

    sync_source = models.ForeignKey(
        "SyncSource", on_delete=models.SET_NULL, null=True, blank=True, related_name="movies"
    )

    jellyfin_item_id = models.CharField(max_length=64, blank=True, help_text="Jellyfin item ID for streaming")
    plex_rating_key = models.CharField(max_length=32, blank=True, default="", help_text="Plex ratingKey")
    remote_updated_at = models.DateTimeField(
        null=True, blank=True, help_text="Server-side updatedAt at last sync (incremental change detection)"
    )

    # Django-served fallback URL for a local file; provider URLs come from streaming_service.
    def get_stream_url(self):
        from cinefin.api.utils.stream_token import make_stream_token

        base_url = cinefin_base_url()
        token = make_stream_token("movie", self.id)
        return {"stream_url": f"{base_url}/stream/movie/{self.id}/?t={token}", "provider": "local"}

    def delete(self, *args, **kwargs):
        self.audio_tracks.all().delete()
        self.subtitle_tracks.all().delete()
        super().delete(*args, **kwargs)

    @property
    def thumbnail_url(self):
        if self.poster_key and self.sync_source_id:
            return f"/api/v2/movies/{self.id}/poster"
        return settings.STATIC_URL + "img/default-movie-poster.jpg"

    def __str__(self):
        return self.title + " (" + str(self.year) + ")"


class TrailerTag(models.Model):
    # Separate from the user-media Tag (bumpers): distinct vocabularies must not leak into each other's filters.
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Trailer(CertificateStoreMixin, VideoContent):
    CERT_FIELD = "content_rating"

    associated_movie = models.ForeignKey(Movie, on_delete=models.SET_NULL, null=True, blank=True)

    director = models.CharField(max_length=255)
    year = models.PositiveIntegerField(validators=[MinValueValidator(FIRST_MOVIE_YEAR)])
    genres = models.ManyToManyField(Genre)
    content_rating = models.CharField(max_length=10, blank=True)
    tmdbid = models.PositiveIntegerField(default=0)
    month = models.PositiveIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    trailer_tags = models.ManyToManyField(TrailerTag, blank=True, related_name="trailers")

    def get_stream_url(self):
        from cinefin.api.utils.stream_token import make_stream_token

        base_url = cinefin_base_url()
        token = make_stream_token("trailer", self.id)
        return {"stream_url": f"{base_url}/stream/trailer/{self.id}/?t={token}", "provider": "local"}

    def __str__(self):
        return self.title + " (" + str(self.year) + ")"


class AudioTrack(models.Model):
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="audio_tracks")
    language = models.CharField(max_length=100)
    codec = models.CharField(max_length=100)
    channels = models.PositiveIntegerField()
    index = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.language} - {self.codec} - {self.title}"


class SubtitleTrack(models.Model):
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="subtitle_tracks")
    language = models.CharField(max_length=100)
    forced = models.BooleanField(default=False)
    sdh = models.BooleanField(default=False)
    index = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.language} ({'Forced' if self.forced else 'SDH' if self.sdh else 'Regular'})"


class Tag(models.Model):
    name = models.CharField(max_length=100, unique=True)
    color = models.CharField(
        max_length=7, blank=True, default="", help_text="Optional badge colour as #RRGGBB (blank = neutral)"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


AUDIO_FORMATS = [
    ("dolby_digital", "Dolby Digital"),
    ("dolby_truehd", "Dolby TrueHD"),
    ("dolby_atmos", "Dolby Atmos"),
    ("dts", "DTS"),
    ("dts_hd", "DTS-HD"),
    ("dts_x", "DTS:X"),
]


class Bumper(VideoContent):
    tags = models.ManyToManyField(Tag)

    audio_format = models.CharField(
        max_length=20,
        blank=True,
        default="",
        choices=AUDIO_FORMATS,
        help_text="Audio format this intro announces, if any",
    )

    file_size = models.PositiveBigIntegerField(default=0, help_text="File size in bytes")
    mime_type = models.CharField(max_length=100, blank=True, help_text="MIME type of the file")
    upload_date = models.DateTimeField(null=True, blank=True, help_text="Date when file was uploaded")
    screenshot = models.CharField(max_length=500, blank=True, help_text="Path to screenshot image file")

    def get_stream_url(self):
        from cinefin.api.utils.stream_token import make_stream_token

        base_url = cinefin_base_url()
        token = make_stream_token("bumper", self.id)
        return {"stream_url": f"{base_url}/stream/bumper/{self.id}/?t={token}", "provider": "local"}

    @property
    def screenshot_url(self):
        if self.screenshot:
            return settings.MEDIA_URL + self.screenshot
        return None


class Certification(models.Model):
    file_path = models.CharField(max_length=1000)
    certification = models.CharField(max_length=10)
    # One generated card per system (BBFC and MPAA backgrounds differ).
    ratings_system = models.CharField(max_length=10, default="BBFC")
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="certifications")

    def get_stream_url(self):
        from cinefin.api.utils.stream_token import make_stream_token

        base_url = cinefin_base_url()
        token = make_stream_token("certification", self.id)
        return {"stream_url": f"{base_url}/stream/certification/{self.id}/?t={token}", "provider": "local"}

    def __str__(self):
        return self.movie.title + " - " + self.certification
