"""Command-provider plugins: the contract plugins import, the registry, and the contrib loader.

A provider is one kind of action a Command can run (REST, Home Assistant, Wake-on-LAN, …). Every provider
is a plugin: a single file (or package) under ``<repo>/contrib/plugins/``, added by pull request and
loaded on first registry access. A plugin that fails to import is skipped and reported — it never stops
boot or playback. See docs/PLUGINS.md.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("cinefin.plugins")

#: Bumped only when the provider contract changes incompatibly; a plugin declaring another value is refused.
PLUGIN_API = 1

#: The time budget for run(); a hold-black block stops waiting a little after it.
RUN_TIMEOUT = 30

FIELD_TYPES = ("text", "textarea", "secret", "number", "boolean", "select", "json")

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_CONTRIB_PACKAGE = "cinefin_contrib_plugins"


class PluginError(Exception):
    pass


@dataclass(frozen=True)
class Field:
    """One form field. The SPA renders these generically; values land in the command's config dict."""

    key: str
    label: str = ""
    type: str = "text"
    required: bool = False
    default: Any = None
    placeholder: str = ""
    help: str = ""
    choices: tuple[str, ...] = ()
    #: Only suggestions whose ``scope`` equals this other field's value are offered (all, if none match).
    scoped_by: str = ""

    def __post_init__(self):
        if self.type not in FIELD_TYPES:
            raise PluginError(f"Field '{self.key}' has unknown type '{self.type}' (one of {', '.join(FIELD_TYPES)})")
        if self.type == "select" and not self.choices:
            raise PluginError(f"Select field '{self.key}' needs choices")

    def to_dict(self) -> dict:
        data = asdict(self)
        data["label"] = self.label or self.key.replace("_", " ").capitalize()
        data["choices"] = list(self.choices)
        return data


class CommandProvider:
    """Base class for a provider; subclass it and decorate with ``@register``."""

    id: str = ""
    label: str = ""
    #: A lucide icon name the SPA knows (globe, house, zap, power, radio, lightbulb, …); unknown → zap.
    icon: str = "zap"
    description: str = ""
    plugin_api: int = PLUGIN_API
    #: Per-command configuration, edited in the command dialog.
    fields: list[Field] = []
    #: Provider-wide settings (a broker URL, a password), edited once under Settings → Plugins.
    settings: list[Field] = []

    # Set by the registry: the contrib file the provider came from.
    source: str = ""

    def run(self, config: dict, settings: dict) -> tuple[bool, str, str]:
        """Do the action. Return (ok, detail, output): detail is a short outcome ("HTTP 200"), output the
        captured response. Raising is safe — it is reported as a failed run. Finish within
        RUN_TIMEOUT (30 s): a hold-black block waits for this, then gives up."""
        raise NotImplementedError

    def summary(self, config: dict) -> str:
        """One-line description of what a configured command targets, shown in lists."""
        return ""

    def suggestions(self, settings: dict) -> dict[str, list[dict]]:
        """Optional autocomplete values per field key: [{"value", "label"?, "scope"?}]. Raise with a
        readable message when the source is unreachable; the dialog shows it and falls back to free text."""
        return {}

    def test_settings(self, settings: dict) -> tuple[bool, str]:
        """Optional: check (unsaved) settings work — a Test button on the Plugins page. Must not raise."""
        raise NotImplementedError

    def discover(self) -> list[dict]:
        """Optional: find candidate settings on the network — a Discover button on the Plugins page.
        Return [{"label": "Living room HA", "values": {"url": …}}]; the operator picks one."""
        raise NotImplementedError

    def load_settings(self) -> dict:
        from cinefin.api.models import Settings

        defaults = {f.key: f.default for f in self.settings if f.default is not None}
        return defaults | (Settings.get(f"plugins.{self.id}") or {})

    def save_settings(self, values: dict) -> None:
        from cinefin.api.models import Settings

        Settings.set(f"plugins.{self.id}", values)

    def validate_config(self, config: dict) -> list[str]:
        return _validate(self.fields, config)

    def validate_settings(self, values: dict) -> list[str]:
        return _validate(self.settings, values)

    def supports(self, method: str) -> bool:
        """Whether this provider implements an optional hook (suggestions, test_settings, discover)."""
        return getattr(type(self), method) is not getattr(CommandProvider, method)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label or self.id,
            "icon": self.icon,
            "description": self.description,
            "source": self.source,
            "enabled": is_enabled(self.id),
            "has_suggestions": self.supports("suggestions"),
            "has_settings_test": self.supports("test_settings"),
            "has_discover": self.supports("discover"),
            "fields": [f.to_dict() for f in self.fields],
            "settings": [f.to_dict() for f in self.settings],
        }


def _validate(fields: list[Field], values: dict) -> list[str]:
    values = values or {}
    problems = []
    for field in fields:
        value = values.get(field.key)
        empty = value is None or value == "" or value == {} or value == []
        if field.required and empty:
            problems.append(f"{field.label or field.key} is required")
        elif not empty and field.type == "select" and value not in field.choices:
            problems.append(f"{field.label or field.key} must be one of {', '.join(field.choices)}")
        elif not empty and field.type == "json" and not isinstance(value, dict | list):
            problems.append(f"{field.label or field.key} must be a JSON object or array")
    return problems


_registry: dict[str, CommandProvider] = {}
_failures: list[dict] = []
_loaded = False
_lock = threading.RLock()
_current_source = ""


def register(cls: type[CommandProvider]) -> type[CommandProvider]:
    if not _ID_RE.match(getattr(cls, "id", "") or ""):
        raise PluginError(f"{cls.__name__}.id must be lowercase letters, digits or _ (got {cls.id!r})")
    if cls.plugin_api != PLUGIN_API:
        raise PluginError(f"{cls.__name__} targets plugin API {cls.plugin_api}; this Cinefin provides {PLUGIN_API}")
    if cls.id in _registry:
        raise PluginError(f"Provider id '{cls.id}' is already registered by {_registry[cls.id].source}")
    provider = cls()
    provider.source = _current_source
    _registry[cls.id] = provider
    logger.debug("Registered command provider: %s (%s)", cls.id, provider.source)
    return cls


def plugins_dir() -> Path:
    from django.conf import settings

    return Path(getattr(settings, "CINEFIN_PLUGINS_DIR", None) or Path(settings.REPO_ROOT) / "contrib" / "plugins")


def _plugin_paths(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    paths = []
    for path in sorted(root.iterdir()):
        if path.name.startswith(("_", ".", "test_")):
            continue
        if (path.is_file() and path.suffix == ".py") or (path.is_dir() and (path / "__init__.py").is_file()):
            paths.append(path)
    return paths


def _import_contrib(path: Path) -> None:
    global _current_source
    name = f"{_CONTRIB_PACKAGE}.{path.stem}"
    if path.is_dir():
        spec = importlib.util.spec_from_file_location(
            name, path / "__init__.py", submodule_search_locations=[str(path)]
        )
    else:
        spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    before = set(_registry)
    _current_source = f"contrib/plugins/{path.name}"
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        for provider_id in set(_registry) - before:
            del _registry[provider_id]
        raise
    finally:
        _current_source = ""


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        if _CONTRIB_PACKAGE not in sys.modules:
            package = type(sys)(_CONTRIB_PACKAGE)
            package.__path__ = []
            sys.modules[_CONTRIB_PACKAGE] = package
        for path in _plugin_paths(plugins_dir()):
            try:
                _import_contrib(path)
            except Exception as exc:  # noqa: BLE001 - a broken plugin must never stop Cinefin
                logger.exception("Plugin %s failed to load", path.name)
                _failures.append(
                    {"source": f"contrib/plugins/{path.name}", "error": f"{exc.__class__.__name__}: {exc}"}
                )
        _loaded = True


# Enable/disable is a soft toggle held in Settings (plugins._disabled — a reserved
# key: no plugin id can start with "_"). A disabled provider stays loaded but is
# hidden from the command picker and refuses to run; its settings are preserved.
def _disabled_ids() -> set[str]:
    from cinefin.api.models import Settings

    return set(Settings.get("plugins._disabled") or [])


def is_enabled(provider_id: str) -> bool:
    return provider_id not in _disabled_ids()


def set_enabled(provider_id: str, enabled: bool) -> None:
    from cinefin.api.models import Settings

    disabled = _disabled_ids()
    disabled.discard(provider_id) if enabled else disabled.add(provider_id)
    Settings.set("plugins._disabled", sorted(disabled))


def get_provider(provider_id: str) -> CommandProvider | None:
    _ensure_loaded()
    return _registry.get(provider_id)


def list_providers() -> list[CommandProvider]:
    _ensure_loaded()
    return sorted(_registry.values(), key=lambda p: (p.label or p.id).lower())


def load_failures() -> list[dict]:
    _ensure_loaded()
    return list(_failures)


def _reset_for_tests() -> None:
    global _loaded
    with _lock:
        _registry.clear()
        _failures.clear()
        for name in [n for n in sys.modules if n == _CONTRIB_PACKAGE or n.startswith(f"{_CONTRIB_PACKAGE}.")]:
            del sys.modules[name]
        _loaded = False
