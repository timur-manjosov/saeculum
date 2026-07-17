"""rain — Wind und Regen ueber einem Hoehenfeld. Die Ursache, nicht die Wirkung.

Dieses Modul weiss nur, was eine Zeile fuer eine Breite steht und wie hoch das Land ist.
Daraus macht es zwei Felder: was die Luft noch **traegt** (Feuchte) und was sie hier
**fallen laesst** (Niederschlag).

Warum es unter :mod:`worldsim.geo.terrain` steht und nicht im Klima, wo es
hingehoerte: weil die **Erosion** den Regen braucht. Ein Fluss schneidet sein Tal mit dem
Wasser, das auf ihn faellt — also muss dasselbe Regenfeld, das spaeter die Fluesse fuellt,
schon die Taeler schneiden, in denen sie liegen werden. Gemessen ist das kein Detail: mit
gleichverteiltem Regen erodiert, wurden die Talquerschnitte an den Flusszellen FLACHER als
ganz ohne Erosion (+0.001 statt +0.053) — die Erosion trug die Haenge um die Fluesse ab,
weil sie das Wasser an ganz anderen Stellen vermutete. Mit dem echten Niederschlag
vertieft sie sie (+0.065). Dieselbe Ursache, dieselbe Wirkung, ein Feld.

Der Regen laeuft also zweimal: einmal ueber dem rohen Relief (er schneidet die Taeler),
einmal ueber dem fertigen (er traegt das Klima). Das ist keine Zeitsimulation, sondern
eine einzige Rueckkopplung: das Land lenkt den Regen, der Regen formt das Land.

Kein Zirkulationsmodell, keine Physik — drei Windbaender und eine Luftmasse, die
landeinwaerts zieht und auf Steigungen abregnet.
"""

from __future__ import annotations

import numpy as np

from worldsim.config import MapConfig

__all__ = [
    "EAST",
    "WEST",
    "circulation",
    "latitudes",
    "moisture_and_rain",
    "wind_bands",
]

# --- Windbaender (Grad Breite) -------------------------------------------------
# Die Grenzen der drei Zellen der Erdatmosphaere, grob. ``+1`` heisst: die Luft zieht
# nach OSTEN (Westwind), ``-1``: nach Westen (Ostwind/Passat).
_TRADE_LIMIT = 30.0     # Passat: aus Ost
_WESTERLY_LIMIT = 60.0  # Westwinde: aus West
EAST, WEST = -1, +1

# --- Zirkulation: wo die Luft steigt (Regen) und wo sie sinkt (Duerre) ---------
# Die Rossbreiten sind der EINE Grund, warum die grossen Wuesten der Erde auf einem
# Breitenband liegen und nicht zufaellig verteilt sind. Als Gauss-Baender ueber der
# Breite modelliert — kein Zirkulationsmodell, nur dessen sichtbares Ergebnis.
_ITCZ_CENTER, _ITCZ_WIDTH, _ITCZ_BOOST = 0.0, 12.0, 0.35    # Aequator: Auftrieb ⇒ Regen
_HORSE_CENTER, _HORSE_WIDTH = 27.0, 13.0                    # Rossbreiten: Absinken ⇒ trocken
_FRONT_CENTER, _FRONT_WIDTH, _FRONT_BOOST = 55.0, 12.0, 0.20  # Polarfront: Auftrieb ⇒ Regen

# Am Luvhang regnet es ZUSAETZLICH aus: die Zelle bekommt mehr ab, als die Luft an
# Grundfeuchte traegt. Ohne das waere der Luvhang nur "nicht trocken", nicht "sehr feucht".
_WINDWARD_BONUS = 0.60


def latitudes(height: int) -> np.ndarray:
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


def wind_bands(lat: np.ndarray) -> np.ndarray:
    """Vorherrschende Windrichtung je Zeile — drei Baender je Hemisphaere."""
    abs_lat = np.abs(lat)
    wind = np.full(lat.shape, EAST, dtype=int)                      # Passat (aus Ost)
    wind[(abs_lat >= _TRADE_LIMIT) & (abs_lat < _WESTERLY_LIMIT)] = WEST  # Westwinde
    wind[abs_lat >= _WESTERLY_LIMIT] = EAST                         # Polarost
    return wind


def circulation(lat: np.ndarray, cfg: MapConfig) -> np.ndarray:
    """Regen-Faktor der Breite: Auftrieb macht nass, Absinken macht trocken."""
    abs_lat = np.abs(lat)
    itcz = _ITCZ_BOOST * np.exp(-(((lat - _ITCZ_CENTER) / _ITCZ_WIDTH) ** 2))
    horse = cfg.horse_latitude_dryness * np.exp(
        -(((abs_lat - _HORSE_CENTER) / _HORSE_WIDTH) ** 2)
    )
    front = _FRONT_BOOST * np.exp(-(((abs_lat - _FRONT_CENTER) / _FRONT_WIDTH) ** 2))
    return np.clip(1.0 + itcz - horse + front, 0.0, 1.5)


def moisture_and_rain(
    elevation: np.ndarray, sea_level: float, cfg: MapConfig
) -> tuple[np.ndarray, np.ndarray]:
    """Traege die Feuchte vom Ozean landeinwaerts ⇒ ``(Feuchte, Niederschlag)``.

    Je Zeile zieht eine Luftmasse in Windrichtung ueber das Gitter. Ueber Wasser ist sie
    gesaettigt; ueber Land verliert sie stetig (Kontinentalitaet) und an jeder Steigung
    zusaetzlich (orografischer Regen). Der Luvhang bekommt den Regen, die Leeseite
    bekommt, was uebrig ist — und das ist der Regenschatten. Er entsteht hier NICHT als
    Regel "hinter Bergen ist es trocken", sondern weil die Luft ihr Wasser vorher
    verloren hat: dieselbe Ursache, aus der die Wuesten der Erde hinter Gebirgen liegen.

    Zwei verschiedene Groessen fallen dabei an, und sie zu verwechseln ist ein Fehler mit
    Folgen:

    * die **Feuchte** — was die Luft ueber dieser Zelle noch TRAEGT. Daran haengt, was
      hier waechst: die Vegetation lebt von der Luftfeuchte und dem Bodenwasser.
    * der **Niederschlag** — was hier tatsaechlich ABREGNET (``carry x loss``). Daran
      haengt, wieviel Wasser bergab laeuft: der Fluss, und das Tal, das er schneidet.

    Am Luvhang eines Gebirges klaffen die beiden weit auseinander: die Luft regnet dort
    den Grossteil ihrer Fracht auf einmal aus. Genau deshalb entspringen die Fluesse der
    Erde in den Bergen — und nicht, weil Berge hoch sind, sondern weil auf ihnen der
    Regen faellt. (Gemessen, als die Hydrologie versehentlich die FEUCHTE als Regen nahm:
    die Fluesse entsprangen samt und sonders in der Ebene, das hoechste Relief in ihrem
    ganzen Einzugsgebiet lag bei -0.01. Die Berge gaben kein Wasser ab.)
    """
    height, width = elevation.shape
    wind = wind_bands(latitudes(height))
    is_water = elevation < sea_level
    moisture = np.ones((height, width), dtype=float)
    rainfall = np.zeros((height, width), dtype=float)
    inland_loss = 1.0 / cfg.moisture_range

    for row in range(height):
        # In Windrichtung marschieren: die Luft kommt von der Luv-Kante der Zeile.
        columns = range(width) if wind[row] == WEST else range(width - 1, -1, -1)
        carry = 1.0             # Feuchte der Luftmasse (1 = gesaettigt)
        upwind_height = sea_level  # sie kommt ueber dem offenen Meer herein
        for col in columns:
            here = float(elevation[row, col])
            if is_water[row, col]:
                carry = 1.0     # ueber dem Ozean laedt sie sich wieder auf
                moisture[row, col] = 1.0
            else:
                rise = max(0.0, here - upwind_height)
                lift = min(1.0, rise / cfg.orographic_scale)  # 0..1: wie steil es aufwaerts geht
                # Die ANKOMMENDE Luft traegt die Feuchte dieser Zelle; am Luvhang regnet
                # sie zusaetzlich ab (deshalb ist der Luvhang nass, nicht bloss "nicht trocken").
                moisture[row, col] = min(1.0, carry * (1.0 + _WINDWARD_BONUS * lift))
                # ... und genau das fehlt ihr danach: was faellt, faellt HIER.
                loss = min(1.0, inland_loss + cfg.rain_shadow_strength * lift)
                rainfall[row, col] = carry * loss
                carry *= 1.0 - loss
            upwind_height = here

    # Die Absinkzone der Rossbreiten legt sich ueber alles: sie macht trocken, was der
    # Wind eigentlich befeuchtet haette — und zwar beides, die Feuchte wie den Regen.
    band = circulation(latitudes(height), cfg)[:, None]
    moisture *= band
    rainfall *= band
    moisture[is_water] = 1.0
    rainfall[is_water] = 0.0
    return np.clip(moisture, 0.0, 1.0), rainfall
