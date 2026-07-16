"""Tektonik: kommen die Gebirge irgendwoher?

Die Behauptung dieses Umbaus ist nicht "die Karte sieht huebscher aus", sondern
**Gebirge sind Ketten entlang von Plattengrenzen**. Das ist eine messbare Aussage,
also wird sie hier als **Verteilung ueber viele Seeds** geprueft, nicht an einem
handverlesenen Fall: ein einzelner Seed beweist nur sein eigenes Glueck.

Gemessen wird am ``relief`` (Hoehe ueber der eigenen Krustenbasis), nicht an der Hoehe
ueber dem Meeresspiegel — genau wie die Karte selbst misst. Der Meeresspiegel schwimmt
mit dem Verhaeltnis von Kontinent zu Ozean; an ihm gemessen gilt ein blosser
Kontinentalsockel ueber tiefem Meer als "Gebirge", und der Test wuerde eine Kette sehen,
wo nur eine Hochebene liegt.
"""

from __future__ import annotations

import dataclasses
import itertools

import numpy as np
from worldsim.config import DEFAULT_MAP_CONFIG
from worldsim.driver import simulate
from worldsim.geo.terrain import (
    HILL_RELIEF,
    MAP_HEIGHT,
    MAP_WIDTH,
    PEAK_RELIEF,
    TRENCH_RELIEF,
    Terrain,
    build_terrain,
)

SEEDS = range(1, 31)
MIN_CHAIN = 6  # so viele zusammenhaengende Zellen heissen "Kette"


def _peaks(terrain: Terrain) -> np.ndarray:
    """Gebirgszellen: Land, das sich ueber seine eigene Kruste hebt."""
    return (terrain.elevation >= terrain.sea_level) & (terrain.relief >= PEAK_RELIEF)


def _ridges(terrain: Terrain) -> np.ndarray:
    """Gehobenes Land ueberhaupt (Huegel und Gebirge)."""
    return (terrain.elevation >= terrain.sea_level) & (terrain.relief >= HILL_RELIEF)


def _trenches(terrain: Terrain) -> np.ndarray:
    """Grabenzellen: OZEANboden, der unter seine eigene Kruste gerissen wurde.

    Ozeanisch ist Teil der Definition: ein Rift auf Kontinentalkruste reisst aehnlich
    tief, ist aber ein gefluteter Grabenbruch (Binnenmeer), kein Tiefseegraben.
    """
    return (
        (terrain.elevation < terrain.sea_level)
        & terrain.oceanic
        & (terrain.relief <= TRENCH_RELIEF)
    )


def _largest_component(mask: np.ndarray) -> int:
    """Groesste zusammenhaengende Flaeche (8er-Nachbarschaft) — eine Kette haengt zusammen."""
    seen = np.zeros_like(mask, dtype=bool)
    height, width = mask.shape
    best = 0
    for start in itertools.product(range(height), range(width)):
        if not mask[start] or seen[start]:
            continue
        stack, size = [start], 0
        seen[start] = True
        while stack:
            row, col = stack.pop()
            size += 1
            for drow, dcol in itertools.product((-1, 0, 1), repeat=2):
                nb = (row + drow, col + dcol)
                if 0 <= nb[0] < height and 0 <= nb[1] < width and mask[nb] and not seen[nb]:
                    seen[nb] = True
                    stack.append(nb)
        best = max(best, size)
    return best


def _border_mask(plate_of: np.ndarray) -> np.ndarray:
    """Zellen, die an eine andere Platte grenzen."""
    border = np.zeros(plate_of.shape, dtype=bool)
    vertical = plate_of[:-1, :] != plate_of[1:, :]
    horizontal = plate_of[:, :-1] != plate_of[:, 1:]
    border[:-1, :] |= vertical
    border[1:, :] |= vertical
    border[:, :-1] |= horizontal
    border[:, 1:] |= horizontal
    return border


def _gap_to_border(terrain: Terrain, mask: np.ndarray) -> float | None:
    """Median-Abstand der markierten Zellen zur naechsten Plattengrenze (in Zellen)."""
    cells = np.argwhere(mask).astype(float)
    borders = np.argwhere(_border_mask(np.asarray(terrain.plate_of))).astype(float)
    if not len(cells):
        return None
    return float(
        np.median(
            np.hypot(
                cells[:, 0][:, None] - borders[:, 0][None, :],
                (cells[:, 1][:, None] - borders[:, 1][None, :]) / 2.0,  # Zelle ist 2:1 hoch
            ).min(axis=1)
        )
    )


def test_land_fraction_is_calibrated() -> None:
    """Der Meeresspiegel trifft jeden Seed: 25-35 % Land — keine Wasserwelt, keine Wueste."""
    shares = [100.0 * build_terrain(seed).land_fraction for seed in SEEDS]
    assert all(25.0 <= share <= 35.0 for share in shares), (min(shares), max(shares))


def test_plates_carry_both_kinds() -> None:
    """Jede Welt hat kontinentale UND ozeanische Platten — sonst gibt es keine Subduktion."""
    for seed in SEEDS:
        kinds = {plate.oceanic for plate in build_terrain(seed).plates}
        assert kinds == {True, False}, seed


def test_plains_stay_plains() -> None:
    """Die Gegenprobe zum alten Fehler: ein Kontinentalsockel ist kein Gebirge.

    Die Ebenen liegen auf ihrer Kruste (Relief um null). Frueher mass die Karte die Hoehe
    ueber dem Meeresspiegel — der aber schwimmt, und in Welten mit wenig Kontinent sank er
    so tief, dass der blosse Sockel als Gebirge galt: einzelne Seeds waren zu 95 % "Berg".
    Bergland muss die Minderheit des Landes bleiben, in JEDER Welt.
    """
    shares = []
    for seed in SEEDS:
        terrain = build_terrain(seed)
        land = terrain.elevation >= terrain.sea_level
        shares.append(100.0 * _peaks(terrain).sum() / max(int(land.sum()), 1))

    assert float(np.median(shares)) < 25.0, np.median(shares)
    assert max(shares) < 50.0, max(shares)  # keine Welt besteht ueberwiegend aus Gebirge


def test_mountains_sit_on_plate_boundaries() -> None:
    """Der Kern der Behauptung: Gebirge stehen an Plattengrenzen, nicht irgendwo.

    Gemessen als Median-Abstand jeder Bergzelle zur naechsten Grenzzelle. Waeren die Berge
    blosses Rauschen, laege er bei mehreren Zellen; die Tektonik drueckt ihn unter eine.
    """
    terrains = [build_terrain(seed) for seed in SEEDS]
    gaps = [g for t in terrains if (g := _gap_to_border(t, _peaks(t))) is not None]

    assert len(gaps) >= 0.8 * len(SEEDS)  # die allermeisten Welten haben ueberhaupt Berge
    assert float(np.median(gaps)) < 1.5, np.median(gaps)


def test_worlds_are_shaped_and_most_carry_a_peak_chain() -> None:
    """Ketten, nicht Flecken — und beide Hoehenquellen tun, was sie sollen.

    Huegel liegen auf der Skala des Rauschens: fast jede Welt ist gewellt. Gipfelketten
    liegen auf der Skala der Tektonik: sie stehen nur, wo Platten konvergieren. Dass ein
    kleiner Rest gar keine hat, ist kein Fehler — eine Welt aus lauter Scherungs- und
    Divergenzgrenzen HAT keine Orogenese, und die Karte soll das zeigen, nicht kaschieren.
    """
    ridges = [_largest_component(_ridges(build_terrain(s))) >= MIN_CHAIN for s in SEEDS]
    peaks = [_largest_component(_peaks(build_terrain(s))) >= MIN_CHAIN for s in SEEDS]

    assert float(np.mean(ridges)) >= 0.95, np.mean(ridges)
    assert float(np.mean(peaks)) >= 0.90, np.mean(peaks)


def test_subduction_digs_a_trench() -> None:
    """Wo eine Platte abtaucht, reisst sie einen Graben — unter die eigene Kruste.

    Die scharfe Fassung: der **tiefste Punkt** einer Welt ist nie irgendwo. Er liegt auf
    ozeanischer Kruste, an einer Plattengrenze — dort, wo sie untertaucht.
    """
    trenched = 0
    for seed in SEEDS:
        terrain = build_terrain(seed)
        plate_of = np.asarray(terrain.plate_of)
        oceanic = terrain.oceanic

        deepest = np.unravel_index(np.argmin(terrain.elevation), terrain.elevation.shape)
        assert oceanic[deepest], seed
        # ... und an einer Plattengrenze. Gemessen als ABSTAND zur Naht, nicht als
        # 1-Zellen-Bandmaske: der Graben liegt seewaerts der Naht (Profil um u=0.28), und
        # auf der breiten 2:1-Karte loest die feinere Spaltenaufloesung diesen Versatz auf —
        # der tiefste Punkt faellt dann gelegentlich eine Spalte neben das Grenzband
        # (gemessen ueber 30 Seeds: schlimmstenfalls 0.5 Zellen), ist aber unverkennbar der
        # Graben. Dieselbe 1.5-Zellen-Schranke wie fuer die Grabenzellen unten.
        deepest_mask = np.zeros(terrain.elevation.shape, dtype=bool)
        deepest_mask[deepest] = True
        assert (_gap_to_border(terrain, deepest_mask) or 0.0) < 1.5, seed

        trench = _trenches(terrain)
        if not trench.any():
            continue
        trenched += 1
        assert oceanic[trench].mean() >= 0.9, seed              # Graeben liegen im Ozean
        assert _border_mask(plate_of)[trench].mean() > 0.5, seed  # ... an einer Grenze
        assert (_gap_to_border(terrain, trench) or 0.0) < 1.5, seed

    assert trenched >= 0.9 * len(SEEDS), trenched


def test_tectonics_puts_the_mountains_at_the_boundaries() -> None:
    """Der Gegenbeweis zu "das Rauschen haette das auch hingekriegt".

    Ohne Tektonik (``mountain_strength = 0``) bleiben nur Plattenbasis und fBm. Das
    Rauschen allein hebt fast nirgends etwas ueber die Gipfelschwelle — und wo es doch
    einmal reicht, liegt das Ergebnis nicht an einer Grenze, sondern irgendwo.
    """
    def terrain_without_tectonics(seed: int) -> Terrain:
        cfg = dataclasses.replace(DEFAULT_MAP_CONFIG, mountain_strength=0.0)
        return build_terrain(seed, MAP_WIDTH, MAP_HEIGHT, cfg)

    with_tectonics = [_largest_component(_peaks(build_terrain(s))) for s in SEEDS]
    without = [_largest_component(_peaks(terrain_without_tectonics(s))) for s in SEEDS]

    assert float(np.median(with_tectonics)) >= MIN_CHAIN, np.median(with_tectonics)
    assert max(without) < MIN_CHAIN, max(without)  # ohne Tektonik: nirgends eine Kette


def test_map_cannot_bend_the_history() -> None:
    """Die Geografie FORMT die Geschichte — aber sie zu zeichnen ruehrt sie nicht an.

    Seit Schritt 2 ist die Karte kanonisch: der Worldgen leitet Tragfaehigkeit, Erze und
    Grenzen aus ihr ab, die Simulation laeuft AUF ihr. Gepinnt wird darum nicht mehr 'die
    Karte ist kosmetisch', sondern die Read-only-Invariante der Schicht: ``build_terrain``
    ist eine reine Funktion des Seeds (zieht KEINEN Master-RNG, mutiert die Welt nicht),
    also verschiebt das Bauen der Karte fuers Rendering keinen einzigen semantischen Zug —
    dieselbe Geografie speist die Historie, aber das Zeichnen kann sie nicht biegen.
    """
    def trace(seed: int) -> list[tuple[int, str]]:
        _, log = simulate(seed=seed, years=80)
        return [(e.year, e.kind.name) for e in log]

    before = trace(7)
    for seed in SEEDS:  # die Karte ausgiebig bauen ...
        build_terrain(seed)
    assert trace(7) == before  # ... aendert an der Historie nichts
