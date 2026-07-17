"""geo — die kanonische Geografie der Welt: Tektonik, Klima, Hydrologie.

**Basisschicht** (haengt nur an ``config`` und ``rng``, plus numpy/opensimplex): sie
liegt unter ``models``/``systems``/``driver``, damit **beide** Seiten dieselbe Geografie
sehen — der Worldgen leitet die Simulations-Eigenschaften der Regionen daraus ab
(:func:`derive_regions`), und die Praesentation rendert dasselbe Feld. Genau EINE Quelle
der Wahrheit ueber Hoehe, Klima, Biome und Wasser (Konzept Schritt 2).

Bis hierher war die Geografie kosmetisch (in ``presentation``); jetzt ist sie kanonisch.
Sie bleibt eine reine, gecachte Funktion des Seeds — nie pro Tick berechnet.
"""

from __future__ import annotations

from worldsim.geo.climate import Biome, Climate, build_climate, latitudes
from worldsim.geo.derive import RegionGeography, derive_regions
from worldsim.geo.hydrology import Hydrology, build_hydrology
from worldsim.geo.terrain import (
    HILL_RELIEF,
    MAP_HEIGHT,
    MAP_WIDTH,
    PEAK_RELIEF,
    TRENCH_RELIEF,
    Plate,
    Terrain,
    build_terrain,
)

__all__ = [
    "HILL_RELIEF",
    "MAP_HEIGHT",
    "MAP_WIDTH",
    "PEAK_RELIEF",
    "TRENCH_RELIEF",
    "Biome",
    "Climate",
    "Hydrology",
    "Plate",
    "RegionGeography",
    "Terrain",
    "build_climate",
    "build_hydrology",
    "build_terrain",
    "derive_regions",
    "latitudes",
]
