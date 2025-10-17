# app_market/collectors/registry.py
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol

from django.conf import settings

log = logging.getLogger(__name__)


class ProviderAdapter(Protocol):
    def __init__(self, *args, **kwargs) -> None: ...
    def wallet_assets(self) -> Any: ...
    def prices_spot(self) -> Any: ...
    def markets(self) -> Any: ...
    def get_last_raw(self) -> Any: ...
    @property
    def last_raw(self) -> Any: ...


@dataclass
class ProviderEntry:
    name: str
    dotted_path: str
    capabilities: Dict[str, bool]
    enabled: bool = True
    needs_api_key: bool = False


REGISTRY: Dict[str, ProviderEntry] = {}


def register(name: str, dotted_path: str, capabilities: Dict[str, bool], *,
             enabled: bool = True, needs_api_key: bool = False) -> None:
    REGISTRY[name] = ProviderEntry(
        name=name,
        dotted_path=dotted_path,
        capabilities=capabilities,
        enabled=enabled,
        needs_api_key=needs_api_key,
    )


def _load_class(dotted: str):
    if ":" not in dotted:
        raise ValueError(f"Invalid dotted path '{dotted}', expected 'module:Class'")
    mod_name, cls_name = dotted.split(":", 1)
    module = importlib.import_module(mod_name)
    return getattr(module, cls_name)


def get_entry(name: str) -> ProviderEntry:
    entry = REGISTRY.get(name)
    if entry:
        return entry
    cfg = getattr(settings, "COLLECTORS_PROVIDER_REGISTRY", {})
    item = cfg.get(name)
    if not item:
        raise KeyError(f"Provider '{name}' is not registered; add to registry.py or settings.COLLECTORS_PROVIDER_REGISTRY")
    return ProviderEntry(
        name=name,
        dotted_path=item["path"],
        capabilities=item.get("cap", {}),
        enabled=item.get("enabled", True),
        needs_api_key=item.get("needs_api", False),
    )


def make_adapter(name: str, credentials: Optional[Any] = None, **kwargs: Any) -> ProviderAdapter:
    """
    Некоторые адаптеры не принимают credentials в __init__.
    Пытаемся сначала с credentials=..., если сигнатура не поддерживает — создаём без него.
    """
    entry = get_entry(name)
    cls = _load_class(entry.dotted_path)
    try:
        adapter = cls(credentials=credentials, **kwargs)
        return adapter
    except TypeError as e:
        log.debug("Adapter %s init without credentials (signature mismatch): %s", entry.dotted_path, e)
        adapter = cls(**kwargs)
        return adapter
