"""stats — End-of-Run-Statistik: Zeitreihen als ASCII-Sparklines + Zusammenfassung.

Reine, read-only Ableitung aus ``World`` + ``EventLog``. **Keine** Re-Simulation:
alle Zeitreihen werden aus den geloggten ``effects`` bzw. der Emissionsdichte
rekonstruiert (``numpy`` fuer die Aggregation). Die Sparkline selbst ist reiner
Stdlib-Text und daher ohne ``rich`` testbar.
"""

from __future__ import annotations

import numpy as np

from worldsim.config import Config
from worldsim.events import EventKind, EventLog
from worldsim.models import World
from worldsim.presentation.visual import ViewState
from worldsim.systems import bevoelkerung as gesamtbevoelkerung

__all__ = [
    "bevoelkerung_verlauf",
    "ereignisse_pro_jahr",
    "macht_verlauf",
    "sparkline",
    "zusammenfassung_zeilen",
]

# Acht Bloecke von leer bis voll — die klassische ASCII/Unicode-Sparkline-Rampe.
_BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float] | np.ndarray) -> str:
    """Verdichte eine Zahlenreihe zu einer Ein-Zeilen-Sparkline.

    Skaliert linear zwischen Minimum und Maximum. Leere Eingabe ⇒ leerer String;
    eine konstante Reihe ⇒ mittlere Bloecke (kein Nulldivisions-Ausreisser).
    """
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return ""
    lo = float(arr.min())
    hi = float(arr.max())
    if hi <= lo:
        return _BLOCKS[len(_BLOCKS) // 2] * arr.size
    norm = (arr - lo) / (hi - lo)
    idx = np.clip((norm * (len(_BLOCKS) - 1)).round().astype(int), 0, len(_BLOCKS) - 1)
    return "".join(_BLOCKS[i] for i in idx)


def ereignisse_pro_jahr(log: EventLog, years: int) -> np.ndarray:
    """Ereignisse je Jahr — die "Turbulenz" der Geschichte (exakt aus dem Log)."""
    counts = np.zeros(max(years, 1), dtype=int)
    for event in log:
        if 0 <= event.year < counts.size:
            counts[event.year] += 1
    return counts


def macht_verlauf(log: EventLog, years: int) -> np.ndarray:
    """Gesamt beanspruchtes Gebiet je Jahr — ein exakter Macht-/Ausdehnungs-Proxy.

    Rekonstruiert Feld-fuer-Feld aus den Besitz-``effects`` (``ViewState``), also
    exakt reproduzierbar. Am Jahresende wird die Summe der besetzten Felder notiert.
    """
    series = np.zeros(max(years, 1), dtype=int)
    view = ViewState()
    cursor = 0
    for year in range(series.size):
        while cursor < len(log) and log.get(cursor).year <= year:
            view.apply(log.get(cursor))
            cursor += 1
        series[year] = len(view.owner)
    return series


def bevoelkerung_verlauf(log: EventLog, cfg: Config, years: int) -> np.ndarray:
    """Gesamtbevoelkerung je Jahr — rekonstruiert aus geloggten Bevoelkerungs-Snapshots.

    Jede Nation startet bei ``initial_population`` (Gruendung) und wird bei jedem
    Event mit ``population``-Effekt (Meilenstein, Hunger, Schock) auf den geloggten
    Wert gesetzt; dazwischen haelt der letzte bekannte Stand. Eine wahrheitsgetreue,
    stufige Kurve aus dem Log (keine Interpolation erfundener Zwischenwerte).
    """
    series = np.zeros(max(years, 1), dtype=float)
    pop: dict[int, int] = {}
    cursor = 0
    for year in range(series.size):
        while cursor < len(log) and log.get(cursor).year <= year:
            event = log.get(cursor)
            if event.kind == EventKind.GRUENDUNG and event.subjects:
                pop.setdefault(event.subjects[0], cfg.initial_population)
            if event.kind == EventKind.ABSPALTUNG and len(event.subjects) > 1:
                pop.setdefault(event.subjects[1], cfg.initial_population)
            for eff in event.effects:
                if eff.field == "population" and isinstance(eff.after, int):
                    pop[eff.entity] = eff.after
            cursor += 1
        series[year] = float(sum(pop.values()))
    return series


def zusammenfassung_zeilen(world: World, log: EventLog, cfg: Config, years: int) -> list[str]:
    """Kompakte Klartext-Zusammenfassung am Laufende (ohne ``rich``, gut testbar)."""
    events = ereignisse_pro_jahr(log, years)
    macht = macht_verlauf(log, years)
    bevoelkerung = bevoelkerung_verlauf(log, cfg, years)

    top = sorted(
        world.polities.values(),
        key=lambda p: (len(p.territory), gesamtbevoelkerung(p)),
        reverse=True,
    )[:5]

    lines = [
        f"History of {years} years — {len(log)} events, "
        f"{len(world.polities)} surviving nations, {len(world.identities)} faiths.",
        f"  activity   {sparkline(events)}  (events/year, peak {int(events.max())})",
        f"  territory  {sparkline(macht)}  (claimed fields, final {int(macht[-1])})",
        f"  population {sparkline(bevoelkerung)}  (final {int(bevoelkerung[-1])})",
        "  strongest nations:",
    ]
    for pol in top:
        faith = world.identities.get(pol.identity_id) if pol.identity_id else None
        faith_name = faith.name if faith else "?"
        lines.append(
            f"    {pol.name:<12} territory {len(pol.territory):>2}  "
            f"pop {gesamtbevoelkerung(pol):>5}  tech {pol.tech_level}  faith {faith_name}"
        )
    return lines
