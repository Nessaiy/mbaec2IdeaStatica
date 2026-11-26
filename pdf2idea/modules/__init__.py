from __future__ import annotations

from typing import Dict, List

from .base import ModuleParser
from .mbaec_s601 import MbaecS601

_MODULES: List[ModuleParser] = [MbaecS601()]


def all_modules() -> List[ModuleParser]:
    return list(_MODULES)


def get_module(module_id: str) -> ModuleParser:
    for m in _MODULES:
        if m.id == module_id:
            return m
    raise KeyError(f"Unbekanntes Modul: {module_id}")
