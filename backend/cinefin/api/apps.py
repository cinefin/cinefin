import atexit
import logging
import os
import re
import signal
import sys
import threading

from django.apps import AppConfig

logger = logging.getLogger(__name__)

# Management commands that must not spin up the background workers.
_NO_WORKER_COMMANDS = {
    "migrate",
    "makemigrations",
    "collectstatic",
    "shell",
    "shell_plus",
    "test",
    "dbshell",
    "createsuperuser",
    "check",
    "prune_jobs",
    "pair_playout_host",
    "export_openapi",
    "loaddata",
    "dumpdata",
    "showmigrations",
    "sqlmigrate",
    "flush",
}


def _try(label, fn):
    try:
        fn()
    except Exception:  # noqa: BLE001 - one failing worker must not stop boot
        logger.exception("Failed to %s", label)


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cinefin.api"

    def ready(self):
        from django.db.models.signals import post_migrate

        from cinefin import plugins

        self._assert_single_web_worker()
        self._register_cleanup_handlers()
        self._ensure_media_tree()
        self._maybe_start_background_workers()
        self._warn_on_risky_settings()
        # Built-in commands (the system provider's actions) exist after every migrate.
        post_migrate.connect(plugins.ensure_builtin_commands, sender=self)

    @staticmethod
    def _assert_single_web_worker():
        """Refuse to boot gunicorn with more than one worker: playout state, the
        schedule runner and the sync engine are per-process, so N workers race.
        Only the argv/env forms are detectable, not a gunicorn config file."""
        cmdline = " ".join(sys.argv) + " " + os.environ.get("GUNICORN_CMD_ARGS", "")
        if "gunicorn" not in cmdline:
            return
        match = re.search(r"(?:^|\s)(?:-w|--workers)[= ]\s*(\d+)", cmdline)
        if match and int(match.group(1)) > 1:
            from django.core.exceptions import ImproperlyConfigured

            raise ImproperlyConfigured(
                f"Cinefin must run with exactly one gunicorn worker (got --workers "
                f"{match.group(1)}). Playout state, the schedule runner and the sync "
                f"engine are per-process; use --workers 1 --threads N for concurrency "
                f"(see etc/cinefin3.service)."
            )

    @staticmethod
    def _warn_on_risky_settings():
        from django.conf import settings

        log = logging.getLogger("cinefin")
        if getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False):
            log.warning(
                "CINEFIN_CORS_ALL=1: any website can call this API from a visitor's "
                "browser. Prefer CINEFIN_CORS_ORIGINS with an explicit list."
            )
        if settings.DEBUG:
            log.warning("DEBUG is on — never expose this instance beyond your own machine.")

    @staticmethod
    def _ensure_media_tree():
        """Create the MEDIA_ROOT subdirectories (it may be a fresh, empty volume)."""
        from django.conf import settings

        from .utils.media_tree import media_subdir_paths, unwritable_media_subdirs

        if getattr(settings, "CINEFIN_DISABLE_BACKGROUND_WORKERS", False):
            return  # test runs must not touch the real media tree

        try:
            for path in media_subdir_paths():
                os.makedirs(path, exist_ok=True)
        except Exception:  # noqa: BLE001 - a read-only mount must not stop boot
            logger.exception("Failed to create media directories")
            return

        # makedirs(exist_ok=True) succeeds on directories another user owns (e.g. a
        # previous Docker run as root); surface that once at boot, not per write.
        unwritable = unwritable_media_subdirs()
        if unwritable:
            logger.error(
                "Media directories exist but are NOT writable by this process: %s. "
                "Uploads and generated media will fail. Fix ownership, "
                "e.g. 'sudo chown -R <app-user> %s'.",
                ", ".join(unwritable),
                settings.MEDIA_ROOT,
            )

    def _maybe_start_background_workers(self):
        from django.conf import settings

        if getattr(settings, "CINEFIN_DISABLE_BACKGROUND_WORKERS", False):
            return
        argv = sys.argv
        if len(argv) > 1 and argv[1] in _NO_WORKER_COMMANDS:
            return
        # Under runserver's autoreloader only the reloaded child (RUN_MAIN=true)
        # runs the workers, not the watcher parent.
        if (
            len(argv) > 1
            and argv[1] == "runserver"
            and "--noreload" not in argv
            and os.environ.get("RUN_MAIN") != "true"
        ):
            return

        from .services import playout_link, schedule_runner
        from .sync import engine

        _try("start sync engine", engine.start)
        _try("start schedule runner", schedule_runner.start)
        _try("start the playout link keeper", playout_link.start)
        # Querying the DB inside ready() is discouraged, so recovery runs off the init path.
        threading.Thread(target=self._recover_orphans, name="orphan-recovery", daemon=True).start()

    @staticmethod
    def _recover_orphans():
        """Trailer jobs (ad-hoc threads) and schedules claimed 'running' are left
        stranded by a crash; reconcile both on boot."""
        from django.db import close_old_connections

        from .services import schedule_runner
        from .services.trailer_jobs import recover_orphans as recover_trailer_orphans

        try:
            _try("recover orphaned trailer jobs", recover_trailer_orphans)
            _try("recover orphaned schedules", schedule_runner.recover_orphans)
        finally:
            close_old_connections()

    def _register_cleanup_handlers(self):
        def cleanup_mpv():
            try:
                from .mpv_service import mpv_service

                if getattr(mpv_service, "controller", None):
                    mpv_service.controller.terminate()
            except Exception:  # noqa: BLE001 - best effort at exit
                pass

        def signal_handler(_signum, _frame):
            cleanup_mpv()
            sys.exit(0)

        atexit.register(cleanup_mpv)
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
