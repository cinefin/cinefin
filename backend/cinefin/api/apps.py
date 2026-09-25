import atexit
import signal
import sys

from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cinefin.api"

    def ready(self):
        # Don't auto-start MPV service - use lazy initialization instead
        # This prevents threads from blocking Django processes like migrate

        # A multi-worker gunicorn silently breaks playout — refuse to boot one.
        self._assert_single_web_worker()

        # Register cleanup handlers for graceful shutdown
        self._register_cleanup_handlers()

        # Make sure the usermedia tree exists (it may be a freshly mounted,
        # empty volume) before anything tries to write into it.
        self._ensure_media_tree()

        # Start the background workers (sync engine + schedule runner), but
        # never during management commands like migrate/makemigrations/shell.
        self._maybe_start_background_workers()

        # One-line nudges for footgun configurations.
        self._warn_on_risky_settings()

    @staticmethod
    def _assert_single_web_worker():
        """Refuse to boot gunicorn with more than one worker process.

        The MPV/playout service is a per-process singleton and the schedule
        runner + sync engine start one thread per process, so N workers means
        N disconnected playout state machines and N schedule runners claiming
        the same rows. The systemd unit ships ``--workers 1`` (concurrency
        comes from ``--threads``); this guard turns the misconfiguration into
        a clear boot failure instead of subtle races. Only the argv/env forms
        are detectable — a gunicorn config file with ``workers = N`` is not,
        which is acceptable: the shipped deployments don't use one.
        """
        import os
        import re
        import sys

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
        import logging

        from django.conf import settings

        logger = logging.getLogger("cinefin")
        if getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False):
            logger.warning(
                "CINEFIN_CORS_ALL=1: any website can call this API from a visitor's "
                "browser. Prefer CINEFIN_CORS_ORIGINS with an explicit list."
            )
        if settings.DEBUG:
            logger.warning("DEBUG is on — never expose this instance beyond your own machine.")

    @staticmethod
    def _ensure_media_tree():
        """Create the MEDIA_ROOT subdirectories the app writes into or reads from."""
        import os

        from django.conf import settings

        from .utils.media_tree import media_subdir_paths, unwritable_media_subdirs

        if getattr(settings, "CINEFIN_DISABLE_BACKGROUND_WORKERS", False):
            return  # test runs must not touch the real media tree

        try:
            for path in media_subdir_paths():
                os.makedirs(path, exist_ok=True)
        except Exception:  # noqa: BLE001 - a read-only mount must not stop boot
            import logging

            logging.getLogger(__name__).exception("Failed to create media directories")
            return

        # makedirs(exist_ok=True) succeeds on directories another user owns
        # (e.g. a previous Docker run created them as root) — then every write
        # fails later, one confusing error at a time. Surface it once at boot.
        unwritable = unwritable_media_subdirs()
        if unwritable:
            import logging

            logging.getLogger(__name__).error(
                "Media directories exist but are NOT writable by this process: %s. "
                "Uploads and generated media will fail. Fix ownership, "
                "e.g. 'sudo chown -R <app-user> %s'.",
                ", ".join(unwritable),
                settings.MEDIA_ROOT,
            )

    def _maybe_start_background_workers(self):
        import os
        import sys

        from django.conf import settings

        # Test runs (pytest uses cinefin.test_settings) must never spawn the
        # engine worker or recovery threads.
        if getattr(settings, "CINEFIN_DISABLE_BACKGROUND_WORKERS", False):
            return

        # Skip for management commands that shouldn't spin up workers.
        skip_commands = {
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
        argv = sys.argv
        if len(argv) > 1 and argv[1] in skip_commands:
            return
        # Under runserver's autoreloader, only the reloaded child (RUN_MAIN=true)
        # should run the workers — not the watcher parent. With --noreload there
        # is no child and RUN_MAIN is never set, so start normally. gunicorn and
        # other entrypoints don't set RUN_MAIN either.
        if (
            len(argv) > 1
            and argv[1] == "runserver"
            and "--noreload" not in argv
            and os.environ.get("RUN_MAIN") != "true"
        ):
            return
        try:
            from .sync import engine

            engine.start()
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger("cinefin.sync.engine").exception("Failed to start sync engine")

        # Programme schedule runner — plays due ProgrammeSchedule rows in a
        # background thread of this process (which owns the MPV state machine).
        try:
            from .services import schedule_runner

            schedule_runner.start()
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception("Failed to start schedule runner")

        # Opt-in telemetry — a daily anonymous heartbeat (no-op unless enabled).
        try:
            from .services import telemetry_service

            telemetry_service.start()
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception("Failed to start telemetry")

        # Trailer jobs run on ad-hoc threads (no resumable worker), so any left
        # "running" by a crash/restart must be marked failed on boot. Run it off
        # the init path — querying the DB inside ready() is discouraged.
        import threading

        threading.Thread(
            target=self._recover_orphans,
            name="orphan-recovery",
            daemon=True,
        ).start()

    @staticmethod
    def _recover_orphans():
        from django.db import close_old_connections

        # Trailer jobs run on ad-hoc threads; schedules are claimed 'running'
        # before load+start. Both must be reconciled on boot after a crash.
        try:
            from .services.trailer_jobs import recover_orphans as recover_trailer_orphans

            recover_trailer_orphans()
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception("Failed to recover orphaned trailer jobs")

        try:
            from .services import schedule_runner

            schedule_runner.recover_orphans()
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception("Failed to recover orphaned schedules")
        finally:
            close_old_connections()

    def _register_cleanup_handlers(self):
        """Register cleanup handlers for MPV service shutdown"""

        def cleanup_mpv():
            try:
                from .mpv_service import mpv_service

                if hasattr(mpv_service, "controller") and mpv_service.controller:
                    mpv_service.controller.terminate()
            except Exception:
                pass  # Ignore errors during cleanup

        # Register cleanup for normal exit
        atexit.register(cleanup_mpv)

        # Register cleanup for signal-based termination (Ctrl+C, etc.)
        def signal_handler(_signum, _frame):
            cleanup_mpv()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
