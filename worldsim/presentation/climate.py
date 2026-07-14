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
2. **Windbaender.** Je Breitenband eine vorherrschende Richtung, wie auf der Erde:
   Passat aus Ost in den Tropen, Westwinde in den mittleren Breiten, Polarost darueber.
   Ein Richtungsfeld pro Zeile — **kein** Zirkulationsmodell.
3. **Feuchtigkeit.** Sie kommt vom Ozean und wird ENTLANG des Windes landeinwaerts
   getragen. Unterwegs trocknet sie aus (Kontinentalitaet); steigt das Gelaende, regnet
   sie orografisch ab: die Luvseite wird sehr feucht, und was den Kamm ueberquert, ist
   arm — der **Regenschatten**. Dazu die Absinkzone der Rossbreiten.
4. **Biome** aus Temperatur x Feuchtigkeit (Whittaker-artig), plus die alpine Zone.

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
from worldsim.presentation.terrain import MAP_HEIGHT, MAP_WIDTH, Terrain, build_terrain
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


# --- Windbaender (Grad Breite) -------------------------------------------------
# Die Grenzen der drei Zellen der Erdatmosphaere, grob. ``+1`` heisst: die Luft zieht
# nach OSTEN (Westwind), ``-1``: nach Westen (Ostwind/Passat).
_TRADE_LIMIT = 30.0   # Passat: aus Ost
_WESTERLY_LIMIT = 60.0  # Westwinde: aus West
_EAST, _WEST = -1, +1

# --- Zirkulation: wo die Luft steigt (Regen) und wo sie sinkt (Duerre) ---------
# Die Rossbreiten sind der EINE Grund, warum die grossen Wuesten der Erde auf einem
# Breitenband liegen und nicht zufaellig verteilt sind. Als Gauss-Baender ueber der
# Breite modelliert — kein Zirkulationsmodell, nur dessen sichtbares Ergebnis.
_ITCZ_CENTER, _ITCZ_WIDTH, _ITCZ_BOOST = 0.0, 12.0, 0.35    # Aequator: Auftrieb ⇒ Regen
_HORSE_CENTER, _HORSE_WIDTH = 27.0, 13.0                    # Rossbreiten: Absinken ⇒ trocken
_FRONT_CENTER, _FRONT_WIDTH, _FRONT_BOOST = 55.0, 12.0, 0.20  # Polarfront: Auftrieb ⇒ Regen

# --- Feuchtetransport ---------------------------------------------------------
# Am Luvhang regnet es ZUSAETZLICH aus: die Zelle bekommt mehr ab, als die Luft an
# Grundfeuchte traegt. Ohne das waere der Luvhang nur "nicht trocken", nicht "sehr feucht".
_WINDWARD_BONUS = 0.60
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


def latitudes(height: int = MAP_HEIGHT) -> np.ndarray:
    """Breitengrad je Zeile: Nordpol oben, Suedpol unten — **flaechentreu**.

    Die Karte spannt einen ganzen Planeten auf; nur so gibt es Pole, Rossbreiten und
    Tropen ueberhaupt. Die Zuordnung ist aber NICHT linear, sondern ``arcsin``
    (Lambert): jede Zeile deckt damit denselben Anteil der Kugelflaeche.

    Das ist kein Schoenheitsdetail, es entscheidet ueber das ganze Klima. Linear
    verteilt lagen 24 % der Zeilen jenseits von 70° Breite — auf einer Kugel sind das
    aber nur 6 % der Flaeche. Die Karte ueberzeichnete die Pole vierfach, und heraus kam
    (gemessen) ein Schneeball: 38 % des Landes Gletscher. Flaechentreu faellt der Pol auf
    eine Zeile zurueck, und die Tropen bekommen den Platz, der ihnen zusteht.
    """
    fraction = 1.0 - 2.0 * (np.arange(height) + 0.5) / height  # +1 (Nord) .. -1 (Sued)
    return np.degrees(np.arcsin(fraction))


def _wind_bands(lat: np.ndarray) -> np.ndarray:
    """Vorherrschende Windrichtung je Zeile — drei Baender je Hemisphaere."""
    abs_lat = np.abs(lat)
    wind = np.full(lat.shape, _EAST, dtype=int)                      # Passat (aus Ost)
    wind[(abs_lat >= _TRADE_LIMIT) & (abs_lat < _WESTERLY_LIMIT)] = _WEST  # Westwinde
    wind[abs_lat >= _WESTERLY_LIMIT] = _EAST                         # Polarost
    return wind


def _circulation(lat: np.ndarray, cfg: MapConfig) -> np.ndarray:
    """Regen-Faktor der Breite: Auftrieb macht nass, Absinken macht trocken."""
    abs_lat = np.abs(lat)
    itcz = _ITCZ_BOOST * np.exp(-(((lat - _ITCZ_CENTER) / _ITCZ_WIDTH) ** 2))
    horse = cfg.horse_latitude_dryness * np.exp(
        -(((abs_lat - _HORSE_CENTER) / _HORSE_WIDTH) ** 2)
    )
    front = _FRONT_BOOST * np.exp(-(((abs_lat - _FRONT_CENTER) / _FRONT_WIDTH) ** 2))
    return np.clip(1.0 + itcz - horse + front, 0.0, 1.5)


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


def _moisture(terrain: Terrain, wind: np.ndarray, cfg: MapConfig) -> np.ndarray:
    """Traege die Feuchte vom Ozean landeinwaerts — das Herz dieses Schrittes.

    Je Zeile zieht eine Luftmasse in Windrichtung ueber das Gitter. Ueber Wasser ist sie
    gesaettigt; ueber Land verliert sie stetig (Kontinentalitaet) und an jeder Steigung
    zusaetzlich (orografischer Regen). Der Luvhang bekommt den Regen, die Leeseite
    bekommt, was uebrig ist — und das ist der Regenschatten. Er entsteht hier NICHT als
    Regel "hinter Bergen ist es trocken", sondern weil die Luft ihr Wasser vorher
    verloren hat: dieselbe Ursache, aus der die Wuesten der Erde hinter Gebirgen liegen.
    """
    elevation = np.asarray(terrain.elevation)
    height, width = elevation.shape
    is_water = elevation < terrain.sea_level
    moisture = np.ones((height, width), dtype=float)
    inland_loss = 1.0 / cfg.moisture_range

    for row in range(height):
        # In Windrichtung marschieren: die Luft kommt von der Luv-Kante der Zeile.
        columns = range(width) if wind[row] == _WEST else range(width - 1, -1, -1)
        carry = 1.0                       # Feuchte der Luftmasse (1 = gesaettigt)
        upwind_height = terrain.sea_level  # sie kommt ueber dem offenen Meer herein
        for col in columns:
            here = float(elevation[row, col])
            if is_water[row, col]:
                carry = 1.0               # ueber dem Ozean laedt sie sich wieder auf
                moisture[row, col] = 1.0
            else:
                rise = max(0.0, here - upwind_height)
                lift = min(1.0, rise / cfg.orographic_scale)  # 0..1: wie steil es aufwaerts geht
                # Die ANKOMMENDE Luft traegt die Feuchte dieser Zelle; am Luvhang regnet
                # sie zusaetzlich ab (deshalb ist der Luvhang nass, nicht bloss "nicht trocken").
                moisture[row, col] = min(1.0, carry * (1.0 + _WINDWARD_BONUS * lift))
                # ... und genau das fehlt ihr danach.
                loss = min(1.0, inland_loss + cfg.rain_shadow_strength * lift)
                carry *= 1.0 - loss
            upwind_height = here

    # Die Absinkzone der Rossbreiten legt sich ueber alles: sie macht trocken, was der
    # Wind eigentlich befeuchtet haette.
    lat = latitudes(height)
    moisture *= _circulation(lat, cfg)[:, None]
    moisture[is_water] = 1.0
    return np.clip(moisture, 0.0, 1.0)


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
    wind = _wind_bands(lat)
    temperature = _temperature(terrain, altitude, lat, noise, cfg)
    moisture = _moisture(terrain, wind, cfg)

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

    for field in (temperature, moisture, wind, altitude):
        field.setflags(write=False)  # gecacht ⇒ nicht mutieren
    return Climate(
        temperature=temperature,
        moisture=moisture,
        wind=wind,
        biome=biome,
        altitude=altitude,
        terrain=terrain,
    )
