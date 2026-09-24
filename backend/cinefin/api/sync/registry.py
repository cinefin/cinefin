from __future__ import annotations

import logging

from .base import SyncSourcePlugin

logger = logging.getLogger("cinefin.sync")

_REGISTRY: dict[str, type[SyncSourcePlugin]] = {}
_loaded = False


def register(cls: type[SyncSourcePlugin]) -> type[SyncSourcePlugin]:
    if not getattr(cls, "type_id", ""):
        raise ValueError(f"Plugin {cls.__name__} must define a non-empty type_id")
    _REGISTRY[cls.type_id] = cls
    logger.debug("Registered sync plugin: %s", cls.type_id)
    return cls


def _ensure_loaded() -> None:
    global _loaded
    if not _loaded:
        from . import plugins  # noqa: F401

        _loaded = True


def get_plugin_class(type_id: str) -> type[SyncSourcePlugin] | None:
    _ensure_loaded()
    return _REGISTRY.get(type_id)


def get_plugin(source) -> SyncSourcePlugin | None:
    cls = get_plugin_class(source.sync_type)
    return cls(source) if cls else None


def list_types() -> list[dict]:
    _ensure_loaded()
    out = []
    for type_id, cls in sorted(_REGISTRY.items()):
        out.append(
            {
                "type_id": type_id,
                "label": cls.label or type_id.title(),
                "operations": list(cls.operations),
                "needs_connection": cls.needs_connection,
            }
        )
    return out
