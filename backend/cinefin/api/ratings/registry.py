_REGISTRY: dict[str, type] = {}


def register(cls):
    if not cls.system:
        raise ValueError(f"{cls.__name__} has no `system` identifier")
    _REGISTRY[cls.system] = cls
    return cls


def get_provider(system: str):
    cls = _REGISTRY.get(system)
    return cls() if cls else None


def list_systems() -> list[str]:
    return sorted(_REGISTRY)
