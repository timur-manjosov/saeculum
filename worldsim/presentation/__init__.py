"""presentation — Farbe, Replay und Werkzeuge (Phase 6).

Die **erste** Schicht mit externen Runtime-Abhaengigkeiten (``rich``, ``numpy``,
``opensimplex``). Sie konsumiert ``World`` + ``EventLog`` strikt **read-only** und
enthaelt **keine** Simulationslogik: der headless Kern bleibt unveraendert
abhaengigkeitsfrei und weiss nichts von dieser Schicht (Einbahn-Abhaengigkeit).

Zwei Prinzipien tragen alles:
- Eine zentrale ``event_to_visual``-Abbildung treibt **beide** Ansichten
  (Live-Dashboard und Replay) — gleiche Optik per Konstruktion.
- Ein ``ViewState``-Reducer rekonstruiert den beobachtbaren Zustand allein aus dem
  Log (kein Re-Simulieren): Replay reproduziert die Historie konsistent.
"""

from worldsim.presentation.query import warum_entitaet, warum_event
from worldsim.presentation.render import Steuerung, live_dashboard, replay
from worldsim.presentation.stats import (
    bevoelkerung_verlauf,
    ereignisse_pro_jahr,
    macht_verlauf,
    sparkline,
    zusammenfassung_zeilen,
)
from worldsim.presentation.visual import (
    ViewState,
    VisualEffect,
    VisualKind,
    event_to_visual,
    visuelle_historie,
)
from worldsim.presentation.worldmap import biome_grid, render_map

__all__ = [
    "Steuerung",
    "ViewState",
    "VisualEffect",
    "VisualKind",
    "bevoelkerung_verlauf",
    "biome_grid",
    "ereignisse_pro_jahr",
    "event_to_visual",
    "live_dashboard",
    "macht_verlauf",
    "render_map",
    "replay",
    "sparkline",
    "visuelle_historie",
    "warum_entitaet",
    "warum_event",
    "zusammenfassung_zeilen",
]
