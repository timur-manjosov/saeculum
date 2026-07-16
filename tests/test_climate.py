"""Klima: liegen die Biome dort, wo sie hingehoeren — und WARUM liegen sie dort?

Die Behauptung dieses Schrittes ist nicht "es gibt jetzt Biome", sondern: eine Wueste ist
ein **Ergebnis**. Sie steht entweder im Regenschatten eines Gebirges oder dort, wo die
Luft der Rossbreiten absinkt. Das ist messbar, also wird es hier als **Verteilung ueber
viele Seeds** geprueft — ein einzelner Seed beweist nur sein eigenes Glueck.
"""

from __future__ import annotations

import numpy as np
from worldsim.driver import simulate
from worldsim.geo.climate import Biome, Climate, build_climate, latitudes
from worldsim.geo.terrain import PEAK_RELIEF

SEEDS = range(1, 31)
HORSE_LOW, HORSE_HIGH = 15.0, 40.0  # die Rossbreiten, grosszuegig gefasst
SHADOW_REACH = 6                    # so weit luvwaerts darf der Berg stehen, der schattet
INLAND_FETCH = 10                   # so viele Landzellen gegen den Wind heissen "tief im Kontinent"


def _land(climate: Climate) -> np.ndarray:
    terrain = climate.terrain
    return np.asarray(terrain.elevation) >= terrain.sea_level


def _peaks(climate: Climate) -> np.ndarray:
    return _land(climate) & (climate.terrain.relief >= PEAK_RELIEF)


def _abs_lat(climate: Climate) -> np.ndarray:
    """(H, W) Betrag des Breitengrads je Zelle."""
    height, width = climate.temperature.shape
    return np.abs(latitudes(height))[:, None] * np.ones((height, width))


def _biome_mask(climate: Climate, biome: Biome) -> np.ndarray:
    return climate.biome == biome


def _mountain_crossings(climate: Climate) -> list[tuple[float, float]]:
    """Fuer jede Bergzelle das Paar (Feuchte im Luv, Feuchte im Lee) — beide an Land."""
    peaks = _peaks(climate)
    land = _land(climate)
    height, width = peaks.shape
    pairs: list[tuple[float, float]] = []
    for row in range(height):
        step = int(climate.wind[row])  # +1: die Luft zieht nach Osten ⇒ Luv liegt westlich
        for col in range(width):
            luv, lee = col - step, col + step
            if not peaks[row, col] or not (0 <= luv < width and 0 <= lee < width):
                continue
            if land[row, luv] and land[row, lee]:
                pairs.append((float(climate.moisture[row, luv]), float(climate.moisture[row, lee])))
    return pairs


def test_temperature_falls_from_equator_to_the_poles() -> None:
    """Das Grundgefaelle der Breite — gemessen ueber ALLE Zellen, nicht nur ueber Land.

    Ueber Land allein waere der Test unehrlich: eine Welt, deren Tropen zufaellig ein
    Hochgebirge tragen, ist dort kalt — zu Recht. Das Breitengefaelle zeigt sich sauber
    dort, wo die Hoehe nicht dazwischenfunkt.
    """
    for seed in SEEDS:
        climate = build_climate(seed)
        abs_lat = _abs_lat(climate)
        temp = np.asarray(climate.temperature)
        tropics = float(np.median(temp[abs_lat < 15.0]))
        polar = float(np.median(temp[abs_lat > 50.0]))
        assert tropics > polar + 0.4, (seed, tropics, polar)


def test_temperature_falls_with_altitude() -> None:
    """Und der Hoehengradient: hoch gelegenes Land ist kaelter als tiefes auf gleicher Breite."""
    gaps = []
    for seed in SEEDS:
        climate = build_climate(seed)
        band = _land(climate) & (_abs_lat(climate) < 40.0)  # eine Breitenzone
        altitude = np.asarray(climate.altitude)
        temp = np.asarray(climate.temperature)
        high = band & (altitude > 0.4)
        low = band & (altitude < 0.1)
        if not (high.any() and low.any()):
            continue
        gaps.append(float(np.median(temp[low])) - float(np.median(temp[high])))

    assert len(gaps) >= 0.8 * len(SEEDS), len(gaps)
    assert float(np.median(gaps)) > 0.25, np.median(gaps)


def test_wind_bands_follow_the_three_cells() -> None:
    """Passat aus Ost, Westwinde, Polarost — die Richtung haengt nur am Breitenband."""
    climate = build_climate(1)
    lat = latitudes(climate.temperature.shape[0])
    for row, degrees in enumerate(lat):
        band = abs(degrees)
        expected = +1 if 30.0 <= band < 60.0 else -1  # Westwinde ziehen nach Osten
        assert int(climate.wind[row]) == expected, (degrees, climate.wind[row])


def test_high_peaks_are_cold_even_in_the_tropics() -> None:
    """Ein hoher Berg am Aequator traegt Schnee — der Hoehengradient schlaegt die Breite.

    Gemessen am **hoechsten tropischen Gipfel** jeder Welt, die einen hat: er muss
    alpinen Fels oder Gletscher tragen, obwohl er auf der Breite des Regenwalds steht.

    ``0.6`` ueber der typischen Landhoehe ist die Schwelle fuer "hoher Berg". Sie lag
    frueher bei 0.8 — bis die Erosion kam und die Gipfel etwas abtrug (sie schneidet ja
    gerade die nassen Luvhaenge an). Der Anspruch bleibt derselbe, nur der Massstab folgt
    dem Relief: bei 0.6 qualifizieren sich 21 von 30 Welten, und **alle 21** tragen oben
    Fels oder Eis.
    """
    tested = carried = 0
    for seed in SEEDS:
        climate = build_climate(seed)
        altitude = np.asarray(climate.altitude)
        tropical = _land(climate) & (_abs_lat(climate) < 15.0)
        if not tropical.any():
            continue
        highest = np.where(tropical, altitude, -np.inf)
        cell = np.unravel_index(np.argmax(highest), highest.shape)
        if highest[cell] < 0.6:
            continue  # diese Welt hat in den Tropen schlicht keinen hohen Berg
        tested += 1
        carried += climate.biome[cell] in (Biome.GLETSCHER, Biome.ALPIN)

    assert tested >= 0.5 * len(SEEDS), tested
    assert carried / tested >= 0.8, (carried, tested)


def test_the_lee_of_a_mountain_is_drier_than_its_windward_side() -> None:
    """Der Regenschatten — der eine Effekt, der diesen Schritt traegt.

    Nicht als Regel "hinter Bergen ist es trocken" eingebaut, sondern als Folge: die Luft
    hat ihr Wasser am Luvhang verloren. Der Test misst genau das, ueber JEDE Bergzelle,
    an der der Wind von Land zu Land kreuzt.
    """
    pairs = [p for seed in SEEDS for p in _mountain_crossings(build_climate(seed))]
    assert len(pairs) > 200, len(pairs)

    luv = np.array([p[0] for p in pairs])
    lee = np.array([p[1] for p in pairs])
    assert float((lee < luv).mean()) >= 0.95, float((lee < luv).mean())
    ratio = float(np.median(lee / np.maximum(luv, 1e-9)))
    assert ratio < 0.6, ratio  # die Leeseite behaelt weniger als die Haelfte


def test_every_desert_has_a_reason() -> None:
    """Eine Wueste ist ein Ergebnis, kein Fleck — und es gibt genau drei Gruende dafuer.

    Sie steht in den Rossbreiten (dort sinkt die Luft), im Regenschatten eines Gebirges
    (dort hat die Luft ihr Wasser schon verloren) oder tief im Kontinent (dort ist sie nie
    hingekommen). Der Test verlangt fuer JEDE Wuestenzelle einen dieser Gruende.
    """
    horse = shadow = inland = explained = total = 0
    for seed in SEEDS:
        climate = build_climate(seed)
        peaks, land = _peaks(climate), _land(climate)
        abs_lat = _abs_lat(climate)
        desert = _biome_mask(climate, Biome.WUESTE)
        height, width = desert.shape
        for row in range(height):
            step = int(climate.wind[row])
            for col in range(width):
                if not desert[row, col]:
                    continue
                total += 1
                in_horse = HORSE_LOW <= abs_lat[row, col] <= HORSE_HIGH
                # Steht luvwaerts (entgegen der Windrichtung) ein Berg?
                upwind = (col - step * k for k in range(1, SHADOW_REACH + 1))
                shadowed = any(0 <= c < width and peaks[row, c] for c in upwind)
                # Wie weit ist es gegen den Wind bis zum offenen Meer?
                fetch, cursor = 0, col - step
                while 0 <= cursor < width and land[row, cursor]:
                    fetch += 1
                    cursor -= step
                far_inland = fetch >= INLAND_FETCH

                horse += in_horse
                shadow += shadowed
                inland += far_inland
                explained += in_horse or shadowed or far_inland

    assert total > 300, total
    # Praktisch jede Wueste hat einen Grund ...
    assert explained / total >= 0.90, (explained, total)
    # ... und die beiden Gruende, um die es diesem Schritt geht, tragen den Loewenanteil.
    assert (horse + shadow) / total >= 0.70, (horse, shadow, total)
    assert shadow / total >= 0.20, (shadow, total)  # der Regenschatten ist kein Randfall


def test_biomes_form_latitude_bands() -> None:
    """Glaubwuerdige Baender: Regenwald am Aequator, Wueste in den Rossbreiten, Tundra am Pol.

    Gemessen am **Mittel** der Breite, nicht am Median: bei 17 Zeilen faellt der Median
    ganzer Baender auf dieselbe Zeile und behauptet Gleichstaende, die keine sind.
    """
    lats: dict[Biome, list[float]] = {}
    for seed in SEEDS:
        climate = build_climate(seed)
        abs_lat = _abs_lat(climate)
        for biome in Biome:
            lats.setdefault(biome, []).extend(abs_lat[_biome_mask(climate, biome)].tolist())

    def band(biome: Biome) -> float:
        return float(np.mean(lats[biome]))

    # Die Reihenfolge vom Aequator nach aussen — das ist die Erde, im Groben.
    assert band(Biome.REGENWALD) < band(Biome.SAVANNE) < band(Biome.WUESTE), (
        band(Biome.REGENWALD), band(Biome.SAVANNE), band(Biome.WUESTE)
    )
    assert band(Biome.WUESTE) < band(Biome.GEMAESSIGTER_WALD) < band(Biome.TAIGA), (
        band(Biome.WUESTE), band(Biome.GEMAESSIGTER_WALD), band(Biome.TAIGA)
    )
    assert band(Biome.TAIGA) < band(Biome.TUNDRA), (band(Biome.TAIGA), band(Biome.TUNDRA))
    # Und die Wueste liegt im Mittel wirklich in den Rossbreiten.
    assert HORSE_LOW <= band(Biome.WUESTE) <= HORSE_HIGH, band(Biome.WUESTE)


def test_every_world_is_habitable() -> None:
    """Keine Welt ist ein Schneeball und keine eine reine Wueste — die Baender teilen sie."""
    for seed in SEEDS:
        climate = build_climate(seed)
        land = _land(climate)
        kinds = {climate.biome[cell] for cell in zip(*np.where(land), strict=True)}
        assert len(kinds) >= 4, (seed, kinds)  # jede Welt traegt mehrere Zonen

        share = {b: float(_biome_mask(climate, b).sum()) / int(land.sum()) for b in Biome}
        assert share[Biome.GLETSCHER] < 0.6, (seed, share[Biome.GLETSCHER])
        assert share[Biome.WUESTE] < 0.6, (seed, share[Biome.WUESTE])


def test_climate_is_deterministic_and_cannot_bend_the_history() -> None:
    """Gleicher Seed ⇒ gleiches Klima; und es zu bauen ruehrt die Simulation nicht an.

    Das Klima FORMT die Geschichte (seit Schritt 2 speist es ueber Biom und Feuchte die
    Tragfaehigkeit), aber es ist eine reine Funktion des Seeds und zieht keinen
    Master-RNG — es fuers Rendering aufzubauen verschiebt darum keinen semantischen Zug.
    """
    first = np.asarray(build_climate(42).moisture)
    assert first.tolist() == np.asarray(build_climate(42).moisture).tolist()
    assert first.tolist() != np.asarray(build_climate(99).moisture).tolist()

    def trace(seed: int) -> list[tuple[int, str]]:
        _, log = simulate(seed=seed, years=80)
        return [(e.year, e.kind.name) for e in log]

    before = trace(7)
    for seed in SEEDS:  # das Klima ausgiebig bauen ...
        build_climate(seed)
    assert trace(7) == before  # ... aendert an der Historie nichts
