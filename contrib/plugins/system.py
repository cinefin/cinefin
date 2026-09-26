"""System actions — run Cinefin's own operations as Commands.

Unlike the other providers (which reach outward to REST/Home Assistant/WoL), this
first-party provider calls *inward* to Cinefin services, so an operator can restart
the player or drop back to the idle ident from the remote, a schedule, a pre-show
cue, or a running-order block. The action set is a fixed, curated dispatch table on
purpose — adding one is a single entry, not a new mechanism."""

from cinefin.plugins import CommandProvider, Field, register


def _restart_player() -> tuple[bool, str, str]:
    from cinefin.api.services.playout_agent_service import playout_agent_service

    playout_agent_service.restart_mpv()  # raises (surfaced by run) if the agent is unreachable
    return True, "player restarted", ""


def _reset_ident() -> tuple[bool, str, str]:
    from cinefin.api.mpv_service import mpv_service

    if mpv_service.reset():
        return True, "reset to the idle ident", ""
    return False, "could not reach the player", ""


# The choice string is BOTH the label the SPA shows and the stable id stored in the
# command's config, so keep these strings stable once shipped.
_ACTIONS = {
    "Restart the player": _restart_player,
    "Reset to the idle ident": _reset_ident,
}


@register
class System(CommandProvider):
    id = "system"
    label = "System"
    icon = "terminal"
    description = "Run a Cinefin system action (restart the player, reset to the idle ident)"
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

    def summary(self, config):
        return (config.get("action") or "").strip()
