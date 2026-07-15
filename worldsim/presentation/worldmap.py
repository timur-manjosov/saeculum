"""worldmap — die Karte: Geologie, Klima und politische Territorien in einer Ansicht.

Reine **Visualisierung ueber dem Adjazenzgraphen**. Die Regionen tragen eine
geografische Koordinate (aus worldgen, Determinismus-Vertrag); hier wird daraus eine
Ansicht in drei Lagen:

1. **Meer** kommt aus :mod:`worldsim.presentation.terrain` — Graben, Tiefsee, Schelf und
   Kuestensaum sind geologische Tatsachen (siehe :func:`_water_style`);
2. **Land** kommt aus :mod:`worldsim.presentation.climate` — jede Landzelle traegt das
   Biom, das Temperatur und Feuchte aus ihr machen. Die Gebirgsketten bleiben lesbar,
   weil hohe Kaemme alpinen Fels und Schnee tragen und die Biombaender an ihnen knicken;
3. **Suesswasser** kommt aus :mod:`worldsim.presentation.hydrology` — Fluesse, Seen und
   Muendungen liegen ueber Biom und Territorium. Sie sind die sichtbarste Kausalkette der
   Karte: der Regen des Klimas laeuft durch die Taeler der Tektonik ins Meer;
4. **Territorien**: jede Landzelle faellt an die naechstgelegene Region (Voronoi ueber
   dem Graphen); gehoert die einer Polity, wird sie zur **Politik** — und die liegt
   leuchtend ueber der gedaempften Natur (Schritt 5, siehe unten).

Das **Kernprinzip der politischen Lesbarkeit**: Natur gedaempft, Politik leuchtend.
Unbeanspruchtes Land traegt das volle Terrain (Biom, Hillshading, Fluesse), aber
**entsaettigt und abgedunkelt** (:func:`_muted_nature`) — es ist Landschaft, kein
Anspruch. Beanspruchtes Land traegt die **kraeftige Farbe seiner Polity**, durch die das
Relief noch durchscheint (die Hillshading-Helligkeit moduliert die Farbe,
:func:`_territory_style`) — man sieht in einer Zelle beides: wem sie gehoert UND wie das
Land aussieht. Der Helligkeits-/Saettigungskontrast traegt die Ablesbarkeit, nicht die
Farbwahl. Als Redundanz fuer farbschwache Augen bekommt jede Polity zusaetzlich eine
eigene **Glyphe** (:data:`_POLITY_GLYPHS`); Nachbar-Polities werden per Graphfaerbung
(:func:`_polity_styles`) klar unterschiedlich eingefaerbt. **Grenzzellen** (an eine andere
Polity oder an freies Land/Meer grenzend) werden akzentuiert, damit ein Reich als
zusammenhaengendes Gebilde heraustritt; die **Hauptstadt** traegt einen deutlichen Sitz-
Marker. Eine kompakte **Legende** unter der Karte nennt die groessten Reiche (Farbe +
Glyphe) und die wichtigsten Terrain-Zeichen.

Die Farben liegen in **zwei** Paletten, und das ist Absicht: die Natur traegt echte
Erdtoene (:class:`~worldsim.presentation.palette.TerrainPalette` — Ozean in Tiefenstufen,
Sand, gestaffelte Gruentoene, Fels und Schnee), waehrend die Rosé-Pine-Akzente der
*Bedeutung* vorbehalten bleiben (Polity-Flaechen, Ereignisse, Chrome). So kann das Land
natuerlich aussehen, ohne dass ein Reich in der Landschaft untergeht.

Read-only, kein semantischer RNG, keine Simulationslogik, **keine** Tile-Mikrosimulation
oder Geografie-Physik — nur eine Ansicht ueber dem fertigen Hoehenfeld.
"""

from __future__ import annotations

import math

import numpy as np
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from worldsim.config import DEFAULT_MAP_CONFIG, MapConfig
from worldsim.models import EntityId, World
from worldsim.presentation.climate import Biome, latitudes
from worldsim.presentation.flow import NEIGHBOURS
from worldsim.presentation.hydrology import STREAM_FACTOR, Hydrology, build_hydrology
from worldsim.presentation.palette import NATURAL_EARTH as N
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

# Zeichenzellen sind etwa doppelt so hoch wie breit (dasselbe ``_CHAR_RATIO`` wie in
# :mod:`terrain`). Die Hoehenschattierung braucht das, damit ein Nord-Sued-Hang nicht
# doppelt so steil erscheint wie ein gleich hoher Ost-West-Hang.
_CHAR_RATIO = 2.0

# Das Meer in vier Tiefenstufen — dunkles Blau in der Tiefe, hell am Saum. Das ist die
# raeumliche Tiefe der Karte: der helle Kuestensaum zeichnet JEDE Kueste nach, dahinter
# faellt der Schelf ab, dann die offene Tiefsee, und im Graben ist es fast schwarzblau.
# Die Glyphe wird dichter mit der Tiefe, der Ton (aus der Erdpalette) dunkler.
_COAST = ("~", N.coast)      # Wasser mit Landnachbar: die Kuestenlinie, hell
_SHELF = ("≈", N.shelf)      # flaches Wasser ueber ersoffenem Sockel
_DEEP_SEA = ("≈", N.deep_sea)  # offene Tiefsee — dieselbe Glyphe, dunkler Ton
_TRENCH = ("≋", N.abyss)     # der Abgrund

# Das Suesswasser tritt HELL und in einem KUEHLEREN Blau als das Meer heraus — es ist der
# Faden, an dem man die Welt liest, und liegt flach (unbeschattet), damit es nicht im
# Relief untergeht. Der See traegt die Wasser-Glyphe des Meeres: eine Flaeche aus ``≈``
# mitten im Land liest sich als Wasserkoerper — vom Bergsee bis zum ertrunkenen Graben.
_LAKE = ("≈", N.lake)
_MOUTH = ("Δ", N.stream)  # dort, wo ein grosser Strom das Meer erreicht
# Die Flussglyphe folgt der Abflussrichtung: eine Linie, die man verfolgen kann. Der
# Strom (viel Akkumulation) bekommt die schwere Variante — die Breite eines Flusses ist
# nichts anderes als sein Durchfluss.
_RIVER_GLYPHS: dict[tuple[int, int], tuple[str, str]] = {
    (0, -1): ("─", "━"), (0, 1): ("─", "━"),
    (-1, 0): ("│", "┃"), (1, 0): ("│", "┃"),
    (-1, -1): ("╲", "╲"), (1, 1): ("╲", "╲"),
    (-1, 1): ("╱", "╱"), (1, -1): ("╱", "╱"),  # noqa: RUF001 — Kastengrafik, kein Schrägstrich
}

# Die Landglyphe kommt aus dem KLIMA (Biom), der Ton aus der Erdpalette. Die Glyphe traegt
# das Detail — welches Biom —, die Hoehe liest man an zweierlei: die hohen Kaemme tragen
# eigene Glyphen (``▲`` Fels, ``*`` Schnee) UND das ganze Land ist hoehenschattiert
# (:func:`_hillshade`), sodass Huegel und Gebirge plastisch aus der Ebene treten. Die
# Glyphen steigen grob in der Dichte mit der Hoehe an — von der leeren Ebene (``"`` ``,``)
# ueber Wald (``&`` ``#``) und Wueste (``░``) bis zum Gipfelzeichen (``▲``).
#
# Die Toene sind jetzt Erdfarben statt Rosé-Pine: Gruen gestaffelt fuer Vegetation,
# Sand/Bernstein fuer Trockenland, Grau/Weiss fuer Fels und Schnee.
_BIOME_STYLE: dict[Biome, tuple[str, str]] = {
    Biome.GLETSCHER: ("*", N.snow),
    Biome.ALPIN: ("▲", N.alpine),
    Biome.TUNDRA: ("-", N.tundra),
    Biome.TAIGA: ("^", N.taiga),
    Biome.GEMAESSIGTER_WALD: ("&", N.forest),
    Biome.REGENWALD: ("#", N.rainforest),
    Biome.FEUCHTGEBIET: ("=", N.wetland),
    Biome.GRASLAND: ('"', N.grassland),
    Biome.STEPPE: (",", N.steppe),
    Biome.SAVANNE: (";", N.savanna),
    Biome.WUESTE: ("░", N.desert),
}

# Polity-Farben (kraeftig) aus der Rosé-Pine-Palette und je eine unterscheidbare Glyphe
# parallel dazu. Beide sind an DENSELBEN Index gebunden: wer eine andere Farbe bekommt,
# bekommt auch eine andere Glyphe — so bleibt Besitz auch fuer farbschwache Augen lesbar
# (Aufgabe 2). Die Reihenfolge ist nach Distinktheit sortiert: die ersten Akzente sind am
# weitesten voneinander entfernt, damit die groessten (zuerst gefaerbten) Reiche klar
# auseinanderfallen. Die Glyphen sind bewusst geometrische Formen aus dem Block "Geometric
# Shapes" (U+25xx) — nahezu universell in Terminal-Schriften vorhanden (Stern-/Kreuzformen
# wie ``★ ✦`` fehlen dagegen selbst in vollen Nerd Fonts) — und kollidieren mit KEINER
# Biom-/Wasserglyphe (``● ■ ◆ ◉ ◈ ○ □`` gegen ``" , ; & # ░ ▲ ^ ~ ≈``). Die vorderen,
# haeufigsten Indizes tragen die silhouetten-verschiedensten Formen (Kreis/Quadrat/Raute).
_POLITY_TONES: tuple[str, ...] = (P.love, P.gold, P.iris, P.foam, P.rose, P.pine, P.text)
_POLITY_GLYPHS: tuple[str, ...] = ("●", "■", "◆", "◉", "◈", "○", "□")

# Die Legende (Aufgabe 5) nennt neben den Reichen die wichtigsten Terrain-Zeichen — je
# Eintrag (Glyphe, Ton, Etikett). Bewusst knapp: die haeufigsten/lesbarsten Signale.
_TERRAIN_KEY: tuple[tuple[str, str, str], ...] = (
    ("≈", N.deep_sea, "sea"),
    ("~", N.coast, "coast"),
    ("━", N.stream, "river"),
    ("▲", N.alpine, "mountains"),
    ("&", N.forest, "forest"),
    ("░", N.desert, "desert"),
)


def _water_style(
    depth: float, relief: float, oceanic: bool, coastal: bool
) -> tuple[str, str]:
    """Wasser ⇒ (Glyphe, Ton). Das entscheidet weiter die Geologie, nicht das Klima.

    ``depth`` ist die Tiefe unter dem Meeresspiegel, ``relief`` die Hoehe ueber der
    eigenen Krustenbasis. Jeder Zweig sagt eine geologische Tatsache: ein Graben ist unter
    die eigene Kruste gerissener Meeresboden, ein Schelf ist ersoffener Kontinentalsockel.
    Nur der Kuestensaum ist keine Tatsache ueber die Tiefe, sondern eine ueber die Naehe —
    er zeichnet die Linie nach, an der Land und Meer sich beruehren.
    """
    if coastal:
        return _COAST
    if oceanic and relief <= _TRENCH_RELIEF:
        return _TRENCH                 # die Subduktion hat den Meeresboden weggerissen
    if not oceanic or depth > -_SHELF_DEPTH:
        # Ersoffener Kontinentalsockel oder flaches Randmeer. Auch ein gefluteter
        # Grabenbruch faellt hierher — ein Rift auf Kontinentalkruste ist ein Binnenmeer,
        # kein Abgrund.
        return _SHELF
    return _DEEP_SEA


def _river_style(water: Hydrology, row: int, col: int, threshold: float) -> tuple[str, str]:
    """Fluss ⇒ (Glyphe, Ton). Die Linie zeigt, wohin er laeuft; die Staerke, wie gross er ist."""
    step = water.flows_to(row, col) or (0, 1)
    light, heavy = _RIVER_GLYPHS[step]
    is_stream = float(water.flow[row, col]) >= STREAM_FACTOR * threshold
    return (heavy, N.stream) if is_stream else (light, N.river)


def _hillshade(elevation: np.ndarray, cfg: MapConfig) -> np.ndarray:
    """Beleuchte das Relief aus Nordwesten ⇒ ein Helligkeits-Faktor (~0.4..1.75) je Zelle.

    Kein 3D-Rendering, nur die eine billige Rechnung, die einer flachen Karte sofort
    Plastik gibt: der Neigungsvektor jeder Zelle wird gegen einen schraeg von oben-links
    einfallenden Lichtstrahl gehalten. Zum Licht geneigte Haenge kommen ueber 1.0 (heller),
    abgewandte darunter (dunkler); die Ebene bleibt bei 1.0. Der Faktor skaliert am Ende
    nur die Helligkeit des ohnehin gewaehlten Erd-/Wassertons — er aendert weder Glyphe
    noch Farbton, also bleibt Biom und Tiefe lesbar.

    Zwei Feinheiten: die Zeilen-Steigung wird durch ``_CHAR_RATIO`` geteilt (die Zelle ist
    doppelt so hoch wie breit, ein Nord-Sued-Hang also scheinbar steiler), und das Gefaelle
    wird vorher ueberhoeht (``hillshade_exaggeration``), weil die Hoehenunterschiede je
    Zelle sonst zu klein fuer sichtbare Schatten sind.
    """
    az = math.radians(cfg.hillshade_azimuth)
    alt = math.radians(cfg.hillshade_altitude)
    grad_row, grad_col = np.gradient(elevation.astype(float))
    grad_col = grad_col * cfg.hillshade_exaggeration
    grad_row = grad_row * cfg.hillshade_exaggeration / _CHAR_RATIO

    # Lichtvektor: Azimut auf den Bildschirm gelegt (Nord = oben = -Zeile, Ost = +Spalte),
    # Hoehe ueber dem Horizont als z. Die Flaechennormale ist (-d/dSpalte, -d/dZeile, 1).
    light_col = math.cos(alt) * math.sin(az)
    light_row = -math.cos(alt) * math.cos(az)
    light_up = math.sin(alt)
    normal_len = np.sqrt(grad_col * grad_col + grad_row * grad_row + 1.0)
    illum = (-grad_col * light_col - grad_row * light_row + light_up) / normal_len

    # Die flache Flaeche beleuchtet der Strahl mit ``sin(alt)``; das ist der Nullpunkt, um
    # den herum der Kontrast die Helligkeit auf- und abschwingen laesst.
    flat = math.sin(alt)
    factor = 1.0 + cfg.hillshade_contrast * (illum - flat) / flat
    return np.clip(factor, 0.4, 1.75)


def _shade(color: str, factor: float) -> str:
    """Skaliere die Helligkeit eines ``#rrggbb``-Tons mit dem Hillshade-Faktor."""
    red = min(255, max(0, round(int(color[1:3], 16) * factor)))
    green = min(255, max(0, round(int(color[3:5], 16) * factor)))
    blue = min(255, max(0, round(int(color[5:7], 16) * factor)))
    return f"#{red:02x}{green:02x}{blue:02x}"


def _desaturate(color: str, amount: float) -> str:
    """Ziehe einen ``#rrggbb``-Ton anteilig zu seinem Grauwert (``amount`` 0..1)."""
    red, green, blue = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    grey = 0.299 * red + 0.587 * green + 0.114 * blue  # wahrgenommene Helligkeit
    red = round(red + (grey - red) * amount)
    green = round(green + (grey - green) * amount)
    blue = round(blue + (grey - blue) * amount)
    return f"#{red:02x}{green:02x}{blue:02x}"


def _muted_nature(color: str, factor: float, cfg: MapConfig) -> str:
    """Unbeanspruchtes Land: entsaettigt, gedaempft, hoehenschattiert (das Kernprinzip).

    Die Natur soll Landschaft bleiben, nicht mit der Politik um Aufmerksamkeit ringen —
    also erst zu Grau ziehen, dann abdunkeln, dann die Reliefschattierung darauflegen. So
    treten die kraeftigen Polity-Toene hervor, ohne dass Biom oder Relief unlesbar werden.
    """
    return _shade(_desaturate(color, cfg.nature_desaturation), factor * cfg.nature_dim)


_BORDER_BRIGHTEN = 1.22  # Grenzzelle: heller als das hellste Innere ⇒ ein klarer Umriss


def _territory_style(tone: str, factor: float, cfg: MapConfig, *, border: bool) -> str:
    """Beanspruchtes Land: die Polity-Farbe, durch die das Relief scheint.

    Die Hillshading-Helligkeit ``factor`` moduliert die Farbe nur zum Anteil
    ``territory_relief`` — genug, dass Berg und Tal durchkommen, nicht so viel, dass die
    Farbe kippt. **Grenzzellen** werden aufgehellt und fett gesetzt, das Innere dagegen nie
    heller als der Rand: so umreisst ein heller, geschlossener Saum jedes Reich (Aufgabe 3).
    """
    if border:
        return f"bold {_shade(tone, _BORDER_BRIGHTEN)}"
    relief = 1.0 + (factor - 1.0) * cfg.territory_relief
    return _shade(tone, min(relief, _BORDER_BRIGHTEN - 0.06))


def _coastline(is_sea: np.ndarray) -> np.ndarray:
    """Meerzellen mit mindestens einem Landnachbarn — die Kuestenlinie."""
    height, width = is_sea.shape
    # Gepolstert statt gerollt: der Kartenrand ist keine Kueste, sondern ein Rand.
    land = np.pad(~is_sea, 1, constant_values=False)
    touches = np.zeros_like(is_sea)
    for drow, dcol in NEIGHBOURS:
        touches |= land[1 + drow : 1 + drow + height, 1 + dcol : 1 + dcol + width]
    return is_sea & touches


# Breitengrad-Marken am linken Rand: sie sagen dem Auge, dass dies ein PLANET ist und
# keine Ebene — die Karte spannt Pol zu Pol, mit Aequator, Rossbreiten und Polarfront an
# ihren festen Breiten. Es ist die billige Andeutung einer Projektion (Aufgabe 5), ohne
# eine echte Projektion zu rechnen oder Kartendaten zu verdecken.
_LAT_TICKS: tuple[tuple[float, str], ...] = (
    (60.0, "60N"), (30.0, "30N"), (0.0, "EQ"), (-30.0, "30S"), (-60.0, "60S")
)
_AXIS_WIDTH = 4  # 3 Zeichen Marke + 1 Trennspalte


def _latitude_axis(height: int) -> list[str]:
    """Fuer jede Zeile die Beschriftung der linken Breitengrad-Skala (je ``_AXIS_WIDTH``)."""
    lat = latitudes(height)
    axis = [" " * _AXIS_WIDTH] * height
    for degrees, label in _LAT_TICKS:
        row = int(np.argmin(np.abs(lat - degrees)))
        axis[row] = f"{label:>3s} "  # rechtsbuendig, dann die Trennspalte
    return axis


def _nearest_region(coords: np.ndarray, width: int, height: int) -> np.ndarray:
    """Fuer jede Zelle den Index der naechstgelegenen Region (Voronoi ueber Koordinaten)."""
    xs = (np.arange(width) + 0.5) / width
    ys = (np.arange(height) + 0.5) / height
    gx, gy = np.meshgrid(xs, ys)  # (H, W)
    dx = gx[..., None] - coords[:, 0]  # (H, W, N)
    dy = gy[..., None] - coords[:, 1]
    return (dx * dx + dy * dy).argmin(axis=2)  # (H, W) ⇒ Index in coords


def _owner_grid(
    owner_of: dict[EntityId, EntityId], nearest: np.ndarray, rids: list[EntityId],
    is_sea: np.ndarray,
) -> np.ndarray:
    """Je Landzelle die Polity-Id ihres Eigners (``-1`` = frei oder Meer).

    Das gemeinsame Raster fuer Grenzerkennung und Polity-Nachbarschaft: eine Landzelle
    faellt an die naechste Region (Voronoi), deren Eigner — falls vorhanden — die Zelle
    beansprucht. Meer traegt nie Territorium (Ozeane trennen Land), also ``-1``.
    """
    height, width = is_sea.shape
    grid = np.full((height, width), -1, dtype=int)
    for row in range(height):
        for col in range(width):
            if is_sea[row, col]:
                continue
            owner = owner_of.get(rids[int(nearest[row, col])])
            if owner is not None:
                grid[row, col] = owner
    return grid


def _borders(owner_grid: np.ndarray) -> np.ndarray:
    """Beanspruchte Zellen, die an einen ANDEREN Eigner (oder freies Land/Meer) grenzen.

    Der Umriss eines Reiches: eine Territorialzelle ist Grenze, wenn eine ihrer vier
    orthogonalen Nachbarn einem anderen Eigner gehoert, frei ist oder ausserhalb der Karte
    liegt (der Kartenrand zaehlt als Grenze). Vier- statt achtverbunden ⇒ ein sauberer,
    ein Zeichen breiter Saum.
    """
    owned = owner_grid >= 0
    border = np.zeros_like(owned)
    for drow, dcol in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        shifted = np.full_like(owner_grid, -2)  # ausserhalb ⇒ -2 (immer "anders")
        src = np.roll(np.roll(owner_grid, -drow, axis=0), -dcol, axis=1)
        rs = slice(max(0, -drow), owner_grid.shape[0] - max(0, drow))
        cs = slice(max(0, -dcol), owner_grid.shape[1] - max(0, dcol))
        shifted[rs, cs] = src[rs, cs]
        border |= owned & (shifted != owner_grid)
    return border


def _polity_styles(
    world: World, owner_grid: np.ndarray,
) -> dict[EntityId, int]:
    """Weise jeder Polity einen Farb-/Glyphen-Index zu, sodass Nachbarn sich unterscheiden.

    Gierige Graphfaerbung ueber der aus dem Territorium abgelesenen Nachbarschaft (Aufgabe
    2): die Polities werden in stabiler Id-Reihenfolge gefaerbt (damit die Farbe ueber die
    Jahre nicht flackert), jede nimmt bevorzugt ihren rang-eigenen Ton und weicht nur aus,
    wenn ein bereits gefaerbter Nachbar ihn schon traegt. Bei ≤7 Toenen und der geringen
    Grenz-Valenz einer Polity reichen die Toene immer — kollidierende Nachbarn bekommen
    verlaesslich verschiedene Farben (und damit auch verschiedene Glyphen).
    """
    height, width = owner_grid.shape
    adjacency: dict[EntityId, set[EntityId]] = {}
    for row in range(height):
        for col in range(width):
            here = int(owner_grid[row, col])
            if here < 0:
                continue
            for drow, dcol in ((1, 0), (0, 1)):  # nur zwei Richtungen ⇒ jedes Paar einmal
                nrow, ncol = row + drow, col + dcol
                if nrow >= height or ncol >= width:
                    continue
                other = int(owner_grid[nrow, ncol])
                if other >= 0 and other != here:
                    adjacency.setdefault(here, set()).add(other)
                    adjacency.setdefault(other, set()).add(here)

    ntones = len(_POLITY_TONES)
    ranks = {pid: i for i, pid in enumerate(sorted(world.polities))}
    style: dict[EntityId, int] = {}
    for pid in sorted(world.polities):
        used = {style[n] for n in adjacency.get(pid, ()) if n in style}
        base = ranks[pid] % ntones
        # Bevorzugt den rang-eigenen Ton, sonst den naechsten freien (rotierend).
        choice = next(
            ((base + k) % ntones for k in range(ntones) if (base + k) % ntones not in used),
            base,  # mehr Nachbarn als Toene: faellt auf die Basis zurueck (praktisch nie)
        )
        style[pid] = choice
    return style


def _legend(
    world: World, owner_grid: np.ndarray, style: dict[EntityId, int], *, max_named: int = 6
) -> Text:
    """Die kompakte Legende unter der Karte: groesste Reiche und Terrain-Zeichen (Aufgabe 5).

    Reiche nach Territoriumsgroesse (aus dem Raster gezaehlt, damit die Legende exakt zur
    gezeigten Karte passt); bei vielen werden nur die groessten namentlich genannt, der
    Rest als ``+k more`` zusammengefasst. Farbe UND Glyphe je Reich — dieselben, mit denen
    die Karte es malt.
    """
    ids, counts = np.unique(owner_grid[owner_grid >= 0], return_counts=True)
    sizes = dict(zip(ids.tolist(), counts.tolist(), strict=True))
    ranked = sorted(sizes, key=lambda p: (sizes[p], -p), reverse=True)

    realms = Text("realms  ", style=P.subtle)
    if not ranked:
        realms.append("— none claimed —", style=P.muted)
    for pid in ranked[:max_named]:
        idx = style.get(pid, 0)
        tone = _POLITY_TONES[idx]
        realms.append(_POLITY_GLYPHS[idx], style=f"bold {tone}")
        realms.append(f" {world.polities[pid].name}   ", style=tone)
    if len(ranked) > max_named:
        realms.append(f"+{len(ranked) - max_named} more", style=P.muted)

    terrain = Text("terrain ", style=P.subtle)
    for glyph, tone, label in _TERRAIN_KEY:
        terrain.append(glyph, style=tone)
        terrain.append(f" {label}   ", style=P.muted)

    legend = Text()
    legend.append_text(realms)
    legend.append("\n")
    legend.append_text(terrain)
    return legend


def render_map(
    world: World,
    seed: int = 0,
    owners: dict[EntityId, EntityId] | None = None,
    *,
    width: int = MAP_WIDTH,
    height: int = MAP_HEIGHT,
    flash: frozenset[EntityId] = frozenset(),
) -> Panel:
    """Rendere die Karte als ``rich``-Panel: gedaempftes Terrain plus leuchtende Politik.

    ``owners`` erlaubt es dem Replay, einen **rekonstruierten** Besitzstand zu zeigen;
    ohne Angabe gilt der aktuelle Weltzustand (so wandern im Watch-Mode die Grenzen Jahr
    fuer Jahr). Unbeanspruchtes Land traegt das entsaettigte, gedaempfte Terrain; wem eine
    Zelle gehoert, faerbt sie in der kraeftigen Farbe seiner Polity (mit durchscheinendem
    Relief) und traegt deren Glyphe. Grenzen werden akzentuiert, die Hauptstadt markiert.
    ``flash`` (Regionen-Ids, im Watch-Modus die eben gewechselten) laesst deren Zellen kurz
    aufblitzen. Unter der Karte steht eine kompakte Legende (Reiche + Terrain-Zeichen).
    """
    rids = sorted(world.regions)
    if not rids:
        return Panel(Text("(no regions)", style=P.muted), title=f"world map · seed {seed}")

    coords = np.array([world.regions[rid].coord for rid in rids], dtype=float)
    water = build_hydrology(seed, width, height)  # einmal je Welt (gecacht), nie pro Tick
    climate, terrain = water.climate, water.terrain
    relief, oceanic = terrain.relief, terrain.oceanic
    elevation = np.asarray(terrain.elevation)
    is_sea = elevation < terrain.sea_level
    coastal = _coastline(is_sea)
    cfg = DEFAULT_MAP_CONFIG
    threshold = cfg.river_threshold

    # Hoehenschattierung: einmal je Render aus dem Hoehenfeld gerechnet (reine Numerik,
    # kein Zufall). Unter Wasser nur gedaempft — die glatte See soll nicht flimmern.
    shade = _hillshade(elevation, cfg)
    water_shade = 1.0 + (shade - 1.0) * cfg.hillshade_water
    nearest = _nearest_region(coords, width, height)
    owner_of = (
        owners
        if owners is not None
        else {rid: r.owner for rid, r in world.regions.items() if r.owner is not None}
    )

    # Die politische Lage: Besitzraster (Meer traegt nie Territorium), Grenzumriss und je
    # Polity ein unterscheidbarer Stil (Farbe + Glyphe, Nachbarn verschieden gefaerbt).
    owner_grid = _owner_grid(owner_of, nearest, rids, is_sea)
    border = _borders(owner_grid)
    style = _polity_styles(world, owner_grid)

    # Hauptstadt-Marker: nur wo die Polity ihren Sitz aktuell auch haelt.
    cap_cell: dict[tuple[int, int], EntityId] = {}
    for pid in sorted(world.polities):
        cap = world.polities[pid].capital
        if cap is not None and cap in world.regions and owner_of.get(cap) == pid:
            cx, cy = world.regions[cap].coord
            col = min(width - 1, int(cx * width))
            row = min(height - 1, int(cy * height))
            cap_cell[(row, col)] = pid

    axis = _latitude_axis(height)  # linke Breitengrad-Skala (Aufgabe 5: es ist ein Planet)

    text = Text()
    for row in range(height):
        text.append(axis[row], style=P.muted)
        for col in range(width):
            pid = cap_cell.get((row, col))
            if pid is not None:
                # Hauptstadt: der Sitz als deutlicher Chip — die Initiale der Polity, fett
                # in ihrem kraeftigen Ton auf dunklem Grund (Aufgabe 4). Wird zuerst
                # gezeichnet, also auch sichtbar, falls der Sitz auf Wasser faellt.
                letter = world.polities[pid].name[:1] or "?"
                text.append(letter, style=f"bold {_POLITY_TONES[style.get(pid, 0)]} on {P.overlay}")
                continue
            if is_sea[row, col]:  # Wasser: das entscheidet die Geologie, nicht das Klima
                if water.mouth[row, col]:
                    glyph, tone = _MOUTH  # hier erreicht ein Strom das Meer
                    text.append(glyph, style=_shade(tone, float(water_shade[row, col])))
                    continue
                glyph, tone = _water_style(
                    float(elevation[row, col]) - terrain.sea_level,
                    float(relief[row, col]),
                    bool(oceanic[row, col]),
                    bool(coastal[row, col]),
                )
                text.append(glyph, style=_shade(tone, float(water_shade[row, col])))
                continue

            # Suesswasser liegt UEBER dem Biom und ueber dem Territorium: ein Fluss ist
            # kein Untergrund, auf dem man siedelt, sondern die Linie, an der man siedelt.
            # Es liegt FLACH (unbeschattet): der helle Wasserfaden soll das Relief queren,
            # nicht in seinem Schatten verschwinden.
            if water.lake[row, col]:
                glyph, tone = _LAKE
                text.append(glyph, style=tone)
                continue
            if water.river[row, col]:
                glyph, tone = _river_style(water, row, col, threshold)
                text.append(glyph, style=tone)
                continue

            glyph, tone = _BIOME_STYLE[climate.biome[row, col]]
            owner = int(owner_grid[row, col])
            if owner < 0:
                # Natur: entsaettigt, gedaempft, hoehenschattiert — sie tritt zurueck,
                # damit die Politik leuchtet (das Kernprinzip von Schritt 5).
                text.append(glyph, style=_muted_nature(tone, float(shade[row, col]), cfg))
                continue

            idx = style.get(owner, 0)
            ptone = _POLITY_TONES[idx]
            if flash and rids[int(nearest[row, col])] in flash:
                # Frischer Besitzwechsel (Watch-Modus, Aufgabe 6): kurz hell aufblitzen.
                text.append(_POLITY_GLYPHS[idx], style=f"bold {P.text} on {ptone}")
                continue
            # Beanspruchtes Land: die Polity-Glyphe (Redundanz zur Farbe) in der Polity-
            # Farbe, durch die das Relief scheint; Grenzzellen kraeftig als heller Umriss.
            text.append(
                _POLITY_GLYPHS[idx],
                style=_territory_style(
                    ptone, float(shade[row, col]), cfg, border=bool(border[row, col])
                ),
            )
        if row != height - 1:
            text.append("\n")

    legend = _legend(world, owner_grid, style)  # Aufgabe 5: Reiche + Terrain-Zeichen
    return Panel(
        Group(text, Text(), legend),
        title=f"world map · seed {seed}",
        title_align="left",
        border_style=P.muted,
    )
