"""climate — Temperatur, Wind, Feuchtigkeit: woraus die Biome folgen.

Auch hier gilt der Leitgedanke aus Schritt 1: Erdaehnlichkeit entsteht aus sichtbaren
**Prozessen**. Eine Wueste ist kein Fleck in einer Rauschtextur, sie ist ein *Ergebnis* —
entweder steht sie im Windschatten eines Gebirges, oder sie liegt dort, wo die Luft der
Hadley-Zelle absinkt. Beides erzeugt dieses Modul, und beides ist danach messbar.

Die Kette
---------
1. **Temperatur.** Faellt vom Aequator zum Pol (Breitengrad der Zeile) und mit der Hoehe
   ueber dem Meeresspiegel. Der Hoehengradient ist stark genug, dass der hoechste Gipfel
   auch am Aequator unter die Schneegrenze faellt — es braucht deshalb *keine* getrennte
   "Schnee-Hoehenzone": sie faellt aus der Temperatur heraus, breitenunabhaengig.
2. **Wind und Regen** kommen aus :mod:`worldsim.geo.rain`: drei Windbaender je
   Hemisphaere, eine Luftmasse, die landeinwaerts zieht, austrocknet und an Steigungen
   orografisch abregnet — der **Regenschatten**. Das Modul steht bewusst UNTER dem Klima,
   weil schon die Erosion des Terrains denselben Regen braucht: wer ein Tal schneidet,
   muss das Wasser sein, das darin fliesst.
3. **Biome** aus Temperatur x Feuchtigkeit (Whittaker-artig), plus die alpine Zone.

Was das Modul NICHT tut: eine Zirkulation simulieren, Jahreszeiten kennen, Zeit haben.
Es ist ein Standbild wie die Tektonik — einmal je Welt gebaut (gecacht), nie pro Tick.
Read-only ueber der Simulation; der Zufall kommt aus dem **kosmetischen** Sub-Strom.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache

import numpy as np
from opensimplex import OpenSimplex

from worldsim.config import DEFAULT_MAP_CONFIG, MapConfig
from worldsim.geo.rain import latitudes, moisture_and_rain, wind_bands
from worldsim.geo.terrain import MAP_HEIGHT, MAP_WIDTH, Terrain, build_terrain
from worldsim.rng import Rng

__all__ = ["Biome", "Climate", "build_climate", "latitudes"]


class Biome(Enum):
    """Die Landschaftstypen der Karte. Wasser traegt kein Biom (das macht die Geologie)."""

    GLETSCHER = "Gletscher"
    ALPIN = "alpiner Fels"
    TUNDRA = "Tundra"
    TAIGA = "Nadelwald"
    GEMAESSIGTER_WALD = "gemaessigter Wald"
    FEUCHTGEBIET = "Feuchtgebiet"
    GRASLAND = "Grasland"
    STEPPE = "Steppe"
    SAVANNE = "Savanne"
    REGENWALD = "Regenwald"
    WUESTE = "Wueste"


# Ein Feuchtgebiet ist nass UND flach — ein Sumpf liegt nicht am Hang.
_WETLAND_MOISTURE = 0.88
_WETLAND_ALTITUDE = 0.12
# Die Baumgrenze: darunter waechst kein Wald mehr, auch wenn Wasser da ist. Ohne sie
# stand in den Messungen Taiga bei 70° Breite — Feuchte allein macht keinen Baum, es
# fehlt die Vegetationszeit.
_TREELINE_TEMP = 0.22


@dataclass(frozen=True)
class Climate:
    """Das fertige Klima einer Welt — einmal je Seed gebaut, nie pro Tick."""

    temperature: np.ndarray  # (H, W) 0..1: 1 = tropisch heiss, 0 = polar
    moisture: np.ndarray     # (H, W) 0..1: 1 = gesaettigt (Ozean/Luvhang), 0 = Wueste
    rainfall: np.ndarray     # (H, W): was hier ABREGNET (s. :func:`rain.moisture_and_rain`)
    wind: np.ndarray         # (H,) int: +1 = die Luft zieht nach Osten, -1 nach Westen
    biome: np.ndarray        # (H, W) object: :class:`Biome` je Landzelle, sonst ``None``
    altitude: np.ndarray     # (H, W): Hoehe ueber der TYPISCHEN Landhoehe (s. u.)
    terrain: Terrain


def _land_reference(terrain: Terrain) -> float:
    """Die typische Landhoehe dieser Welt — der Bezug, gegen den "hoch" gemessen wird.

    **Nicht** der Meeresspiegel, und das ist derselbe Grund wie bei den Biomen des Terrains
    (:attr:`Terrain.relief`): der Meeresspiegel schwimmt mit dem Verhaeltnis kontinentaler
    zu ozeanischer Flaeche. In einer kontinentarmen Welt sinkt er fast auf den Ozeanboden,
    und dann steht der ganz gewoehnliche Kontinentalsockel +0.75 "hoch" ueber ihm — mit dem
    Hoehengradienten multipliziert wird daraus ein Schneeball (gemessen: ein Seed zu 63 %
    Gletscher, ohne einen einzigen echten Berg).

    Gegen die typische Landhoehe gemessen luegt nichts: die Ebene liegt bei null, und
    "hoch" heisst hoch **ueber dem umgebenden Land** — genau das, was die Temperatur
    tatsaechlich interessiert.
    """
    elevation = np.asarray(terrain.elevation)
    land = elevation >= terrain.sea_level
    if not land.any():
        return terrain.sea_level
    return float(np.median(elevation[land]))


def _noise_field(gen: OpenSimplex, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """``opensimplex`` ueber einem Gitter, elementweise (das Feld ist winzig)."""
    out = np.empty_like(xs)
    flat_x, flat_y, flat_out = xs.ravel(), ys.ravel(), out.ravel()
    for i in range(flat_x.size):
        flat_out[i] = gen.noise2(float(flat_x[i]), float(flat_y[i]))
    return out


def _temperature(
    terrain: Terrain, altitude: np.ndarray, lat: np.ndarray, noise: OpenSimplex, cfg: MapConfig
) -> np.ndarray:
    """Aequator-zu-Pol-Gefaelle, minus Hoehengradient, plus etwas Unregelmaessigkeit."""
    height, width = terrain.elevation.shape
    xs, ys = np.meshgrid(
        (np.arange(width) + 0.5) / width, (np.arange(height) + 0.5) / height
    )
    base = 1.0 - np.abs(lat)[:, None] / 90.0
    rise = np.clip(altitude, 0.0, None)  # ueber der typischen Landhoehe, nicht ueber dem Meer
    rough = cfg.temp_noise * _noise_field(noise, xs * 3.0 + 91.0, ys * 3.0 - 37.0)
    return np.clip(base - cfg.altitude_lapse * rise + rough, 0.0, 1.0)


def _classify(temp: float, moist: float, altitude: float, cfg: MapConfig) -> Biome:
    """Whittaker-artig: Temperatur x Feuchtigkeit ⇒ Biom, plus die Hoehenzonen."""
    if temp < cfg.snow_temp:
        return Biome.GLETSCHER  # Pole UND hohe Gipfel — der Hoehengradient macht beides
    if altitude >= cfg.alpine_altitude and temp < cfg.alpine_temp:
        return Biome.ALPIN

    if temp < cfg.boreal_temp:  # kalt
        if temp < _TREELINE_TEMP:
            return Biome.TUNDRA  # jenseits der Baumgrenze: Feuchte allein macht keinen Wald
        return Biome.TAIGA if moist >= cfg.dry_moisture else Biome.TUNDRA

    if moist >= _WETLAND_MOISTURE and altitude < _WETLAND_ALTITUDE:
        return Biome.FEUCHTGEBIET  # nass UND flach: ein Sumpf liegt nicht am Hang

    if temp < cfg.temperate_temp:  # gemaessigt
        if moist < cfg.arid_moisture:
            return Biome.WUESTE
        if moist < cfg.dry_moisture:
            return Biome.STEPPE
        if moist < cfg.humid_moisture:
            return Biome.GRASLAND
        return Biome.GEMAESSIGTER_WALD

    # tropisch
    if moist < cfg.arid_moisture:
        return Biome.WUESTE
    if moist < cfg.humid_moisture:
        return Biome.SAVANNE
    return Biome.REGENWALD


@lru_cache(maxsize=8)
def build_climate(
    seed: int,
    width: int = MAP_WIDTH,
    height: int = MAP_HEIGHT,
    cfg: MapConfig = DEFAULT_MAP_CONFIG,
) -> Climate:
    """Baue das Klima einer Welt: Temperatur ⇒ Wind ⇒ Feuchtigkeit ⇒ Biome.

    Reine Funktion von ``(seed, width, height, cfg)`` und gecacht: sie laeuft **einmal**
    je Welt, nie pro Tick. Der Zufall (nur die Temperatur-Unregelmaessigkeit) kommt aus
    dem **kosmetischen** Sub-Strom ``"climate"`` — das Klima kann die Historie nicht
    verbiegen.
    """
    terrain = build_terrain(seed, width, height, cfg)
    gen = Rng(seed).cosmetic_stream("climate")
    noise = OpenSimplex(gen.getrandbits(63))

    # Hoehe ueber der typischen Landhoehe — der stabile Bezug, nicht der schwimmende
    # Meeresspiegel (siehe :func:`_land_reference`).
    altitude = np.asarray(terrain.elevation) - _land_reference(terrain)
    lat = latitudes(height)
    wind = wind_bands(lat)
    temperature = _temperature(terrain, altitude, lat, noise, cfg)
    # Derselbe Regen, der oben in der Erosion die Taeler geschnitten hat — nur laeuft er
    # jetzt ueber das FERTIGE Relief. Das Land hat den Regen umgelenkt, der es geformt hat.
    moisture, rainfall = moisture_and_rain(
        np.asarray(terrain.elevation), terrain.sea_level, cfg
    )

    is_land = np.asarray(terrain.elevation) >= terrain.sea_level
    biome = np.empty((height, width), dtype=object)
    for row in range(height):
        for col in range(width):
            if not is_land[row, col]:
                continue  # Wasser traegt kein Biom — das macht die Geologie
            biome[row, col] = _classify(
                float(temperature[row, col]),
                float(moisture[row, col]),
                float(altitude[row, col]),
                cfg,
            )

    for field in (temperature, moisture, rainfall, wind, altitude):
        field.setflags(write=False)  # gecacht ⇒ nicht mutieren
    return Climate(
        temperature=temperature,
        moisture=moisture,
        rainfall=rainfall,
        wind=wind,
        biome=biome,
        altitude=altitude,
        terrain=terrain,
    )
