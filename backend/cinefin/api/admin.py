from django.contrib import admin
from django.utils.html import format_html

from .models import (
    APIKey,
    AudioTrack,
    Bumper,
    Certification,
    Command,
    Genre,
    Movie,
    MoviePlayback,
    Playlist,
    PlaylistItem,
    PlayoutHost,
    Programme,
    ProgrammeBlock,
    ProgrammeSchedule,
    ProgrammeTemplate,
    ProgrammeTemplateItem,
    ProgrammeTitleTemplate,
    Settings,
    SubtitleTrack,
    SyncSource,
    Tag,
    Trailer,
    TrailerRule,
)


class AudioTrackInline(admin.TabularInline):
    model = AudioTrack
    extra = 1


class SubtitleTrackInline(admin.TabularInline):
    model = SubtitleTrack
    extra = 1


@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "director",
        "year",
        "duration",
        "certification",
        "display_genres",
        "thumbnail_preview",
        "date_added",
        "kiosk_display",
    )
    list_filter = ("certification", "genres", "year", "kiosk_display")
    search_fields = ("title", "director", "description", "kiosk_display")
    inlines = [AudioTrackInline, SubtitleTrackInline]
    filter_horizontal = ("genres",)

    def display_genres(self, obj):
        return ", ".join([genre.name for genre in obj.genres.all()])

    display_genres.short_description = "Genres"

    def thumbnail_preview(self, obj):
        # Live from the media server via the poster proxy — nothing is stored.
        if obj.poster_key:
            return format_html('<img src="{}" width="50" height="50" />', obj.thumbnail_url)
        return "No poster"

    thumbnail_preview.short_description = "Poster"


@admin.register(Certification)
class CertificationAdmin(admin.ModelAdmin):
    list_display = ("file_path", "movie", "certification")


@admin.register(Trailer)
class TrailerAdmin(admin.ModelAdmin):
    list_display = ("title", "associated_movie", "director", "year", "duration", "content_rating")
    list_filter = ("content_rating", "year")
    search_fields = ("title", "director", "associated_movie__title")


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ("name", "movie_count", "trailler_count")

    def movie_count(self, obj):
        return obj.movie_set.count()

    def trailler_count(self, obj):
        return obj.trailer_set.count()

    movie_count.short_description = "Number of Movies"


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "bumper_count")

    def bumper_count(self, obj):
        return obj.bumper_set.count()

    bumper_count.short_description = "Number of Bumpers"


@admin.register(Bumper)
class BumperAdmin(admin.ModelAdmin):
    list_display = ("title", "duration", "display_tags")
    filter_horizontal = ("tags",)

    def display_tags(self, obj):
        return ", ".join([tag.name for tag in obj.tags.all()])

    display_tags.short_description = "Tags"


@admin.register(Command)
class CommandAdmin(admin.ModelAdmin):
    list_display = ("name", "command_preview", "show_on_remote")

    def command_preview(self, obj):
        return obj.command[:50] + "..." if len(obj.command) > 50 else obj.command

    command_preview.short_description = "Command Preview"


# Fields shared by the ProgrammeBlock inline and admin. The typed content FKs
# (movie/bumper/command/trailer/certification) replaced the old
# GenericForeignKey widget + /admin/get_content_objects/ AJAX helper — Django
# admin handles plain FKs natively.
PROGRAMME_BLOCK_FIELDS = (
    "order",
    "content_type",
    "movie",
    "bumper",
    "command",
    "trailer",
    "certification",
    "trailer_rule",
    "random_tag",
    "random_count",
    "audio_track_index",
    "subtitle_track_index",
)


class ProgrammeBlockInline(admin.TabularInline):
    model = ProgrammeBlock
    fields = PROGRAMME_BLOCK_FIELDS
    raw_id_fields = ("movie", "trailer", "certification", "trailer_rule")
    extra = 1


@admin.register(Programme)
class ProgrammeAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at", "updated_at", "block_count", "has_playlist", "has_title")
    search_fields = ("name", "description")
    inlines = [ProgrammeBlockInline]
    list_filter = ("title_template", "title_background_type")

    fieldsets = (
        ("Basic Information", {"fields": ("name", "description", "template")}),
        (
            "Programme Title Card",
            {
                "fields": (
                    "title_template",
                    "title_background_type",
                    "title_background_color",
                    "title_background_file",
                    "title_duration",
                    "title_file",
                ),
                "classes": ("collapse",),
                "description": "Configure automatic title card generation for this programme",
            },
        ),
    )

    readonly_fields = ("title_file",)

    def block_count(self, obj):
        return obj.blocks.count()

    block_count.short_description = "Number of Blocks"

    def has_playlist(self, obj):
        return hasattr(obj, "playlist")

    has_playlist.boolean = True
    has_playlist.short_description = "Playlist Created"

    def has_title(self, obj):
        return obj.has_title_configured()

    has_title.boolean = True
    has_title.short_description = "Title Configured"


@admin.register(ProgrammeBlock)
class ProgrammeBlockAdmin(admin.ModelAdmin):
    fields = ("programme",) + PROGRAMME_BLOCK_FIELDS
    raw_id_fields = ("movie", "trailer", "certification", "trailer_rule")
    list_display = (
        "programme",
        "order",
        "get_content_type",
        "get_content_object",
        "audio_track_index",
        "subtitle_track_index",
    )
    list_filter = ("programme", "content_type")
    search_fields = ("programme__name",)

    def get_content_type(self, obj):
        return obj.content_type

    get_content_type.short_description = "Content Type"

    def get_content_object(self, obj):
        if obj.content_object:
            return str(obj.content_object)
        elif obj.trailer_rule:
            return f"Trailer Rule: {obj.trailer_rule}"
        elif obj.random_tag:
            count_text = f" x{obj.random_count}" if getattr(obj, "random_count", 1) > 1 else ""
            return f"Random ({obj.random_tag}){count_text}"
        return "N/A"

    get_content_object.short_description = "Content"


@admin.register(TrailerRule)
class TrailerRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "reference_movie", "certificate_ceiling", "year_from", "year_to", "number_of_trailers")
    list_filter = ("certificate_ceiling",)
    search_fields = ("name", "reference_movie__title")


class PlaylistItemInline(admin.TabularInline):
    model = PlaylistItem
    extra = 1


@admin.register(Playlist)
class PlaylistAdmin(admin.ModelAdmin):
    list_display = ("programme", "created_at", "item_count")
    inlines = [PlaylistItemInline]

    def item_count(self, obj):
        return obj.items.count()

    item_count.short_description = "Number of Items"


@admin.register(ProgrammeSchedule)
class ProgrammeScheduleAdmin(admin.ModelAdmin):
    list_display = ("programme", "start_time", "runtime")
    list_filter = ("runtime",)
    search_fields = ("programme__name",)


@admin.register(MoviePlayback)
class MoviePlaybackAdmin(admin.ModelAdmin):
    list_display = ("id", "movie", "audio_track_index", "subtitle_track_index")
    list_filter = ("audio_track_index", "subtitle_track_index")
    search_fields = ("movie__title",)
    raw_id_fields = ("movie",)

    def get_queryset(self, request):
        # Optimize query by selecting related movie
        return super().get_queryset(request).select_related("movie")


@admin.register(SyncSource)
class SyncSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "sync_type", "url", "enabled", "last_sync", "created_at")
    list_filter = ("sync_type", "enabled")
    search_fields = ("name", "url")
    readonly_fields = ("last_sync", "created_at", "updated_at")

    fieldsets = (
        ("Basic Information", {"fields": ("name", "sync_type", "enabled")}),
        ("Connection Settings", {"fields": ("url", "token", "libraries")}),
        ("Additional Configuration", {"fields": ("extra_config",), "classes": ("collapse",)}),
        ("Status", {"fields": ("last_sync", "created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def get_readonly_fields(self, request, obj=None):
        """Make token field read-only for existing objects for security."""
        readonly = list(self.readonly_fields)
        if obj:  # Editing existing object
            readonly.append("token")
        return readonly


class ProgrammeTemplateItemInline(admin.TabularInline):
    model = ProgrammeTemplateItem
    extra = 1
    fields = (
        "order",
        "item_type",
        "feature_number",
        "bound_to_feature",
        "trailer_count",
        "match_genre",
        "match_certification",
        "match_year",
        "year_delta",
        "certification_feature",
        "count",
        "command",
        "bumper",
        "tag",
    )
    ordering = ("order",)


@admin.register(ProgrammeTemplate)
class ProgrammeTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "number_of_features", "item_count", "created_at")
    list_filter = ("number_of_features", "created_at")
    search_fields = ("name", "description")
    inlines = [ProgrammeTemplateItemInline]

    def item_count(self, obj):
        return obj.items.count()

    item_count.short_description = "Number of Items"


@admin.register(ProgrammeTemplateItem)
class ProgrammeTemplateItemAdmin(admin.ModelAdmin):
    list_display = ("template", "order", "item_type", "get_item_description", "count")
    list_filter = ("item_type", "template")
    search_fields = ("template__name",)

    def get_item_description(self, obj):
        if obj.item_type == "feature":
            return f"Feature {obj.feature_number or '?'}"
        elif obj.item_type == "trailer_rule":
            return f"{obj.trailer_count} Trailers (Feature {obj.bound_to_feature or '?'})"
        elif obj.item_type == "command":
            return obj.command.name if obj.command else "Command (not selected)"
        elif obj.item_type == "bumper":
            if obj.tag:
                count_text = f" x{obj.count}" if obj.count > 1 else ""
                return f"Random {obj.tag.name}{count_text}"
            return obj.bumper.title if obj.bumper else "User media (not selected)"
        elif obj.item_type == "certification":
            return f"Certification (Feature {obj.certification_feature or '?'})"
        return "Unknown Item"

    get_item_description.short_description = "Description"


@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
    list_display = ("get_cinema_name", "updated_at")
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Settings Data", {"fields": ("data",), "description": "JSON settings data. Edit with caution."}),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def get_cinema_name(self, obj):
        """Display cinema name from JSON data."""
        return obj.data.get("cinema", {}).get("name", "Cinefin")

    get_cinema_name.short_description = "Cinema Name"

    def has_add_permission(self, request):
        """Only allow one settings instance"""
        return not Settings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of settings"""
        return False


@admin.register(ProgrammeTitleTemplate)
class ProgrammeTitleTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "default_duration", "programme_count", "created_at", "updated_at")
    search_fields = ("name", "description")
    readonly_fields = ("created_at", "updated_at")

    fieldsets = (
        ("Basic Information", {"fields": ("name", "description", "default_duration")}),
        (
            "Template Configuration",
            {"fields": ("template_config",), "description": "JSON configuration for title card layout"},
        ),
        ("Metadata", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def programme_count(self, obj):
        return obj.programmes.count()

    programme_count.short_description = "Programmes Using Template"


@admin.register(PlayoutHost)
class PlayoutHostAdmin(admin.ModelAdmin):
    list_display = ("name", "base_url", "enabled", "is_active", "last_seen_at", "agent_version", "os", "arch")
    list_filter = ("enabled", "is_active")
    search_fields = ("name", "base_url")
    readonly_fields = ("last_seen_at", "agent_version", "os", "arch", "created_at", "updated_at")


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    # View/revoke only — the raw key exists once at creation (via the API), so
    # keys aren't hand-authored here; the hash is never editable.
    list_display = ("name", "prefix", "created_at", "last_used_at")
    search_fields = ("name", "prefix")
    readonly_fields = ("prefix", "key_hash", "created_at", "last_used_at")


# Register the models that don't need custom admin classes
admin.site.register(AudioTrack)
admin.site.register(SubtitleTrack)
