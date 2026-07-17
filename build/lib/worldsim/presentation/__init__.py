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

from worldsim.geo import (
    Biome,
    Climate,
    Hydrology,
    Plate,
    Terrain,
    build_climate,
    build_hydrology,
    build_terrain,
    latitudes,
)
from worldsim.presentation.components import (
    bilanz_tafel,
    ereignis_text,
    faktoren_inline,
    faktoren_text,
    feed_tafel,
    kausal_zeile,
    tasten_zeile,
    zeitalter_regel,
)
from worldsim.presentation.explore import explore
from worldsim.presentation.palette import ROSE_PINE_MOON, Palette
from worldsim.presentation.query import warum_entitaet, warum_event
from worldsim.presentation.render import Steuerung, replay
from worldsim.presentation.static import render_chronik
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
from worldsim.presentation.watch import watch, weltlauf
from worldsim.presentation.worldmap import (
    MAP_VIEWS,
    POLITICAL_VIEW,
    TERRAIN_VIEW,
    render_map,
)

__all__ = [
    "MAP_VIEWS",
    "POLITICAL_VIEW",
    "ROSE_PINE_MOON",
    "TERRAIN_VIEW",
    "Biome",
    "Climate",
    "Hydrology",
    "Palette",
    "Plate",
    "Steuerung",
    "Terrain",
    "ViewState",
    "VisualEffect",
    "VisualKind",
    "bevoelkerung_verlauf",
    "bilanz_tafel",
    "build_climate",
    "build_hydrology",
    "build_terrain",
    "ereignis_text",
    "ereignisse_pro_jahr",
    "event_to_visual",
    "explore",
    "faktoren_inline",
    "faktoren_text",
    "feed_tafel",
    "kausal_zeile",
    "latitudes",
    "macht_verlauf",
    "render_chronik",
    "render_map",
    "replay",
    "sparkline",
    "tasten_zeile",
    "visuelle_historie",
    "warum_entitaet",
    "warum_event",
    "watch",
    "weltlauf",
    "zeitalter_regel",
    "zusammenfassung_zeilen",
]
