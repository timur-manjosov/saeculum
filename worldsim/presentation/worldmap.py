"""worldmap — die Karte: Geologie, Klima und politische Territorien in einer Ansicht.

Reine **Visualisierung ueber dem Adjazenzgraphen**. Die Regionen tragen eine
geografische Koordinate (aus worldgen, Determinismus-Vertrag); hier wird daraus eine
Ansicht in drei Lagen:

1. **Wasser** kommt aus :mod:`worldsim.presentation.terrain` — Graben, Tiefsee, Schelf
   sind geologische Tatsachen (siehe :func:`_water_style`);
2. **Land** kommt aus :mod:`worldsim.presentation.climate` — jede Landzelle traegt das
   Biom, das Temperatur und Feuchte aus ihr machen. Die Gebirgsketten bleiben lesbar,
   weil hohe Kaemme alpinen Fels und Schnee tragen und die Biombaender an ihnen knicken;
3. **Territorien**: jede Landzelle faellt an die naechstgelegene Region (Voronoi ueber
   dem Graphen); gehoert die einer Polity, faerbt sich die Zelle **kraeftig** in deren
   Farbe — die Glyphe bleibt das Biom, man sieht also weiterhin, WORAUF ein Reich sitzt.

Farben aus der Rosé-Pine-Moon-Palette: das Land in drei Familien (gruen = bewachsen,
bernstein = trocken, grau/weiss = kalt), gedaempft gerendert, damit es zuruecktritt; die
Polity-Akzente treten als kraeftige Flaechen hervor. Read-only, kein semantischer RNG,
keine Simulationslogik, **keine** Tile-Mikrosimulation oder Geografie-Physik.
"""

from __future__ import annotations

import numpy as np
from rich.panel import Panel
from rich.text import Text

from worldsim.models import EntityId, World
from worldsim.presentation.climate import Biome, build_climate
from worldsim.presentation.palette import ROSE_PINE_MOON as P
from worldsim.presentation.terrain import MAP_HEIGHT, MAP_WIDTH

__all__ = ["render_map"]

# Biome als Schwellen ueber der Hoehe **relativ zum Meeresspiegel** ⇒
# (Grenze, Glyphe, Ton, ist_Wasser). Der Ton laeuft als Helligkeitsrampe vom Abgrund
# zum Gipfel. Wasser traegt nie Territorium — Ozeane trennen Land.
# Die Biome lesen das **Relief** — die Hoehe ueber der eigenen Krustenbasis —, nicht die
# Hoehe ueber dem Meeresspiegel. Der schwimmt naemlich mit dem Verhaeltnis kontinentaler
# zu ozeanischer Flaeche: in einer Welt mit wenig Kontinent sinkt er fast auf den
# Ozeanboden, und dann ragt der ganz gewoehnliche Kontinentalsockel weit ueber ihn — an
# absoluten Schwellen gemessen waere ein solcher Kontinent restlos "Gebirge", ganz ohne
# Hebung (gemessen: einzelne Seeds zu 95 % Bergland). Am Relief gemessen luegt nichts:
# eine Ebene liegt auf ihrer Kruste (Median +0.02), ein Ozeanboden auch (-0.02) — nur
# Orogenese und Subduktion schieben eine Zelle davon weg.
#
# Geeicht an der gemessenen Relief-Verteilung ueber 60 Seeds (Land p90 +0.47, p97 +0.95;
# ausgewaschener Ozeanboden p10 -0.40, p2 -1.09).
# Die beiden Landschwellen teilen sich die Arbeit genau wie die beiden Hoehenquellen:
# Huegel liegen auf der Skala des fBm (die Detailrauheit reicht bis ~0.08) — deshalb
# traegt JEDE Welt Huegel. Gebirge liegen auf der Skala der Tektonik, die das Rauschen um
# ein Vielfaches ueberragt — deshalb traegt nur eine Welt mit Konvergenz Gebirge.
_HILL_RELIEF = 0.08    # darueber: gewellt (Huegel) — das macht schon das Rauschen
_PEAK_RELIEF = 0.35    # darueber: Gebirge — das macht nur die Tektonik
_TRENCH_RELIEF = -0.55  # darunter: unter die eigene Kruste gerissen ⇒ Tiefseegraben
_SHELF_DEPTH = 0.20    # so flach unter dem Meeresspiegel gilt Wasser als Kuestensaum

_DEEP_SEA = ("≈", P.pine)
_SHELF = ("~", P.foam)
_TRENCH = ("≋", P.highlight_high)

# Die Landglyphen kommen jetzt aus dem KLIMA, nicht mehr aus der Hoehe: eine Zelle ist,
# was Temperatur und Feuchte aus ihr machen. Die Ketten bleiben trotzdem lesbar — hohe
# Kaemme tragen alpinen Fels und Schnee, und die Biombaender KNICKEN an ihnen (nasser
# Luvwald, trockener Lee-Schatten), was mehr ueber sie sagt als eine Hoehenglyphe.
#
# Drei Farbfamilien tragen die Bedeutung, die Glyphe traegt das Detail:
# gruen = bewachsen, bernstein = trocken, grau/weiss = kalt.
_BIOME_STYLE: dict[Biome, tuple[str, str]] = {
    Biome.GLETSCHER: ("*", P.text),
    Biome.ALPIN: ("▲", P.subtle),
    Biome.TUNDRA: ("-", P.muted),
    Biome.TAIGA: ("^", P.pine),
    Biome.GEMAESSIGTER_WALD: ("&", P.pine),
    Biome.REGENWALD: ("#", P.pine),
    Biome.FEUCHTGEBIET: ("=", P.foam),
    Biome.GRASLAND: ('"', P.pine),
    Biome.STEPPE: (",", P.gold),
    Biome.SAVANNE: (";", P.gold),
    Biome.WUESTE: ("░", P.gold),
}

# Polity-Farben (kraeftig) aus der Palette. Zuerst die terrain-fremden Akzente,
# damit die groessten Polities klar unterscheidbar bleiben; dann der Rest.
_POLITY_TONES: tuple[str, ...] = (P.love, P.gold, P.iris, P.rose, P.foam, P.pine, P.text)


def _water_style(depth: float, relief: float, oceanic: bool) -> tuple[str, str]:
    """Wasser ⇒ (Glyphe, Ton). Das entscheidet weiter die Geologie, nicht das Klima.

    ``depth`` ist die Tiefe unter dem Meeresspiegel, ``relief`` die Hoehe ueber der
    eigenen Krustenbasis. Jeder Zweig sagt eine geologische Tatsache: ein Graben ist unter
    die eigene Kruste gerissener Meeresboden, ein Schelf ist ersoffener Kontinentalsockel.
    """
    if oceanic and relief <= _TRENCH_RELIEF:
        return _TRENCH                 # die Subduktion hat den Meeresboden weggerissen
    if not oceanic or depth > -_SHELF_DEPTH:
        # Ersoffener Kontinentalsockel oder Kuestensaum. Auch ein gefluteter Grabenbruch
        # faellt hierher — ein Rift auf Kontinentalkruste ist ein Binnenmeer, kein Abgrund.
        return _SHELF
    return _DEEP_SEA


def _polity_tone(pid: EntityId, order: dict[EntityId, int]) -> str:
    """Stabile Polity-Farbe nach Rang (gleiche Polity ⇒ immer dieselbe Farbe)."""
    return _POLITY_TONES[order.get(pid, 0) % len(_POLITY_TONES)]


def _nearest_region(coords: np.ndarray, width: int, height: int) -> np.ndarray:
    """Fuer jede Zelle den Index der naechstgelegenen Region (Voronoi ueber Koordinaten)."""
    xs = (np.arange(width) + 0.5) / width
    ys = (np.arange(height) + 0.5) / height
    gx, gy = np.meshgrid(xs, ys)  # (H, W)
    dx = gx[..., None] - coords[:, 0]  # (H, W, N)
    dy = gy[..., None] - coords[:, 1]
    return (dx * dx + dy * dy).argmin(axis=2)  # (H, W) ⇒ Index in coords


def render_map(
    world: World,
    seed: int = 0,
    owners: dict[EntityId, EntityId] | None = None,
    *,
    width: int = MAP_WIDTH,
    height: int = MAP_HEIGHT,
) -> Panel:
    """Rendere die Karte als ``rich``-Panel: Terrain plus politische Territorien.

    ``owners`` erlaubt es dem Replay, einen **rekonstruierten** Besitzstand zu
    zeigen; ohne Angabe gilt der aktuelle Weltzustand (so wandern im Watch-Mode die
    Grenzen Jahr fuer Jahr). Landzellen faerben sich in der Farbe der Polity, der
    ihre naechste Region gehoert; Wasser bleibt Wasser; Hauptstaedte tragen die
    Initiale ihrer Polity.
    """
    rids = sorted(world.regions)
    if not rids:
        return Panel(Text("(no regions)", style=P.muted), title=f"world map · seed {seed}")

    coords = np.array([world.regions[rid].coord for rid in rids], dtype=float)
    climate = build_climate(seed, width, height)  # einmal je Welt (gecacht), nie pro Tick
    terrain = climate.terrain
    relief, oceanic = terrain.relief, terrain.oceanic
    nearest = _nearest_region(coords, width, height)
    owner_of = (
        owners
        if owners is not None
        else {rid: r.owner for rid, r in world.regions.items() if r.owner is not None}
    )
    order = {pid: i for i, pid in enumerate(sorted(world.polities))}

    # Hauptstadt-Marker: nur wo die Polity ihren Sitz aktuell auch haelt.
    cap_cell: dict[tuple[int, int], EntityId] = {}
    for pid in sorted(world.polities):
        cap = world.polities[pid].capital
        if cap is not None and cap in world.regions and owner_of.get(cap) == pid:
            cx, cy = world.regions[cap].coord
            col = min(width - 1, int(cx * width))
            row = min(height - 1, int(cy * height))
            cap_cell[(row, col)] = pid

    text = Text()
    for row in range(height):
        for col in range(width):
            pid = cap_cell.get((row, col))
            if pid is not None:
                letter = world.polities[pid].name[:1] or "?"
                text.append(letter, style=f"bold {_polity_tone(pid, order)}")
                continue
            biome = climate.biome[row, col]
            if biome is None:  # Wasser: das entscheidet die Geologie, nicht das Klima
                glyph, tone = _water_style(
                    float(terrain.elevation[row, col]) - terrain.sea_level,
                    float(relief[row, col]),
                    bool(oceanic[row, col]),
                )
                text.append(glyph, style=f"dim {tone}")
                continue

            glyph, tone = _BIOME_STYLE[biome]
            owner = owner_of.get(rids[int(nearest[row, col])])
            if owner is not None:
                # Die Polity faerbt die Flaeche, die Glyphe bleibt das Biom: man sieht
                # weiterhin, WORAUF ein Reich sitzt (Steppe, Regenwald, Wueste).
                text.append(glyph, style=f"bold {_polity_tone(owner, order)}")
            else:
                text.append(glyph, style=f"dim {tone}")
        if row != height - 1:
            text.append("\n")
    return Panel(text, title=f"world map · seed {seed}", title_align="left", border_style=P.muted)
