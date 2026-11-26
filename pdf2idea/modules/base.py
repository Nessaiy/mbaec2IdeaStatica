from __future__ import annotations

from typing import Callable, Optional

from ..model import ParseResult

Progress = Optional[Callable[[int, int], None]]


class ModuleParser:
    """Basisklasse. Fuer ein neues Baustatik-Modul: Unterklasse anlegen,
    parse() implementieren und in modules/__init__.py registrieren."""

    id = ""
    label = ""

    def parse(self, pdf_path: str, progress: Progress = None) -> ParseResult:
        raise NotImplementedError
