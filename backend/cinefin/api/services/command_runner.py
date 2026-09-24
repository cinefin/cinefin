"""Command execution service — the single place commands run. Failures never raise to the caller."""

import logging
import threading
from dataclasses import dataclass

from django.db import close_old_connections

from cinefin import plugins
from cinefin.api.models import Command

logger = logging.getLogger("cinefin.automation")

TIMEOUT_SECONDS = plugins.RUN_TIMEOUT
OUTPUT_CAP = 10_000


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    detail: str
    output: str


def _cap(text: str) -> str:
    if text and len(text) > OUTPUT_CAP:
        return text[:OUTPUT_CAP] + f"\n… truncated ({len(text)} bytes total)"
    return text or ""


def _execute(command: Command, trigger: str) -> CommandResult:
    provider = plugins.get_provider(command.provider)
    if provider is None:
        ok, detail, output = False, f"unknown provider '{command.provider}'", ""
    elif not plugins.is_enabled(command.provider):
        ok, detail, output = False, f"provider '{command.provider}' is disabled", ""
    else:
        try:
            ok, detail, output = provider.run(command.config or {}, provider.load_settings())
            ok, detail, output = bool(ok), str(detail or ""), _cap(str(output or ""))
        except Exception as exc:  # a provider bug must never take playback down
            logger.exception(f"Command '{command.name}' raised unexpectedly")
            ok, detail, output = False, f"internal error: {exc.__class__.__name__}", str(exc)

    level = logging.INFO if ok else logging.ERROR
    logger.log(level, f"Command '{command.name}' [{trigger}] via {command.provider}: {detail}")
    return CommandResult(ok=ok, detail=detail, output=output)


def execute(command: Command, trigger: str, wait: bool = False) -> CommandResult | None:
    """wait=True runs inline and returns the result; otherwise fires on a daemon thread, returns None."""
    if wait:
        return _execute(command, trigger)

    def _target():
        close_old_connections()
        _execute(command, trigger)

    threading.Thread(target=_target, daemon=True, name=f"cmd-{command.name[:24]}").start()
    return None


def execute_many_sequential(commands: list[Command], trigger: str) -> None:
    """Run commands in order on one background thread (pre-show list: ordering matters, don't block)."""
    if not commands:
        return

    def _target():
        close_old_connections()
        for command in commands:
            _execute(command, trigger)

    threading.Thread(target=_target, daemon=True, name="cmd-sequence").start()
