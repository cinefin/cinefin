"""The singleton Settings model: runtime application configuration stored as JSON."""

import copy

from django.db import models


class Settings(models.Model):
    data = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Ordered tuples are the source of truth; the sets are derived so they can't drift.
    RATINGS_BBFC_ORDER = ("U", "PG", "12", "12A", "15", "18", "R18")
    RATINGS_MPAA_ORDER = ("G", "PG", "PG-13", "R", "NC-17")
    RATINGS_BBFC = set(RATINGS_BBFC_ORDER)
    RATINGS_MPAA = set(RATINGS_MPAA_ORDER)
    VALID_RATINGS_SYSTEMS = ("BBFC", "MPAA")

    DEFAULTS = {
        "cinema": {
            "name": "Cinefin",
            # None = the bundled System Ident (assets/system/ident.mp4).
            "default_ident_id": None,
            "ratings_system": "BBFC",
            # Navbar logo (MEDIA_ROOT-relative); distinct from tickets.logo_path.
            "web_logo_path": None,
        },
        "display": {
            "accent_color": None,
            "time_format": "24h",
            "update_check": True,
        },
        "security": {
            # Default False on purpose: hard-coded True would lock out existing
            # installs on upgrade and break a fresh pre-installer DB. The gate
            # fails open without a usable User (services/auth_service).
            "auth_enabled": False,
            # Kiosk displays can't log in; only /kiosk/ + its read-only status
            # endpoint are exempted. Off if the screen isn't physically trusted.
            "kiosk_public": True,
        },
        "setup": {
            # Until True, installer redirect middleware sends all requests to /installer/.
            "completed": False,
            # Wizard step (2-5) to resume after `completed` flips. 0 = finished.
            "wizard_step": 0,
        },
        "tickets": {
            "total_rows": 10,
            "seats_per_row": 20,
            # "file" = local device file; "network" = ESC/POS over TCP.
            "printer_type": "file",
            "printer_device": "/dev/usb/lp0",
            "printer_host": "",
            "printer_port": 9100,
            # Socket timeout (s); too low aborts a raster write mid-image.
            "printer_timeout": 30,
            # Blank lines fed past the tear bar / cutter. 0–20.
            "feed_lines": 2,
            # Image encoding (raster/column/graphics) or "off"; wrong choice prints garbage.
            "image_mode": "raster",
            # Dots: 384 (58mm) or 576 (80mm). Selects ESC/POS profile, caps image width.
            "paper_width": 384,
            # QR "surprise link" pool — one picked at random per ticket. EMPTY
            # list prints no QR; only a non-list falls back to ticket_service.FUN_QR_LINKS.
            "qr_fun_links": [
                "https://www.youtube.com/watch?v=V14PfDDwxlE",
                "https://www.youtube.com/watch?v=8wI4jMxveyI",
                "https://www.youtube.com/watch?v=qPGYBLaF15M",
                "https://www.youtube.com/watch?v=21h0G_gU9Tw",
                "https://www.youtube.com/watch?v=k8V9vgqeUPM",
                "https://www.youtube.com/watch?v=7bXjWRXDFV8",
                "https://www.youtube.com/watch?v=ZqZdfxc-fq0",
            ],
            # Ordered {"key", "enabled"} sections; "rule" (divider) may repeat.
            # Section vocabulary lives in services/ticket_service.SECTION_KEYS.
            "layout": [
                {"key": "rule", "enabled": True},
                {"key": "logo", "enabled": True},
                {"key": "rule", "enabled": True},
                {"key": "cinema_name", "enabled": True},
                {"key": "header_text", "enabled": True},
                {"key": "admit", "enabled": True},
                {"key": "title", "enabled": True},
                {"key": "rating", "enabled": True},
                {"key": "rule", "enabled": True},
                {"key": "qr", "enabled": True},
                {"key": "footer_text", "enabled": True},
            ],
            # title via ESC/POS double width/height; rating as fraction of width; QR 1-16.
            "title_size": "normal",
            "rating_size": "medium",
            "qr_size": 6,
            # strftime formats validated against preset lists in ticket_service.
            "admit_text": "ADMIT ONE",
            "date_format": "%d/%m/%Y",
            "time_format": "%H:%M",
            # Tokens: {film} {seat} {date} {time} {cinema}.
            "header_text": "",
            "footer_text": "",
        },
        "playout": {
            # Base URL the playout host uses to fetch streamed media from Cinefin;
            # must be reachable FROM the host. Blank = fall back to CINEFIN_SERVER_URL.
            "server_url": "",
            # Subtitle style applied LIVE via set_property on connect/save (no restart).
            "subtitles": {
                "font_size": 55,
                "color": "#FFFFFF",
                # outline-and-shadow | opaque-box | background-box
                "border_style": "outline-and-shadow",
                "back_color": "#000000",
                "position": 100,  # sub-pos 0 (top) – 100 (bottom)
                "margin_y": 22,
                "use_margins": True,
                "bold": False,
            },
        },
        "scheduler": {
            # Command IDs run in order on programme start; a failing one is logged and skipped.
            "preshow_commands": [],
        },
        "kiosk": {
            # Server-side defaults; URL params and the per-screen localStorage picker override.
            # wall | nownext | spotlight | split | marquee | lightbox |
            # board | tonight | auto
            "layout": "wall",
            # Cycle ambient layouts every N min (0 = stay). Ignored while "auto".
            "rotate_minutes": 0,
            "header": True,
            "clock": True,
            "takeover": True,
            "countdown_minutes": 30,  # engage threshold; 0 = off
            "night": False,
            "night_start": "01:00",
            "night_end": "08:00",
            # "flagged" (Movie.kiosk_display) | "all" | "scheduled" (upcoming features).
            "content_source": "flagged",
            "show_showtimes": True,
        },
        "trailers": {
            "tmdb_api_key": "",
            "download_quality": "1080",
            # Backfill missing certs via ratings providers; TMDB stays primary.
            "rating_lookup_enabled": True,
            "upcoming_months_ahead": 6,
            "filename_template": "{title} ({year}) [tmdb-{tmdbid}]",
            "folder_template": "{year}",
        },
    }

    class Meta:
        verbose_name = "Settings"
        verbose_name_plural = "Settings"

    def __str__(self):
        cinema_name = self.get("cinema.name")
        return f"Settings - {cinema_name}"

    @classmethod
    def _get_default(cls, key: str):
        keys = key.split(".")
        value = cls.DEFAULTS
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k, {})
            else:
                return None
        return value if value != {} else None

    @classmethod
    def _get_instance(cls):
        # deepcopy: a shallow copy would share nested dicts/lists with DEFAULTS,
        # so Settings.set would silently rewrite the class-level defaults.
        instance, created = cls.objects.get_or_create(id=1, defaults={"data": copy.deepcopy(cls.DEFAULTS)})
        return instance

    @classmethod
    def get_ratings_system(cls) -> str:
        system = cls.get("cinema.ratings_system") or "BBFC"
        return system if system in cls.VALID_RATINGS_SYSTEMS else "BBFC"

    @classmethod
    def get_valid_ratings(cls, system: str | None = None) -> set:
        system = system or cls.get_ratings_system()
        return cls.RATINGS_MPAA if system == "MPAA" else cls.RATINGS_BBFC

    @classmethod
    def get_ratings_order(cls, system: str | None = None) -> tuple:
        system = system or cls.get_ratings_system()
        return cls.RATINGS_MPAA_ORDER if system == "MPAA" else cls.RATINGS_BBFC_ORDER

    @classmethod
    def get(cls, key: str = None, default=None):
        instance = cls._get_instance()

        if key is None:
            return cls._merge_with_defaults(instance.data)

        keys = key.split(".")
        value = instance.data

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    break
            else:
                value = None
                break

        if value is None:
            default_value = cls._get_default(key)
            return default if default is not None else default_value

        return value

    @classmethod
    def _merge_with_defaults(cls, data: dict) -> dict:
        result = copy.deepcopy(cls.DEFAULTS)

        def merge(base, override):
            for key, value in override.items():
                if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                    merge(base[key], value)
                else:
                    base[key] = value

        merge(result, data or {})
        return result

    @classmethod
    def set(cls, key: str, value):
        instance = cls._get_instance()

        keys = key.split(".")
        data = instance.data

        for k in keys[:-1]:
            if k not in data or not isinstance(data[k], dict):
                data[k] = {}
            data = data[k]

        data[keys[-1]] = value
        instance.save()

    @classmethod
    def update(cls, updates: dict):
        for key, value in updates.items():
            cls.set(key, value)

    @classmethod
    def reset(cls):
        instance = cls._get_instance()
        instance.data = copy.deepcopy(cls.DEFAULTS)
        instance.save()
        return instance

    @classmethod
    def get_all(cls) -> dict:
        return cls.get(None)

    @classmethod
    def get_cinema_name(cls) -> str:
        return cls.get("cinema.name", "Cinefin")
