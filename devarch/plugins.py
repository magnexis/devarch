from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from typing import Protocol


class Plugin(Protocol):
    name: str

    def register(self) -> None: ...


@dataclass(slots=True)
class PluginInfo:
    name: str
    module: str


def discover_plugins() -> list[PluginInfo]:
    infos: list[PluginInfo] = []
    try:
        entries = metadata.entry_points(group="devarch.plugins")
    except TypeError:
        entries = metadata.entry_points().get("devarch.plugins", [])  # type: ignore[assignment]
    for entry in entries:
        infos.append(PluginInfo(name=entry.name, module=entry.value))
    return infos

