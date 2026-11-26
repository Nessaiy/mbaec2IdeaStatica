"""Logik der bildlichen Achsenzuordnung (ohne tkinter, damit testbar).

Der Nutzer klickt eine Achsenspitze (+ oder -) am IDEA-Bauteil und danach eine Achsenspitze (+ oder -) der Baustatik.
Daraus wird die Zuordnung 'Baustatik-Achse -> +/-IDEA-Achse' (Format wie in axes.py) abgeleitet:

    IDEA +Z  <->  Baustatik +x     ->  axes["x"] = "+z"
    IDEA -Z  <->  Baustatik +x     ->  axes["x"] = "-z"
    IDEA +Z  <->  Baustatik -x     ->  axes["x"] = "-z"      (zwei Minus ergeben wieder Plus)

Sind zwei Achsen zugeordnet, ergibt sich die dritte (Rechtssystem bleibt Rechtssystem, also keine Spiegelung)."""
from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from .axes import AXES, component_map_from_axes, determinant


def _sign(spec: str) -> int:
    return -1 if spec.startswith("-") else 1


class AxisPairs:
    def __init__(self, axes: Optional[Dict[str, str]] = None):
        self.pairs: Dict[str, str] = {}          # Baustatik-Achse (x|y|z) -> '+/-' IDEA-Achse
        self.derived: Set[str] = set()           # automatisch abgeleitete Baustatik-Achsen
        self.suggested = False
        if axes:
            self.set_all(axes, suggested=True)

    # --- Aufbau
    def set_all(self, axes: Dict[str, str], suggested: bool = False) -> None:
        self.pairs = {a: axes[a] for a in AXES if a in axes}
        self.derived = set()
        self.suggested = suggested

    def clear(self) -> None:
        self.pairs, self.derived, self.suggested = {}, set(), False

    def connect(self, idea: str, bs: str) -> None:
        """idea: z. B. '+z' (Achsenspitze am IDEA-Bauteil), bs: z. B. '-x' (Achsenspitze der Baustatik)."""
        self.suggested = False
        for k in self.derived:
            self.pairs.pop(k, None)
        self.derived = set()
        a_i, a_b = idea[-1], bs[-1]
        spec = ("+" if _sign(idea) * _sign(bs) > 0 else "-") + a_i
        for k, v in list(self.pairs.items()):            # jede IDEA-Achse nur einmal
            if k != a_b and v[-1] == a_i:
                del self.pairs[k]
        self.pairs[a_b] = spec
        self._derive()

    def _derive(self) -> None:
        if len(self.pairs) != 2:
            return
        rest_b = next(a for a in AXES if a not in self.pairs)
        used = {v[-1] for v in self.pairs.values()}
        rest_i = next(a for a in AXES if a not in used)
        for s in ("+", "-"):
            trial = dict(self.pairs)
            trial[rest_b] = s + rest_i
            if determinant(trial) == 1:
                self.pairs[rest_b] = s + rest_i
                self.derived.add(rest_b)
                return

    # --- Abfrage
    def complete(self) -> bool:
        return len(self.pairs) == 3

    def axes(self) -> Dict[str, str]:
        if not self.complete():
            raise ValueError("Es sind noch nicht alle drei Achsen zugeordnet.")
        return {a: self.pairs[a] for a in AXES}

    def component_map(self) -> Dict[str, str]:
        return component_map_from_axes(self.axes())

    def is_mirror(self) -> bool:
        return self.complete() and determinant(self.axes()) < 0

    def idea_marks(self) -> Dict[str, str]:
        """IDEA-Achsenspitze ('+z', '-x' ...) -> Beschriftung der zugehoerigen Baustatik-Achsenspitze ('+x' ...)."""
        out: Dict[str, str] = {}
        for a_b, spec in self.pairs.items():
            out[spec] = "+" + a_b
            out[("-" if spec[0] == "+" else "+") + spec[-1]] = "-" + a_b
        return out

    def bs_marks(self) -> Dict[str, str]:
        """Baustatik-Achsenspitze ('+x', '-x' ...) -> zugehoerige IDEA-Achsenspitze."""
        out: Dict[str, str] = {}
        for a_b, spec in self.pairs.items():
            out["+" + a_b] = spec
            out["-" + a_b] = ("-" if spec[0] == "+" else "+") + spec[-1]
        return out

    def lines(self) -> List[Tuple[str, str, str]]:
        """[(Baustatik-Achse, IDEA-Achse oder '?', Herkunft)] fuer die Anzeige."""
        out = []
        for a in AXES:
            if a in self.pairs:
                src = "abgeleitet" if a in self.derived else ("Vorschlag" if self.suggested else "gewählt")
                out.append((a, self.pairs[a].replace("-", "−").upper(), src))
            else:
                out.append((a, "?", ""))
        return out
