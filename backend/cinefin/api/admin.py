"""Django admin: a development tool, mounted only with DEBUG on (see cinefin/urls.py)."""

from django.contrib import admin

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
    extra = 0


class SubtitleTrackInline(admin.TabularInline):
    model = SubtitleTrack
    extra = 0


@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ("title", "director", "year", "certification", "kiosk_display")
    list_filter = ("certification", "year", "kiosk_display")
    search_fields = ("title", "director")
    inlines = [AudioTrackInline, SubtitleTrackInline]
    filter_horizontal = ("genres",)


@admin.register(Trailer)
class TrailerAdmin(admin.ModelAdmin):
    list_display = ("title", "associated_movie", "year", "content_rating")
    search_fields = ("title", "associated_movie__title")


class ProgrammeBlockInline(admin.TabularInline):
    model = ProgrammeBlock
    raw_id_fields = ("movie", "trailer", "certification", "trailer_rule")
    extra = 0


@admin.register(Programme)
class ProgrammeAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at", "updated_at")
    search_fields = ("name",)
    inlines = [ProgrammeBlockInline]


class PlaylistItemInline(admin.TabularInline):
    model = PlaylistItem
    extra = 0


@admin.register(Playlist)
class PlaylistAdmin(admin.ModelAdmin):
    inlines = [PlaylistItemInline]


class ProgrammeTemplateItemInline(admin.TabularInline):
    model = ProgrammeTemplateItem
    extra = 0


@admin.register(ProgrammeTemplate)
class ProgrammeTemplateAdmin(admin.ModelAdmin):
    inlines = [ProgrammeTemplateItemInline]


@admin.register(SyncSource)
class SyncSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "sync_type", "url", "enabled", "last_sync")

    def get_readonly_fields(self, request, obj=None):
        # The token stays read-only once saved.
        return ("last_sync", "token") if obj else ("last_sync",)


@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not Settings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PlayoutHost)
class PlayoutHostAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "base_url", "enabled", "is_active", "last_seen_at")


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    # View/revoke only: the raw key exists once, at creation through the API.
    list_display = ("name", "prefix", "created_at", "last_used_at")
    readonly_fields = ("prefix", "key_hash", "created_at", "last_used_at")


admin.site.register(
    [
        AudioTrack,
        Bumper,
        Certification,
        Command,
        Genre,
        MoviePlayback,
        ProgrammeBlock,
        ProgrammeSchedule,
        ProgrammeTemplateItem,
        ProgrammeTitleTemplate,
        SubtitleTrack,
        Tag,
        TrailerRule,
    ]
)
