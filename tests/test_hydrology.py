"""Hydrologie: laeuft das Wasser dahin, wo es hingehoert — und aus dem richtigen Grund?

Die Behauptung dieses Schrittes ist nicht "es gibt jetzt Fluesse", sondern: ein Fluss ist
ein **Beweis**. Er entspringt, wo der Regen faellt (am Luvhang der Gebirge), er sammelt
sich in den Taelern, die die Erosion geschnitten hat, und er endet im Meer. Nirgends steht
eine Regel, die das anordnet — es faellt aus Hoehe, Wind und Schwerkraft heraus. Also wird
es hier auch so geprueft: als **Verteilung ueber viele Seeds**, nie an einer gebauten Welt.
"""

from __future__ import annotations

import numpy as np
from worldsim.config import DEFAULT_MAP_CONFIG as CFG
from worldsim.driver import simulate
from worldsim.geo.flow import NEIGHBOURS
from worldsim.geo.hydrology import (
    _LAKE_MIN_DEPTH,
    STREAM_FACTOR,
    Hydrology,
    build_hydrology,
)
from worldsim.geo.terrain import HILL_RELIEF

SEEDS = range(1, 41)


def _sea(water: Hydrology) -> np.ndarray:
    terrain = water.terrain
    return np.asarray(terrain.elevation) < terrain.sea_level


def _sources(water: Hydrology) -> list[tuple[int, int]]:
    """Zellen, an denen ein Fluss BEGINNT (kein Fluss fliesst ihnen zu)."""
    height, width = water.flow.shape
    fed = np.zeros((height, width), dtype=bool)
    for row in range(height):
        for col in range(width):
            if not water.river[row, col]:
                continue
            target = int(water.downstream[row, col])
            if target >= 0:
                fed[target // width, target % width] = True
    return [
        (row, col)
        for row in range(height)
        for col in range(width)
        if water.river[row, col] and not fed[row, col]
    ]


def test_every_drop_reaches_the_sea() -> None:
    """Kein Wasser laeuft im Kreis und keines versickert: jede Landzelle findet das Meer.

    Das ist die tragende Zusicherung des Abflussmodells (und die Bedingung dafuer, dass
    die Akkumulation in EINEM Durchgang rechnen darf). Geprueft wird sie, indem jeder
    Landzelle stur bergab gefolgt wird — bis ins Meer, oder bis der Weg sich beisst.
    """
    for seed in SEEDS:
        water = build_hydrology(seed)
        sea = _sea(water)
        height, width = sea.shape
        for row in range(height):
            for col in range(width):
                if sea[row, col]:
                    continue
                seen: set[int] = set()
                cursor = row * width + col
                while cursor >= 0 and not sea[cursor // width, cursor % width]:
                    assert cursor not in seen, (seed, row, col)  # Kreislauf!
                    seen.add(cursor)
                    cursor = int(water.downstream[cursor // width, cursor % width])
                assert cursor >= 0, (seed, row, col)  # im Nichts geendet


def test_rivers_rise_in_the_high_ground() -> None:
    """Fluesse entspringen OBEN — und zwar, weil dort der Regen faellt, nicht weil es hoch ist.

    Der Unterschied ist messbar: als die Hydrologie versehentlich die Luft-FEUCHTE als
    Niederschlag nahm (statt dessen, was tatsaechlich abregnet), entsprangen die Fluesse
    in der Ebene — das hoechste Relief im ganzen Einzugsgebiet einer Quelle lag bei -0.01.
    Erst der orografische Regen des Luvhangs legt die Quellen dorthin, wo sie hingehoeren.
    """
    reliefs: list[float] = []
    uphill = total = 0
    for seed in SEEDS:
        water = build_hydrology(seed)
        relief = water.terrain.relief
        for row, col in _sources(water):
            total += 1
            reliefs.append(float(relief[row, col]))
            uphill += relief[row, col] >= HILL_RELIEF

    assert total > 300, total
    # Die Quelle liegt im Mittel deutlich ueber der eigenen Kruste — im Bergland.
    assert float(np.median(reliefs)) > 0.10, np.median(reliefs)
    # ... und die Haelfte aller Quellen liegt wirklich im Huegel- oder Bergland.
    assert uphill / total >= 0.45, (uphill, total)


def test_rivers_gather_as_they_go() -> None:
    """Bergab wird der Fluss groesser: er nimmt auf, was ihm zufliesst.

    Das ist keine gezeichnete Verzweigung, sondern die Akkumulation selbst — und genau
    daran haengt die Zeichenstaerke: der Strom ist der Fluss, der schon Fluesse geschluckt
    hat. Also muss der Durchfluss laengs jedes Laufs monoton wachsen.
    """
    confluences = 0
    for seed in SEEDS:
        water = build_hydrology(seed)
        height, width = water.flow.shape
        for row in range(height):
            for col in range(width):
                target = int(water.downstream[row, col])
                if target < 0:
                    continue
                downstream_flow = float(water.flow[target // width, target % width])
                assert downstream_flow >= float(water.flow[row, col]) - 1e-9, (seed, row, col)
                # Ein Zusammenfluss: zwei Fluesse muenden in dieselbe Zelle.
                feeders = sum(
                    1
                    for drow, dcol in NEIGHBOURS
                    if 0 <= row + drow < height
                    and 0 <= col + dcol < width
                    and water.river[row + drow, col + dcol]
                    and int(water.downstream[row + drow, col + dcol]) == target
                )
                confluences += feeders >= 2
    assert confluences > 20, confluences  # Fluesse VEREINIGEN sich, sie laufen nicht parallel


def test_the_big_rivers_end_in_a_delta() -> None:
    """Ein Strom erreicht das Meer — und dort, wo er es tut, steht die Muendung."""
    with_mouth = with_stream = 0
    for seed in SEEDS:
        water = build_hydrology(seed)
        with_mouth += bool(water.mouth.any())
        with_stream += bool((water.flow[water.river] >= STREAM_FACTOR * CFG.river_threshold).any())

        # Jede Muendung liegt im Meer und hat einen Fluss neben sich (nie mitten im Ozean).
        sea = _sea(water)
        height, width = sea.shape
        for row, col in zip(*np.where(water.mouth), strict=True):
            assert sea[row, col], (seed, row, col)
            assert any(
                0 <= row + drow < height
                and 0 <= col + dcol < width
                and water.river[row + drow, col + dcol]
                for drow, dcol in NEIGHBOURS
            ), (seed, row, col)

    assert with_stream / len(SEEDS) >= 0.6, with_stream   # die meisten Welten tragen einen Strom
    assert with_mouth / len(SEEDS) >= 0.8, with_mouth     # und er findet das Meer


def test_lakes_lie_in_hollows_and_hold_water() -> None:
    """Ein See steht in einer Senke — und ist genau so tief, wie die Senke es zulaesst.

    Nichts sucht hier nach Seen: die Depressionsfuellung laeuft, weil das Abflussmodell
    sie braucht (sonst haetten Senken keinen Abfluss), und der See faellt als Nebenprodukt
    heraus. Also muss jede Seezelle unter ihrem eigenen Ueberlauf liegen — und jedes
    Becken muss tief genug sein, dass darin wirklich Wasser steht (sonst waere es eine
    Pfuetze, und Pfuetzen zerhacken die Fluesse, die durch sie hindurchlaufen).
    """
    worlds = 0
    basins = 0
    for seed in SEEDS:
        water = build_hydrology(seed)
        sea = _sea(water)
        worlds += bool(water.lake.any())
        basins += int(water.lake.sum())
        for row, col in zip(*np.where(water.lake), strict=True):
            assert not sea[row, col], (seed, row, col)  # ein See ist kein Meer
            # Das Wasser steht ueber dem Grund: die Zelle ist eine echte Senke.
            assert water.lake_depth[row, col] > 0.0, (seed, row, col)
        # Kein See ohne ein Becken, das die Mindesttiefe wirklich erreicht.
        if water.lake.any():
            assert float(water.lake_depth[water.lake].max()) >= _LAKE_MIN_DEPTH, seed

    assert basins > 100, basins           # Seen sind kein Einzelfall ...
    assert worlds / len(SEEDS) >= 0.4, worlds  # ... und stehen in fast jeder zweiten Welt


def test_erosion_carves_valleys_without_beheading_the_mountains() -> None:
    """Die Erosion tut BEIDES — sonst waere sie den Durchgang nicht wert.

    Sie schneidet Taeler (die Flusszelle liegt tiefer als ihre Querhaenge) und laesst die
    Ketten stehen (das Gebirge bleibt Gebirge).

    Gemessen wird gegen die Gegenprobe — **dieselbe Welt ohne Erosion, an denselben
    Zellen**. Das ist der Punkt: vergleicht man stattdessen jeweils das eigene Flussnetz
    der beiden Welten, misst man zwei verschiedene Zellmengen und bekommt Unsinn heraus.
    Der Test verfolgt also den Lauf der ERODIERTEN Welt und schaut nach, wie tief dieselbe
    Rinne im unerodierten Relief lag.

    Zwei fruehere Fassungen der Erosionsformel fielen genau hier durch: die Lehrbuch-
    Stream-Power (mit dem Gefaelle im Produkt) trug die HAENGE statt der Rinne ab, und die
    Fassung mit gleichverteiltem Regen suchte das Wasser dort, wo keines faellt. Beide
    machten die Taeler FLACHER als gar keine Erosion.
    """
    from dataclasses import replace

    from worldsim.geo.terrain import MAP_HEIGHT, MAP_WIDTH, build_terrain

    flat = replace(CFG, erosion_strength=0.0)
    carved: list[float] = []
    bare: list[float] = []
    with_chain = 0

    for seed in SEEDS:
        water = build_hydrology(seed)
        terrain = water.terrain
        raw = build_terrain(seed, MAP_WIDTH, MAP_HEIGHT, flat)  # dieselbe Welt, nie erodiert
        carved += _valley_depths(water, np.asarray(terrain.elevation))
        bare += _valley_depths(water, np.asarray(raw.elevation))

        land = np.asarray(terrain.elevation) >= terrain.sea_level
        with_chain += bool((land & (terrain.relief >= 0.35)).sum() >= 8)

    # Die Rinne ist TIEFER als vor der Erosion — das ist der ganze Zweck des Durchgangs.
    assert float(np.median(carved)) > float(np.median(bare)), (
        np.median(carved), np.median(bare)
    )
    # Und die Gebirge stehen noch: die Erosion hobelt Rinnen, keine Gipfel.
    assert with_chain / len(SEEDS) >= 0.85, with_chain


def _valley_depths(water: Hydrology, elevation: np.ndarray) -> list[float]:
    """Wie tief die Flusszellen des Bergland-Netzes unter ihren Querhaengen liegen.

    Das Netz kommt immer aus ``water``; das Hoehenfeld wird uebergeben, damit dieselben
    Zellen in zwei Welten (mit und ohne Erosion) verglichen werden koennen.
    """
    terrain = water.terrain
    height, width = elevation.shape
    land = np.asarray(terrain.elevation) >= terrain.sea_level
    depths: list[float] = []
    for row in range(height):
        for col in range(width):
            if not water.river[row, col]:
                continue
            step = water.flows_to(row, col)
            if step is None:
                continue
            # Quer zum Lauf: die beiden Haenge, zwischen denen er liegt.
            across = (-step[1], step[0])
            flanks = [
                (row + sign * across[0], col + sign * across[1]) for sign in (1, -1)
            ]
            if not all(
                0 <= r < height and 0 <= c < width and land[r, c] for r, c in flanks
            ):
                continue
            if float(np.mean([terrain.relief[r, c] for r, c in flanks])) < 0.15:
                continue  # nur im Bergland — in der Ebene gibt es kein Tal zu schneiden
            depths.append(
                float(np.mean([elevation[r, c] for r, c in flanks]) - elevation[row, col])
            )
    return depths


def test_a_river_in_the_desert_carries_foreign_water() -> None:
    """Der Nil, und keiner hat ihn gebaut.

    Eine Wueste bringt keinen Fluss hervor — dort faellt ja kein Regen. Trotzdem stehen
    Fluesse in der Wueste (gemessen: 3.8 % der Wuestenzellen), und zwar aus demselben
    Grund wie auf der Erde: sie kommen von **auswaerts**. Der Regenschatten legt die
    Wueste gerade dorthin, wo ein Gebirge das Wasser abgefangen hat — und an dessen
    anderer Flanke laeuft es hinunter und quert die Trockenzone.

    Der Test misst das direkt, indem er ein zweites Mal akkumuliert: einmal allen Regen,
    einmal nur den, der AUSSERHALB der Wueste gefallen ist. Der Quotient ist der Anteil
    Fremdwasser, den ein Wuestenfluss traegt.
    """
    from worldsim.geo.climate import Biome
    from worldsim.geo.flow import (
        accumulate,
        downstream_links,
        fill_depressions,
    )

    foreign_shares: list[float] = []
    dry_cells = dry_rivers = wet_cells = wet_rivers = 0

    for seed in SEEDS:
        water = build_hydrology(seed)
        terrain, climate = water.terrain, water.climate
        elevation = np.asarray(terrain.elevation)
        sea = _sea(water)
        desert = climate.biome == Biome.WUESTE
        rainforest = climate.biome == Biome.REGENWALD

        dry_cells += int(desert.sum())
        dry_rivers += int((desert & water.river).sum())
        wet_cells += int(rainforest.sum())
        wet_rivers += int((rainforest & water.river).sum())

        # Dieselbe Rechnung, aber der Wuestenregen zaehlt nicht mit.
        drainage = fill_depressions(elevation, sea)
        downstream = downstream_links(drainage, sea)
        elsewhere = np.where(sea | desert, 0.0, np.asarray(climate.rainfall))
        foreign = accumulate(downstream, drainage.upstream_first, elsewhere)
        for row, col in zip(*np.where(desert & water.river), strict=True):
            total = float(water.flow[row, col])
            if total > 0.0:
                foreign_shares.append(float(foreign[row, col]) / total)

    assert dry_cells > 500 and wet_cells > 200, (dry_cells, wet_cells)
    # Im Regenwald steht ein Netz, in der Wueste stehen einzelne Laeufe.
    assert wet_rivers / wet_cells > 1.5 * (dry_rivers / dry_cells), (
        wet_rivers / wet_cells, dry_rivers / dry_cells
    )
    # Und JEDER dieser Laeufe lebt von Wasser, das anderswo gefallen ist: der Median
    # eines Wuestenflusses traegt 96 % Fremdwasser, und KEINER traegt unter 30 %.
    assert len(foreign_shares) > 50, len(foreign_shares)
    assert float(np.median(foreign_shares)) > 0.85, np.median(foreign_shares)
    assert float(np.min(foreign_shares)) > 0.30, np.min(foreign_shares)
    assert float(np.mean(np.array(foreign_shares) > 0.5)) >= 0.90, foreign_shares


def test_hydrology_is_deterministic_and_cannot_bend_the_history() -> None:
    """Gleicher Seed ⇒ gleiches Wasser; und es zu bauen ruehrt die Simulation nicht an.

    Die Hydrologie zieht ueberhaupt keinen Zufall (Wasser wuerfelt nicht, es laeuft
    bergab) und leitet sich rein aus Terrain und Klima ab — beide reine Funktionen des
    Seeds. Seit Schritt 2 speist dasselbe Wasser die Tragfaehigkeit (Fluesse und Kueste
    machen Land fruchtbar), es FORMT also die Geschichte; aber es fuers Rendering
    aufzubauen zieht keinen Master-RNG und mutiert die Welt nicht — den semantischen Pfad
    beruehrt es nie.
    """
    first = np.asarray(build_hydrology(42).flow)
    assert first.tolist() == np.asarray(build_hydrology(42).flow).tolist()
    assert first.tolist() != np.asarray(build_hydrology(99).flow).tolist()

    def trace(seed: int) -> list[tuple[int, str]]:
        _, log = simulate(seed=seed, years=80)
        return [(e.year, e.kind.name) for e in log]

    before = trace(7)
    for seed in SEEDS:  # das Wasser ausgiebig bauen ...
        build_hydrology(seed)
    assert trace(7) == before  # ... aendert an der Historie nichts
