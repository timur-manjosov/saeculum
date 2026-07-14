"""hydrology — Fluesse, Seen, Muendungen: das Wasser, das ueber die fertige Welt laeuft.

Der dritte Schritt derselben Kette. Die Tektonik hat die Berge gebaut, das Klima hat
entschieden, wo es regnet — hier laeuft der Regen bergab, und man sieht die beiden
vorigen Schritte an ihm: **ein Fluss ist ein Beweis**. Er entspringt dort, wo Hoehe und
Feuchte zusammentreffen; er sammelt sich in den Taelern, die die Erosion geschnitten
hat; er umgeht das Gebirge, das im Weg steht; er endet im Meer.

Nichts davon ist eine Regel. Es gibt keine Zeile, die "zeichne einen Fluss von den Bergen
zum Meer" sagt. Es gibt nur:

1. **Abfluss** — jede Zelle fliesst zum tiefsten Nachbarn (:mod:`worldsim.presentation.flow`);
2. **Akkumulation** — jede Zelle sammelt den **Niederschlag** aller Zellen, die zu ihr
   abfliessen. Niederschlag heisst: was die Luft hier fallen laesst, nicht was sie noch
   traegt (:func:`rain.moisture_and_rain`) — und fallen laesst sie ihn am Luvhang der
   Gebirge. Nur deshalb entspringen die Fluesse oben;
3. **eine Schwelle** — genug gesammelter Abfluss ⇒ Fluss (``river_threshold``).

Alles Weitere faellt heraus, ohne gesucht zu werden: dass Fluesse sich zu **groesseren
Stroemen vereinigen** (bergab summiert sich der Durchfluss), dass ein **See** in einer
Senke steht (dorthin laeuft Wasser, aber nicht hinaus — die Depressionsfuellung findet
ihn), dass eine **Muendung** dort liegt, wo viel Durchfluss die Kueste trifft — und, am
schoensten, dass ein Fluss die **Wueste** quert, ohne dass ihn dort ein Tropfen speiste:
gemessen traegt eine Wuestenfluss-Zelle im Median 96 % Wasser, das anderswo gefallen ist.
Das ist der Nil, und niemand hat ihn gebaut.

Wie Terrain und Klima: einmal je Welt gebaut (gecacht), nie pro Tick, read-only ueber der
Simulation, kein semantischer Zufall — hier sogar **gar kein** Zufall, denn Wasser
wuerfelt nicht, es laeuft bergab.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from worldsim.config import DEFAULT_MAP_CONFIG, MapConfig
from worldsim.presentation.climate import Climate, build_climate
from worldsim.presentation.flow import (
    NEIGHBOURS,
    accumulate,
    downstream_links,
    fill_depressions,
)
from worldsim.presentation.terrain import MAP_HEIGHT, MAP_WIDTH, Terrain

__all__ = ["Hydrology", "build_hydrology"]

# Ein See ist eine Senke, in der wirklich Wasser STEHT. Beurteilt wird das **je Becken**,
# nicht je Zelle: eine Senke zaehlt als See, wenn ihr tiefster Punkt tiefer liegt als
# ``_LAKE_MIN_DEPTH``; dann gehoert das ganze Becken dazu, bis hinauf zum Ufer.
#
# Eine Schranke je ZELLE waere das Naheliegende und ist falsch. Sie laesst jede Delle
# durchgehen, in der ein Fingerhut Wasser steht — und weil eine Ebene voll solcher Dellen
# ist, zerhackte sie ausgerechnet die Fluesse: der groesste Strom einer Testwelt lief als
# **Perlenschnur** aus abwechselnd Fluss- und Pfuetzenzellen ueber die flache Tundra.
# Gemessen: 95 der 126 "Seen" einer Welt waren flacher als 0.05.
_LAKE_MIN_DEPTH = 0.05
_PUDDLE = 0.005  # darunter ist die Fuellung blosses Rechenrauschen, keine Senke

# Groessenklassen, als Vielfache der Fluss-Schwelle. Sie geben dem Fluss seine BREITE:
# ein Bach ist eine duenne Linie, ein Strom eine dicke — abgeleitet aus der Akkumulation,
# nicht gesetzt.
# Ein STROM ist ein Fluss, der ein Mehrfaches der Schwelle traegt; und ein Delta setzt
# die Karte genau dort, wo ein solcher Strom das Meer erreicht — ein Zeichen, eine
# Schwelle. (Ein eigener Delta-Regler waere ein Knopf ohne eigene Bedeutung.)
# Gemessen ueber 60 Seeds: bei 2.5 traegt jede zweite Welt einen Strom und fast jede ein
# Delta; bei 4.0 waren Stroeme in drei von vier Welten schlicht abwesend.
STREAM_FACTOR = 2.5


@dataclass(frozen=True)
class Hydrology:
    """Das Wasser einer Welt — einmal je Seed gebaut, nie pro Tick."""

    flow: np.ndarray        # (H, W): akkumulierter Abfluss in "Zellen vollen Regens"
    downstream: np.ndarray  # (H, W) int: flacher Index der Abflusszelle (-1 = Meer/Ende)
    lake_depth: np.ndarray  # (H, W): wie hoch das Wasser in einer Senke steht (0 = keine)
    river: np.ndarray       # (H, W) bool: Landzelle mit Fluss
    lake: np.ndarray        # (H, W) bool: Landzelle unter einem See
    mouth: np.ndarray       # (H, W) bool: Meerzelle, in die ein grosser Strom muendet
    climate: Climate

    @property
    def terrain(self) -> Terrain:
        return self.climate.terrain

    def flows_to(self, row: int, col: int) -> tuple[int, int] | None:
        """Richtung des Abflusses als ``(drow, dcol)`` — die Linie, die der Fluss zieht."""
        width = self.flow.shape[1]
        target = int(self.downstream[row, col])
        if target < 0:
            return None
        return target // width - row, target % width - col


def _lakes(depth: np.ndarray, min_depth: float) -> np.ndarray:
    """Senken ⇒ Seen. Ein Becken zaehlt ganz oder gar nicht.

    Die gefuellten Zellen zerfallen in zusammenhaengende Becken; ein Becken ist ein See,
    wenn irgendwo darin das Wasser tief genug steht. Dann gehoert es vollstaendig dazu —
    auch die flachen Randzellen, denn das Ufer eines Sees ist immer flach.
    """
    height, width = depth.shape
    hollow = depth > _PUDDLE
    lake = np.zeros((height, width), dtype=bool)
    seen = np.zeros((height, width), dtype=bool)

    for row in range(height):
        for col in range(width):
            if not hollow[row, col] or seen[row, col]:
                continue
            basin = [(row, col)]
            seen[row, col] = True
            queue = deque(basin)
            deepest = 0.0
            while queue:
                here_row, here_col = queue.popleft()
                deepest = max(deepest, float(depth[here_row, here_col]))
                for drow, dcol in NEIGHBOURS:
                    nrow, ncol = here_row + drow, here_col + dcol
                    if (
                        0 <= nrow < height
                        and 0 <= ncol < width
                        and hollow[nrow, ncol]
                        and not seen[nrow, ncol]
                    ):
                        seen[nrow, ncol] = True
                        basin.append((nrow, ncol))
                        queue.append((nrow, ncol))
            if deepest >= min_depth:
                for cell in basin:
                    lake[cell] = True
    return lake


def _mouths(
    flow: np.ndarray, is_sea: np.ndarray, river: np.ndarray, threshold: float
) -> np.ndarray:
    """Meerzellen, in die ein grosser Strom muendet — der Delta-Punkt der Kueste."""
    height, width = flow.shape
    mouth = np.zeros((height, width), dtype=bool)
    for row in range(height):
        for col in range(width):
            if not is_sea[row, col] or flow[row, col] < threshold:
                continue
            # Die Meerzelle traegt den Durchfluss, den ihr das Land gibt: sie ist genau
            # dann eine Muendung, wenn nebenan wirklich ein Fluss endet.
            mouth[row, col] = any(
                0 <= row + drow < height
                and 0 <= col + dcol < width
                and river[row + drow, col + dcol]
                for drow, dcol in NEIGHBOURS
            )
    return mouth


@lru_cache(maxsize=8)
def build_hydrology(
    seed: int,
    width: int = MAP_WIDTH,
    height: int = MAP_HEIGHT,
    cfg: MapConfig = DEFAULT_MAP_CONFIG,
) -> Hydrology:
    """Lass den Regen des Klimas ueber die Geologie laufen: Fluesse, Seen, Muendungen.

    Reine Funktion von ``(seed, width, height, cfg)`` und gecacht — sie laeuft **einmal**
    je Welt. Sie zieht keinen Zufall: die ganze Karte des Wassers steht schon in Hoehe
    und Feuchte, sie muss nur ausgerechnet werden.
    """
    climate = build_climate(seed, width, height, cfg)
    terrain = climate.terrain
    elevation = np.asarray(terrain.elevation)
    is_sea = elevation < terrain.sea_level

    drainage = fill_depressions(elevation, is_sea)
    downstream = downstream_links(drainage, is_sea)

    # Was den Fluss speist, ist der **Niederschlag** — nicht die Feuchte. Der Unterschied
    # ist der ganze Schritt (siehe :func:`climate._moisture`): die Feuchte sagt, was die
    # Luft noch traegt, der Niederschlag, was sie hier fallen laesst. Und fallen laesst
    # sie ihn am Luvhang der Gebirge. Deshalb — und nur deshalb — entspringen die Fluesse
    # oben: nicht weil Berge hoch sind, sondern weil auf ihnen der Regen faellt.
    precipitation = np.where(is_sea, 0.0, np.asarray(climate.rainfall))
    flow = accumulate(downstream, drainage.upstream_first, precipitation)

    lake_depth = np.where(is_sea, 0.0, drainage.depth(elevation))
    lake = _lakes(lake_depth, _LAKE_MIN_DEPTH)
    river = ~is_sea & ~lake & (flow >= cfg.river_threshold)
    mouth = _mouths(flow, is_sea, river, STREAM_FACTOR * cfg.river_threshold)

    downstream = downstream.reshape(height, width)
    for field in (flow, downstream, lake_depth, lake, river, mouth):
        field.setflags(write=False)  # gecacht ⇒ nicht mutieren
    return Hydrology(
        flow=flow,
        downstream=downstream,
        lake_depth=lake_depth,
        river=river,
        lake=lake,
        mouth=mouth,
        climate=climate,
    )
