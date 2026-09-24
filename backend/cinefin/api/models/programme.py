import os

from django.core.validators import MinValueValidator
from django.db import models

from .automation import Command
from .media import Bumper, Certification, Genre, Movie, Tag, Trailer, TrailerTag


class ProgrammeTemplate(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    number_of_features = models.PositiveIntegerField(default=1, help_text="Number of movies in this template")
    trailer_count_per_feature = models.PositiveIntegerField(default=3, help_text="Trailers before each feature")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.number_of_features} feature{'s' if self.number_of_features != 1 else ''})"

    def save(self, *args, **kwargs):
        if self.is_default:
            ProgrammeTemplate.objects.filter(is_default=True).update(is_default=False)
        super().save(*args, **kwargs)


class ProgrammeTemplateItem(models.Model):
    template = models.ForeignKey(ProgrammeTemplate, on_delete=models.CASCADE, related_name="items")
    order = models.PositiveIntegerField()

    ITEM_TYPES = (
        ("command", "Command"),
        ("bumper", "User Media"),
        ("trailer", "Trailer"),
        ("feature", "Feature Film"),
        ("trailer_rule", "Trailer Rule"),
        ("certification", "Certification (auto)"),
        ("audio_bumper", "Audio Bumper"),
    )
    item_type = models.CharField(max_length=20, choices=ITEM_TYPES)

    command = models.ForeignKey(Command, on_delete=models.CASCADE, null=True, blank=True)
    bumper = models.ForeignKey(Bumper, on_delete=models.CASCADE, null=True, blank=True)
    trailer = models.ForeignKey(Trailer, on_delete=models.CASCADE, null=True, blank=True)
    # A tag set = random pick from this tag; else the specific bumper clip.
    tag = models.ForeignKey(
        Tag, on_delete=models.CASCADE, null=True, blank=True, help_text="For random user-media selection"
    )
    count = models.PositiveIntegerField(default=1, help_text="Number of random items to select (when a tag is set)")

    feature_number = models.PositiveIntegerField(null=True, blank=True, help_text="Which feature this item relates to")

    credits_command = models.ForeignKey(
        Command,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="template_item_credits",
        help_text="Command to execute when credits begin (for features)",
    )

    hold_black = models.BooleanField(
        default=False, help_text="Show a black screen for the command's duration while it runs"
    )

    bound_to_feature = models.PositiveIntegerField(
        null=True, blank=True, help_text="Feature number this trailer rule is bound to"
    )
    trailer_count = models.PositiveIntegerField(default=3, help_text="Number of trailers for trailer rule")
    match_genre = models.BooleanField(default=True)
    match_certification = models.BooleanField(default=True)
    match_year = models.BooleanField(default=False)
    year_delta = models.PositiveIntegerField(default=5, help_text="Years +/- to match for trailers")
    trailer_tag = models.ForeignKey(
        TrailerTag,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Only pick trailers carrying this tag (trailer rules)",
    )

    certification_feature = models.PositiveIntegerField(
        null=True, blank=True, help_text="Feature number this certification is for"
    )

    class Meta:
        ordering = ["order"]

    def __str__(self):
        if self.item_type == "feature" and self.feature_number:
            return f"{self.template.name} - Feature {self.feature_number}"
        elif self.item_type == "trailer_rule" and self.bound_to_feature:
            return f"{self.template.name} - {self.trailer_count} Trailers (Feature {self.bound_to_feature})"
        elif self.item_type == "certification" and self.certification_feature:
            return f"{self.template.name} - Certification (Feature {self.certification_feature})"
        return f"{self.template.name} - {self.get_item_type_display()}"


class Programme(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    template = models.ForeignKey(ProgrammeTemplate, on_delete=models.CASCADE, null=True, blank=True)

    ticket_design = models.ForeignKey(
        "TicketDesign",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="programmes",
        help_text="Ticket design for this programme's tickets (blank = the default design)",
    )

    title_template = models.ForeignKey(
        "ProgrammeTitleTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="programmes",
        help_text="Template for generating programme title card",
    )
    title_background_type = models.CharField(
        max_length=20,
        choices=[
            ("color", "Solid Color"),
            ("image", "Static Image"),
            ("video", "Video"),
        ],
        default="color",
        help_text="Type of background for title card",
    )
    title_background_color = models.CharField(
        max_length=7, default="#000000", help_text="Hex color code for solid color background (e.g. #000000)"
    )
    title_background_file = models.CharField(
        max_length=1000, blank=True, help_text="Path to background image or video file"
    )
    title_file = models.CharField(max_length=1000, blank=True, help_text="Path to the generated title card MP4 file")
    title_duration = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Duration of title card in seconds (optional, uses template default or video length)",
    )
    title_fade_in = models.FloatField(default=0.0, help_text="Fade in duration in seconds (0 = no fade)")
    title_fade_out = models.FloatField(default=0.0, help_text="Fade out duration in seconds (0 = no fade)")

    playlist_stale = models.BooleanField(
        default=False, help_text="Playlist needs regeneration due to block or streaming changes"
    )

    last_played_at = models.DateTimeField(
        null=True, blank=True, help_text="When playback of this programme last started"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def get_total_runtime_minutes(self):
        total_seconds = 0

        for block in self.blocks.all():
            content = block.content_object
            if block.content_type == "movie":
                if content is None:
                    continue
                movie_runtime = getattr(content, "runtime", 0) or 0
                total_seconds += movie_runtime * 60
            elif block.content_type == "bumper":
                bumper_duration = getattr(content, "duration", 0)
                total_seconds += bumper_duration or 0
            elif block.content_type == "certification":
                cert_duration = getattr(content, "duration", 5)
                total_seconds += cert_duration or 5
            elif block.trailer_rule:
                estimated_trailer_duration = block.trailer_rule.number_of_trailers * 150
                total_seconds += estimated_trailer_duration

        if hasattr(self, "playlist") and self.playlist:
            playlist_seconds = 0
            for item in self.playlist.items.all():
                content = item.content_object
                if content is None:
                    continue
                if item.content_type == "movie":
                    movie = getattr(content, "movie", None)
                    movie_runtime = getattr(movie, "runtime", 0) or 0
                    playlist_seconds += movie_runtime * 60
                elif item.content_type == "trailer":
                    trailer_duration = getattr(content, "duration", 0)
                    playlist_seconds += trailer_duration or 0
                elif item.content_type == "bumper":
                    bumper_duration = getattr(content, "duration", 0)
                    playlist_seconds += bumper_duration or 0
                elif item.content_type == "certification":
                    cert_duration = getattr(content, "duration", 5)
                    playlist_seconds += cert_duration or 5

            if self.playlist.items.count() > self.blocks.count():
                total_seconds = playlist_seconds

        total_minutes = (total_seconds + 59) // 60
        return total_minutes

    def get_runtime(self):
        return self.get_total_runtime_minutes()

    def get_formatted_runtime(self):
        total_minutes = self.get_total_runtime_minutes()

        if total_minutes >= 60:
            hours = total_minutes // 60
            minutes = total_minutes % 60
            if minutes > 0:
                return f"{hours} hour{'s' if hours != 1 else ''} {minutes} minute{'s' if minutes != 1 else ''}"
            else:
                return f"{hours} hour{'s' if hours != 1 else ''}"
        else:
            return f"{total_minutes} minute{'s' if total_minutes != 1 else ''}"

    def get_feature_movies(self):
        blocks = self.blocks.filter(content_type="movie").select_related("movie").order_by("order")
        return [block.movie for block in blocks if block.movie is not None]

    def has_title_configured(self):
        return self.title_template is not None

    def get_title_file_path(self):
        from cinefin.api.utils.media_paths import usermedia_abs_path

        if self.title_file and os.path.exists(usermedia_abs_path(self.title_file)):
            return self.title_file
        return None

    def get_title_stream_url(self):
        if not self.get_title_file_path():
            return None
        from cinefin.api.utils.stream_token import make_stream_token
        from cinefin.api.utils.urls import cinefin_base_url

        base_url = cinefin_base_url()
        token = make_stream_token("title", self.id)
        return f"{base_url}/stream/title/{self.id}/?t={token}"


class TrailerRule(models.Model):
    # Fallback trailer count for rules/blocks that don't carry their own.
    DEFAULT_COUNT = 3

    name = models.CharField(max_length=255)
    # Optional convenience seed/ranker only, not a hard filter; SET_NULL so
    # deleting the movie doesn't delete a rule that no longer depends on it.
    reference_movie = models.ForeignKey(
        "Movie", on_delete=models.SET_NULL, null=True, blank=True, related_name="trailer_rules"
    )
    # Genres are best-effort match-any (empty = no constraint); cert/year/tag are hard.
    genres = models.ManyToManyField(Genre, blank=True, related_name="+")
    # Never pick a trailer rated above this (severity order). Empty = no cap.
    certificate_ceiling = models.CharField(max_length=10, blank=True, default="")
    # Inclusive release-year window; either end may be open (None).
    year_from = models.IntegerField(null=True, blank=True)
    year_to = models.IntegerField(null=True, blank=True)
    number_of_trailers = models.PositiveIntegerField(default=1)
    trailer_tag = models.ForeignKey(
        TrailerTag,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Only pick trailers carrying this tag",
    )

    def __str__(self):
        return self.name


class ProgrammeBlock(models.Model):
    programme = models.ForeignKey(Programme, on_delete=models.CASCADE, related_name="blocks")
    order = models.PositiveIntegerField()

    CONTENT_TYPES = (
        ("movie", "Movie"),
        ("bumper", "User Media"),
        ("command", "Command"),
        ("trailer_rule", "Trailer Rule"),
        ("certification", "Certification"),
        ("trailer", "Trailer"),
        ("random_movie", "Random Movie"),
        ("audio_bumper", "Audio Bumper"),
    )
    content_type = models.CharField(max_length=20, choices=CONTENT_TYPES, blank=True)

    # Typed content links — at most one set, selected by content_type. SET_NULL
    # so the block survives deletion of its target (cached_title/year describe it).
    # "certification" blocks reference the Movie being certified (clip resolved at
    # playlist-gen); the certification FK only carries legacy direct-pointing rows.
    movie = models.ForeignKey(Movie, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    bumper = models.ForeignKey(Bumper, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    command = models.ForeignKey(Command, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    trailer = models.ForeignKey(Trailer, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    certification = models.ForeignKey(Certification, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    trailer_rule = models.ForeignKey(TrailerRule, on_delete=models.SET_NULL, null=True, blank=True)

    # A "bumper" block is random when random_tag is set (or random_count > 1);
    # otherwise it plays the specific bumper clip.
    random_tag = models.ForeignKey(Tag, on_delete=models.SET_NULL, null=True, blank=True)
    random_count = models.PositiveIntegerField(default=1, help_text="Number of random items to select")

    random_movie_genres = models.ManyToManyField(Genre, blank=True, related_name="random_movie_blocks")
    random_movie_certification = models.CharField(
        max_length=10, blank=True, help_text="Filter by certification (e.g., PG-13, R)"
    )
    random_movie_year_from = models.PositiveIntegerField(null=True, blank=True, help_text="Minimum release year")
    random_movie_year_to = models.PositiveIntegerField(null=True, blank=True, help_text="Maximum release year")
    random_movie_runtime_from = models.PositiveIntegerField(
        null=True, blank=True, help_text="Minimum runtime in minutes"
    )
    random_movie_runtime_to = models.PositiveIntegerField(null=True, blank=True, help_text="Maximum runtime in minutes")

    audio_track_index = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(0)])
    subtitle_track_index = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(0)])

    credits_command = models.ForeignKey(
        Command,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="programme_block_credits",
        help_text="Command to execute when credits begin",
    )

    # False = command fires as an instant cue between items (no playlist entry).
    hold_black = models.BooleanField(
        default=False, help_text="Show a black screen for the command's duration while it runs"
    )

    bound_to_block_order = models.PositiveIntegerField(
        null=True, blank=True, help_text="Block order this item is bound to (for random movie references)"
    )

    trailer_match_genres = models.BooleanField(default=True, help_text="Match genres with reference movie")
    trailer_match_certification = models.BooleanField(
        default=True, help_text="Match certification with reference movie"
    )
    trailer_year_delta = models.PositiveIntegerField(default=5, help_text="Year range for trailer matching")
    trailer_tag = models.ForeignKey(
        TrailerTag,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Only pick trailers carrying this tag (bound trailer rules)",
    )

    # Snapshot captured on save, so the block still describes a since-deleted movie.
    cached_title = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Snapshot of the movie title, preserved if the movie is deleted",
    )
    cached_year = models.PositiveIntegerField(
        null=True, blank=True, help_text="Snapshot of the movie year, preserved if the movie is deleted"
    )

    class Meta:
        ordering = ["order"]

    @property
    def content_object(self):
        if self.content_type == "movie":
            return self.movie
        if self.content_type == "bumper":
            return self.bumper
        if self.content_type == "command":
            return self.command
        if self.content_type == "trailer":
            return self.trailer
        if self.content_type == "certification":
            # Production stores the reference Movie; legacy rows point at the clip.
            return self.movie or self.certification
        return None

    def save(self, *args, **kwargs):
        # Refresh snapshot while the movie still resolves; never blank it once gone.
        if self.content_type == "movie" and self.movie is not None:
            self.cached_title = self.movie.title or self.cached_title
            if self.movie.year is not None:
                self.cached_year = self.movie.year
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.programme.name} - Block {self.order}"


class ProgrammeTitleTemplate(models.Model):
    name = models.CharField(max_length=255, unique=True, help_text="Template name")
    description = models.TextField(blank=True, help_text="Description of this template")

    template_config = models.JSONField(default=dict, help_text="JSON configuration for title card layout")

    default_duration = models.PositiveIntegerField(
        default=10, help_text="Default duration in seconds when using static backgrounds"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ["name"]
        verbose_name = "Programme Title Template"
        verbose_name_plural = "Programme Title Templates"
