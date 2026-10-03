"""System actions — Cinefin's own operations as built-in, locked Commands.

Unlike the other providers (which reach outward to REST/Home Assistant/WoL), this
first-party provider calls *inward* to Cinefin services. Each action is a built-in
command (see CommandProvider.builtin_commands): always present, usable anywhere a
command is (remote, dashboard, lead-in, running-order block), never renamed or
deleted. The action set is a fixed dispatch table — adding one is a single entry."""

from cinefin.plugins import CommandProvider, Field, register


def _restart_player() -> tuple[bool, str, str]:
    from cinefin.api.services.playout_agent_service import playout_agent_service

    playout_agent_service.restart_mpv()  # raises (surfaced by run) if the agent is unreachable
    return True, "player restarted", ""


def _player(method: str, done: str):
    def action() -> tuple[bool, str, str]:
        from cinefin.api.mpv_service import mpv_service

        if getattr(mpv_service, method)():
            return True, done, ""
        return False, "could not reach the player", ""

    return action


# The choice string is BOTH the label the SPA shows and the stable id stored in the
# command's config, so keep these strings stable once shipped (a rename needs a
# data migration, as 0049 did for "Reset to the idle ident" -> "Standby").
_ACTIONS = {
    "Restart the player": _restart_player,
    "Standby": _player("standby", "on standby"),
    "Stop the programme": _player("pause", "programme stopped"),  # a pause; "Standby" ends it
    "Pause": _player("pause", "paused"),
    "Resume": _player("play", "resumed"),
}


@register
class System(CommandProvider):
    id = "system"
    label = "System"
    icon = "terminal"
    description = "Cinefin's own actions: restart the player, standby, stop, pause, resume"
    fields = [Field("action", "Action", type="select", choices=tuple(_ACTIONS), required=True)]

    def run(self, config, settings):
        action = (config.get("action") or "").strip()
        fn = _ACTIONS.get(action)
        if fn is None:
            return False, "unknown action", action
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - any service error becomes a failed command, never a crash
            return False, "action failed", str(e)

    def builtin_commands(self):
        return [(action, {"action": action}) for action in _ACTIONS]

    def summary(self, config):
        return (config.get("action") or "").strip()
