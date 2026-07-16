"""derive — die Bruecke von der Geografie zu den Simulations-Eigenschaften der Regionen.

Schritt 2 des Konzepts: **die Simulation laeuft AUF der Geografie, nicht daneben.** Der
Worldgen zog die Region-Eigenschaften (Tragfaehigkeit, Eisen, Lage) frueher blind aus dem
RNG — hier werden sie stattdessen aus der bei :mod:`worldsim.geo` erzeugten Geografie
ABGELEITET. Kein Anpassungs-Algorithmus, keine Vorausplanung: die bestehenden adaptiven
Systeme (Demografie, Produktion) reagieren ohnehin auf Nahrung und Ressourcen — es genuegt,
ihre EINGABEN geografisch zu machen, dann konzentriert sich die Bevoelkerung von selbst auf
das gute Land.

Vier Ableitungen, alle aus demselben Hoehen-/Klima-/Wasserfeld:

1. **Regionen platzieren.** ``num_regions`` Zentren werden per *farthest point* ueber die
   Landzellen gestreut (das erste Zentrum auf die fruchtbarste Zelle, jedes weitere so weit
   wie moeglich von den bisherigen) — deterministisch, ohne Wuerfel. So bekommt jeder
   Kontinent Regionen im Verhaeltnis seiner Landflaeche, und keine zwei Zentren klumpen.
2. **Tragfaehigkeit** je Region = Summe der Zell-Fruchtbarkeit ihres Landes. Fruchtbarkeit
   folgt dem Biom (Grasland/Wald hoch, Wueste/Eis/Fels niedrig), dem Wasserzugang (Fluss,
   See, Kueste heben sie) und der Hoehe (Hochland senkt sie). Fruchtbares Tiefland am
   Wasser traegt viel, Wueste und Hochgebirge wenig.
3. **Ressourcen** aus dem Terrain: Eisen dort, wo genug Huegel/Berge stehen; Gold selten,
   nur in den wenigen gebirgigsten Regionen (Erz sitzt im Fels). So wird der Ressourcenkrieg
   geografisch — man kaempft um das fruchtbare Tal oder die Eisenberge.
4. **Nachbarschaft** aus der Voronoi-Zerlegung des GESAMTEN Gitters (Land wie Meer): zwei
   Regionen grenzen aneinander, wenn ihre Zellen sich beruehren. Dieselbe Zerlegung, die die
   Karte zeichnet — Sim-Adjazenz und Karten-Territorium sind damit **dieselbe** Sache, und
   ein schmaler Meeresarm zwischen zwei Kuestenregionen bleibt ueberquerbar (die Zellen der
   Kuestenregionen beruehren sich ueber dem Wasser), waehrend der offene Ozean trennt.

Rein deterministisch: keine Zufallsziehung, nur Numerik ueber dem gecachten Geografie-Feld
(genau wie die Hydrologie — Wasser wuerfelt nicht, es laeuft bergab). Der Worldgen ruft dies
**einmal** je Welt auf; die Systeme lesen danach nur noch die abgeleiteten Region-Felder.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from worldsim.config import DEFAULT_MAP_CONFIG, Config, MapConfig
from worldsim.geo.climate import Biome
from worldsim.geo.hydrology import build_hydrology
from worldsim.geo.terrain import HILL_RELIEF, MAP_HEIGHT, MAP_WIDTH, PEAK_RELIEF

__all__ = ["RegionGeography", "derive_regions"]

# Orthogonale Nachbarn fuer Kueste und Adjazenz (4er — ein sauberer Saum).
_ORTHO: tuple[tuple[int, int], ...] = ((-1, 0), (1, 0), (0, -1), (0, 1))


@dataclass(frozen=True)
class RegionGeography:
    """Die aus der Geografie abgeleiteten Simulations-Eigenschaften je Region.

    Reine Daten (plain Python), die der Worldgen in ``Region``-Objekte giesst. Alle
    Sequenzen sind ueber den Region-Index 0..num_regions-1 ausgerichtet.
    """

    coords: tuple[tuple[float, float], ...]      # Zentrum in [0,1)^2 (wie ``Region.coord``)
    food_capacity: tuple[float, ...]             # Tragfaehigkeit (Getreide-Basis)
    iron_rich: tuple[bool, ...]                  # genug Huegel/Berge ⇒ Eisen
    gold_rich: tuple[bool, ...]                  # eine der wenigen gebirgigsten ⇒ Gold
    adjacency: tuple[tuple[int, ...], ...]       # Region-Index ⇒ Nachbar-Indizes (sortiert)
    capital_rank: tuple[int, ...]                # Region-Indizes, bestes Startland zuerst


def _biome_fertility(cfg: Config) -> dict[Biome, float]:
    """Baue die Biom→Grundfruchtbarkeit-Tabelle aus den (namens-verschluesselten) Gewichten.

    Die Gewichte leben in :class:`Config` als ``(Biom-Name, Wert)``-Paare — nicht nach dem
    ``Biome``-Enum verschluesselt, weil ``config`` unter ``geo`` liegt und das Enum nicht
    kennen darf (Einbahn-Schichten). Hier wird der Name zurueck ins Enum aufgeloest.
    """
    return {Biome[name]: value for name, value in cfg.fertility_by_biome}


def _cell_fertility(
    hydro, is_land: np.ndarray, cfg: Config
) -> np.ndarray:
    """Fruchtbarkeit je Zelle (0 auf Wasser): Biom x Wasserzugang x Hoehe.

    Das ist der Kern von Aufgabe 2 — fruchtbares Tiefland am Wasser hoch, Wueste/Eis/
    Hochgebirge niedrig. Drei benannte Faktoren, kein undurchsichtiger Index.
    """
    climate = hydro.climate
    table = _biome_fertility(cfg)
    height, width = is_land.shape

    fert = np.zeros((height, width), dtype=float)
    for biome, base in table.items():
        fert[climate.biome == biome] = base

    # Wasserzugang: Fluss, See oder Kuestensaum (Landzelle an offener See). Fruchtbares
    # Land AM Wasser traegt am meisten — die Wiege der Zivilisation.
    sea = ~is_land
    coast = np.zeros((height, width), dtype=bool)
    padded = np.pad(sea, 1, constant_values=False)
    for drow, dcol in _ORTHO:
        coast |= padded[1 + drow : 1 + drow + height, 1 + dcol : 1 + dcol + width]
    water_access = is_land & (np.asarray(hydro.river) | np.asarray(hydro.lake) | coast)
    fert *= 1.0 + cfg.fertility_water_bonus * water_access

    # Hoehe: Hochland ist muehsamer (duenne Boeden, kurze Vegetationszeit). Ueber der
    # typischen Landhoehe (climate.altitude) linear gedaempft, mit einem Boden.
    rise = np.clip(np.asarray(climate.altitude), 0.0, None)
    altitude_factor = np.clip(
        1.0 - cfg.fertility_altitude_penalty * rise, cfg.fertility_altitude_floor, 1.0
    )
    fert *= altitude_factor
    return np.where(is_land, fert, 0.0)


def _place_centers(
    is_land: np.ndarray, fertility: np.ndarray, num_regions: int
) -> list[int]:
    """Streue ``num_regions`` Regionzentren per farthest-point ueber die Landzellen.

    Das erste Zentrum auf die fruchtbarste Landzelle (die Wiege), jedes weitere auf die
    Landzelle mit dem groessten Abstand zu allen bisherigen — so verteilen sich die Zentren
    ueber ALLE Kontinente im Verhaeltnis ihrer Flaeche und klumpen nie. Deterministisch:
    Gleichstaende bricht der kleinste (Zeile, Spalte)-Index (``argmax`` nimmt den ersten).
    """
    width = is_land.shape[1]
    land_flat = np.flatnonzero(is_land.ravel())  # aufsteigend ⇒ stabile Reihenfolge
    rows = (land_flat // width).astype(float)
    cols = (land_flat % width).astype(float)

    # Erstes Zentrum: fruchtbarste Landzelle (Gleichstand ⇒ kleinster Flach-Index).
    fert_land = fertility.ravel()[land_flat]
    first = int(np.argmax(fert_land))
    chosen = [first]
    # Abstand jeder Landzelle zum naechsten gewaehlten Zentrum (quadriert genuegt).
    min_d2 = (rows - rows[first]) ** 2 + (cols - cols[first]) ** 2
    while len(chosen) < num_regions and len(chosen) < land_flat.size:
        nxt = int(np.argmax(min_d2))
        chosen.append(nxt)
        d2 = (rows - rows[nxt]) ** 2 + (cols - cols[nxt]) ** 2
        min_d2 = np.minimum(min_d2, d2)
    return [int(land_flat[i]) for i in chosen]  # Flach-Indizes der Zentren im Gitter


def _voronoi(centers: list[int], width: int, height: int) -> np.ndarray:
    """Ordne JEDER Gitterzelle (Land wie Meer) das naechste Zentrum zu ⇒ (H, W) Region-Index.

    Dieselbe normalisierte Euklid-Metrik wie ``worldmap._nearest_region`` (keine Aspekt-
    korrektur), damit Sim-Region und Karten-Territorium exakt dieselbe Zerlegung sind.
    """
    crow = np.array([c // width for c in centers], dtype=float)
    ccol = np.array([c % width for c in centers], dtype=float)
    rows = np.arange(height, dtype=float)[:, None]
    cols = np.arange(width, dtype=float)[None, :]
    # (H, W, R) waere gross; iterativ das Minimum halten ist speicherarm und deterministisch.
    best = np.zeros((height, width), dtype=int)
    best_d2 = np.full((height, width), np.inf)
    for idx in range(len(centers)):
        d2 = (rows - crow[idx]) ** 2 + (cols - ccol[idx]) ** 2
        closer = d2 < best_d2
        best = np.where(closer, idx, best)
        best_d2 = np.where(closer, d2, best_d2)
    return best


def _adjacency(region_of: np.ndarray, num_regions: int) -> tuple[tuple[int, ...], ...]:
    """Nachbar-Regionen aus der Zell-Kontiguitaet (Land wie Meer) ⇒ zusammenhaengender Graph.

    Zwei Regionen grenzen aneinander, wenn irgendwo zwei orthogonal benachbarte Zellen zu
    ihnen gehoeren. Weil das ganze Gitter zerlegt ist, ist der Graph garantiert
    zusammenhaengend — kein Kontinent faellt aus dem Handels-/Kriegsnetz.
    """
    neighbours: list[set[int]] = [set() for _ in range(num_regions)]
    vert = region_of[:-1, :] != region_of[1:, :]
    horz = region_of[:, :-1] != region_of[:, 1:]
    for row, col in zip(*np.where(vert), strict=True):
        a, b = int(region_of[row, col]), int(region_of[row + 1, col])
        neighbours[a].add(b)
        neighbours[b].add(a)
    for row, col in zip(*np.where(horz), strict=True):
        a, b = int(region_of[row, col]), int(region_of[row, col + 1])
        neighbours[a].add(b)
        neighbours[b].add(a)
    return tuple(tuple(sorted(n)) for n in neighbours)


def derive_regions(
    seed: int, cfg: Config, map_cfg: MapConfig = DEFAULT_MAP_CONFIG
) -> RegionGeography:
    """Leite alle geografischen Region-Eigenschaften aus der Welt-Geografie ab.

    Reine, deterministische Funktion von ``(seed, cfg, map_cfg)``. Baut die (gecachte)
    Hydrologie — und damit Klima und Terrain — und aggregiert sie je Region.
    """
    hydro = build_hydrology(seed, MAP_WIDTH, MAP_HEIGHT, map_cfg)
    terrain = hydro.terrain
    elevation = np.asarray(terrain.elevation)
    is_land = elevation >= terrain.sea_level
    relief = np.asarray(terrain.relief)
    height, width = elevation.shape

    fertility = _cell_fertility(hydro, is_land, cfg)
    centers = _place_centers(is_land, fertility, cfg.num_regions)
    region_of = _voronoi(centers, width, height)

    hilly = is_land & (relief >= HILL_RELIEF)
    peaky = is_land & (relief >= PEAK_RELIEF)
    river = np.asarray(hydro.river)
    lake = np.asarray(hydro.lake)
    sea = ~is_land
    coast_land = np.zeros((height, width), dtype=bool)
    padded_sea = np.pad(sea, 1, constant_values=False)
    for drow, dcol in _ORTHO:
        coast_land |= padded_sea[1 + drow : 1 + drow + height, 1 + dcol : 1 + dcol + width]
    coast_land &= is_land

    coords: list[tuple[float, float]] = []
    food_capacity: list[float] = []
    iron_rich: list[bool] = []
    peak_count: list[int] = []
    capital_score: list[float] = []
    for r, center in enumerate(centers):
        cells = region_of == r
        land_cells = cells & is_land
        n_land = int(land_cells.sum())
        coords.append(((center % width + 0.5) / width, (center // width + 0.5) / height))
        food_capacity.append(float(fertility[land_cells].sum()) * cfg.fertility_capacity_scale)
        hill_share = float(hilly[land_cells].sum()) / max(n_land, 1)
        iron_rich.append(hill_share >= cfg.iron_hill_share)
        peak_count.append(int(peaky[cells].sum()))
        # Startland-Guete: mittlere Fruchtbarkeit, plus Bonus fuer Kueste und Suesswasser.
        mean_fert = float(fertility[land_cells].sum()) / max(n_land, 1)
        has_coast = bool((coast_land & cells).any())
        has_water = bool(((river | lake) & cells).any())
        capital_score.append(
            mean_fert
            + cfg.capital_coast_bonus * has_coast
            + cfg.capital_water_bonus * has_water
        )

    # Gold ist selten: nur die wenigen gebirgigsten Regionen (Erz sitzt im Fels), und nur,
    # wo ueberhaupt ein Gipfel steht. Deterministisch: nach Gipfelzahl, Gleichstand ⇒ Index.
    n_gold = round(cfg.num_regions * cfg.gold_region_fraction)
    ranked_gold = sorted(range(cfg.num_regions), key=lambda r: (-peak_count[r], r))
    gold_set = {r for r in ranked_gold[:n_gold] if peak_count[r] > 0}
    gold_rich = tuple(r in gold_set for r in range(cfg.num_regions))

    # Startland-Rangfolge (bestes zuerst); die Auswahl der Hauptstaedte (mit Streuung)
    # trifft der Worldgen.
    capital_rank = tuple(sorted(range(cfg.num_regions), key=lambda r: (-capital_score[r], r)))

    return RegionGeography(
        coords=tuple(coords),
        food_capacity=tuple(food_capacity),
        iron_rich=tuple(iron_rich),
        gold_rich=gold_rich,
        adjacency=_adjacency(region_of, cfg.num_regions),
        capital_rank=capital_rank,
    )
