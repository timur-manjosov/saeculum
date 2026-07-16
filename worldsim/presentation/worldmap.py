"""worldmap — die Karte: Wasser, freies Land, Besitz und Grenzen auf einen Blick.

Reine **Visualisierung ueber dem Adjazenzgraphen**. Die Regionen tragen eine
geografische Koordinate (aus worldgen, Determinismus-Vertrag); hier wird daraus eine
Ansicht in vier Lagen:

1. **Meer** kommt aus :mod:`worldsim.geo.terrain` — Graben, Tiefsee, Schelf und
   Kuestensaum sind geologische Tatsachen (siehe :func:`_water_tone`);
2. **Land** kommt aus :mod:`worldsim.geo.climate` — jede Landzelle traegt das
   Biom, das Temperatur und Feuchte aus ihr machen;
3. **Suesswasser** kommt aus :mod:`worldsim.geo.hydrology` — Fluesse und Seen liegen
   ueber Biom und Territorium: der Regen des Klimas laeuft durch die Taeler der Tektonik
   ins Meer;
4. **Territorien**: jede Landzelle faellt an die naechstgelegene Region (Voronoi ueber
   dem Graphen); gehoert die einer Polity, wird sie zur **Politik**.

**Das Ordnungsprinzip (Schritt 4): die Flaeche traegt die Politik, die Glyphe das Land.**
Der Hintergrund einer Zelle beantwortet "Wasser, frei oder wessen?", und nur die Glyphe
darauf traegt die Textur (Biom, Fluss, Polity-Zeichen) — in einem Ton, der von seinem
eigenen Grund nur so weit absteht, wie er darf. Daraus faellt der Rest heraus:

- **Wasser** ist eine geschlossene, unschattierte Flaeche in vier Tiefenstufen und traegt
  **kein Zeichen**. Das ist die Invariante, die "Wasser ist nie mit Land verwechselbar"
  ueberhaupt pruefbar macht: *die See ist die einzige Flaeche ohne Glyphe* — jede Landzelle
  traegt eine, keine Wasserzelle tut es (gepinnt in
  ``test_water_is_the_only_field_without_a_sign``).
- **Freies Land** wird entsaettigt und auf EIN ruhiges Helligkeitsband gezogen
  (:func:`_quiet_land`) — es ist Landschaft, kein Anspruch.
- **Territorium** traegt die kraeftige Farbe seiner Polity (:func:`_territory_tone`): der
  **Rand den reinen Ton, flach** — daher umreisst jedes Reich ein gleichmaessiger, kraeftiger
  Saum —, das **Innere** eine Spur zurueckgenommen, durch die das Relief noch schwach
  scheint. Man sieht in einer Zelle beides: wem sie gehoert UND wie das Land liegt.

Das traegt die ganze Lesbarkeit, und zwar aus einem messbaren Grund: das Auge sortiert
zuerst nach **Helligkeit**. Vorher ueberlappten die drei Baender restlos (Wasser 29..216,
freies Land 83..236, Territorium 122..225 — eine freie Wueste strahlte jedes ``pine``-Reich
nieder). Jetzt sind sie gestapelt: **Wasser 26..86 < freies Land ~96 < Territorium 122..225**.
Erst dadurch rangiert das Bild ueberhaupt, und die Farbwahl darf Kuer sein statt Kruecke.

Als Redundanz fuer farbschwache Augen bekommt jede Polity zusaetzlich eine eigene
**Glyphe** (:data:`_POLITY_GLYPHS`); Nachbar-Polities werden per Graphfaerbung
(:func:`_polity_styles`) nicht nur verschieden, sondern **unaehnlich** eingefaerbt. Die
**Hauptstadt** traegt einen Sitz-Marker, und eine kompakte **Legende** unter der Karte
nennt Meer, freies Land, die groessten Reiche (Farbe + Glyphe) und die Terrain-Zeichen.

Zwei **Ansichten** (:data:`MAP_VIEWS`, Taste ``m`` in watch/replay) teilen alles bis auf
sechs Zahlen (:class:`_View`) — dieselbe Geografie, dieselben Lagen, dasselbe Wasser; sie
unterscheiden nur, **wie laut das Land sein darf**: ``political`` daempft es zur Andeutung
und gibt der Politik die Flaeche, ``terrain`` gibt ihm volle Erdfarbe, volles Relief und
alle Fluesse und zieht die Politik auf ihren Umriss zurueck.

Die Farben liegen in **zwei** Paletten, und das ist Absicht: die Natur traegt echte
Erdtoene (:class:`~worldsim.presentation.palette.TerrainPalette`), waehrend die
Rosé-Pine-Akzente der *Bedeutung* vorbehalten bleiben (Polity-Flaechen, Ereignisse,
Chrome). So kann das Land natuerlich aussehen, ohne dass ein Reich darin untergeht.

Read-only, kein semantischer RNG, keine Simulationslogik, **keine** Tile-Mikrosimulation
oder Geografie-Physik — nur eine Ansicht ueber dem fertigen Hoehenfeld.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from worldsim.config import DEFAULT_MAP_CONFIG, MapConfig
from worldsim.geo.climate import Biome, latitudes
from worldsim.geo.flow import NEIGHBOURS
from worldsim.geo.hydrology import STREAM_FACTOR, Hydrology, build_hydrology
from worldsim.geo.terrain import MAP_HEIGHT, MAP_WIDTH, TRENCH_RELIEF
from worldsim.models import EntityId, World
from worldsim.presentation.palette import NATURAL_EARTH as N
from worldsim.presentation.palette import REALM_LEAF
from worldsim.presentation.palette import ROSE_PINE_MOON as P

__all__ = ["MAP_VIEWS", "POLITICAL_VIEW", "TERRAIN_VIEW", "render_map"]

# Die Relief-Schwellen (Huegel/Gebirge/Graben) leben in :mod:`worldsim.geo.terrain` — sie
# sind eine Eigenschaft des Reliefs, kein Darstellungsdetail, und der Worldgen liest sie
# ebenso (Berge tragen Eisen). Nur ``TRENCH_RELIEF`` braucht die Wasser-Stufenwahl hier.
_SHELF_DEPTH = 0.20    # so flach unter dem Meeresspiegel gilt Wasser als Kuestensaum

# Zeichenzellen sind etwa doppelt so hoch wie breit (dasselbe ``_CHAR_RATIO`` wie in
# :mod:`terrain`). Die Hoehenschattierung braucht das, damit ein Nord-Sued-Hang nicht
# doppelt so steil erscheint wie ein gleich hoher Ost-West-Hang.
_CHAR_RATIO = 2.0

# --- Die zwei Ansichten -------------------------------------------------------

POLITICAL_VIEW = "political"
TERRAIN_VIEW = "terrain"
MAP_VIEWS: tuple[str, str] = (POLITICAL_VIEW, TERRAIN_VIEW)


@dataclass(frozen=True)
class _View:
    """Wieviel eine Ansicht dem LAND zugesteht — mehr unterscheidet die beiden nicht.

    Beide zeichnen dieselbe Geografie mit denselben Lagen aus denselben Daten; jede Zahl
    hier ist eine Lautstaerke, keine zweite Wahrheit. Darum kann keine Ansicht etwas
    zeigen, was die andere nicht auch weiss (gepinnt in ``test_both_views_draw_the_same_world``).
    """

    name: str
    desaturation: float   # wie weit die Erdfarbe des freien Landes zu Grau zieht
    luma: float | None    # Zielhelligkeit des freien Landes (``None`` = seine natuerliche)
    relief: float         # Anteil der Hoehenschattierung auf dem Land
    fill: bool            # traegt besetztes Land die volle Polity-Flaeche (sonst: Umriss)?
    river_flow: float     # ab welchem Abfluss (x Schwelle) ein Fluss ueberhaupt erscheint
    river_contrast: float  # wie weit der Wasserton sich vom Grund abhebt


def _view_of(name: str, cfg: MapConfig) -> _View:
    """Die benannte Ansicht; unbekannte Namen fallen auf die politische zurueck."""
    if name == TERRAIN_VIEW:
        # Die Geografie zeigt sich, wie sie ist: keine Entsaettigung, die natuerliche
        # Helligkeit, volles Relief, jeder Fluss im vollen Wasserton. Das sind keine
        # Stellschrauben, sondern die Definition der Ansicht — daher stehen sie hier.
        return _View(
            TERRAIN_VIEW, desaturation=0.0, luma=None, relief=1.0,
            fill=False, river_flow=1.0, river_contrast=1.0,
        )
    return _View(
        POLITICAL_VIEW,
        desaturation=cfg.nature_desaturation,
        luma=cfg.nature_luma,
        relief=cfg.nature_relief,
        fill=True,
        river_flow=STREAM_FACTOR,  # nur der grosse Strom, nicht jedes Rinnsal
        river_contrast=cfg.river_contrast,
    )


# --- Zeichen und Toene --------------------------------------------------------

# Das Meer in vier Tiefenstufen — fast schwarzblau im Graben, am Saum am hellsten, aber
# immer noch dunkler als jedes Land. Es traegt KEINE Glyphe: die Stufenfolge allein macht
# die raeumliche Tiefe, und die leere Flaeche macht das Meer auf einen Blick zum Meer.
_COAST = N.coast        # Wasser mit Landnachbar: die Kuestenlinie
_SHELF = N.shelf        # flaches Wasser ueber ersoffenem Sockel
_DEEP_SEA = N.deep_sea  # offene Tiefsee
_TRENCH = N.abyss       # der Abgrund
# Packeis: der gefrorene Polarozean. Der blasse, kalte Ton macht Pol zu Pol eine sichtbare
# Kappe — DAS Signal, das die Karte sofort als Planet lesen laesst. Das Eis ueberlagert
# JEDE Wasserart (auch Kueste), sonst risse ein Kuestensaum die Kappe auf.
_SEA_ICE = N.sea_ice
_LAKE = N.lake  # Suesswasser ist auch Wasser: eine Flaeche, kein Zeichen

# Die Flussglyphe folgt der Abflussrichtung: eine Linie, die man verfolgen kann. Der
# Strom (viel Akkumulation) bekommt die schwere Variante — die Breite eines Flusses ist
# nichts anderes als sein Durchfluss.
_RIVER_GLYPHS: dict[tuple[int, int], tuple[str, str]] = {
    (0, -1): ("─", "━"), (0, 1): ("─", "━"),
    (-1, 0): ("│", "┃"), (1, 0): ("│", "┃"),
    (-1, -1): ("╲", "╲"), (1, 1): ("╲", "╲"),
    (-1, 1): ("╱", "╱"), (1, -1): ("╱", "╱"),  # noqa: RUF001 — Kastengrafik, kein Schrägstrich
}

# Die Landglyphe kommt aus dem KLIMA (Biom), der Ton aus der Erdpalette. Die Glyphen
# steigen grob in der Dichte mit der Hoehe an — von der leeren Ebene (``"`` ``,``) ueber
# Wald (``&`` ``#``) und Wueste (``░``) bis zum Gipfelzeichen (``▲``).
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
# bekommt auch eine andere Glyphe — so bleibt Besitz auch fuer farbschwache Augen lesbar.
#
# **Zwei Toene der Palette fehlen hier mit Absicht** (Schritt 4) — die Liste braucht nicht
# alle Akzente, sondern sechs, die einander UND dem Meer fernbleiben. Beides ist gemessen
# (30 Seeds x 250 J., :func:`_tone_distance`), nicht geschmacklich:
#
# * ``rose #ea9a97`` steckt in BEIDEN schlechten Paaren der Palette (zu ``love`` 86, zu
#   ``gold`` 93) und trieb die Faerbung ueberhaupt erst in die Enge. Ohne ihn faellt das
#   schlechteste je gemessene Nachbarpaar von 86 auf 121.
# * ``pine #3e8fb0`` ist trotz seines Namens ein Meeresblau: er liegt nur **24** von den
#   Ozeanstufen entfernt — ein pine-farbenes Reich an der Kueste IST die See. Kein Regler
#   half, weil es der Farbton selbst ist. An seiner Stelle steht ``REALM_LEAF``, das Gruen,
#   das Rosé Pine nicht hat (schlechtester Abstand 144 statt 24; siehe ``palette``).
#
# Beide bleiben der Palette als Ereignisfarben erhalten — nur als LANDESfarbe taugen sie
# nicht. Kuerzen laesst sich die Liste dabei nicht: mit fuenf Toenen tragen Nachbarn
# gemessen wieder denselben Ton (Abstand 0), weil die Faerbung ausweichen muss.
#
# Die Glyphen sind geometrische Formen aus dem Block "Geometric Shapes" (U+25xx) — nahezu
# universell in Terminal-Schriften vorhanden (Stern-/Kreuzformen wie ``★ ✦`` fehlen selbst
# in vollen Nerd Fonts) — und kollidieren mit KEINER Biomglyphe (gegen ``" , ; & # ░ ▲ ^``).
#
# Sie sind **hohl, und das ist der Punkt** (Schritt 4): seit die Flaeche die Polity-Farbe
# traegt, ist eine flaechige Glyphe ihr Gegner. Die alten ``● ■ ◆`` decken den groessten
# Teil der Zelle ab — ein ``■`` in Kontrast-Tinte auf ``gold`` machte die Zelle nicht
# golden mit Zeichen, sondern schlicht **dunkelbraun** (gemessen: Grund #f6c177, Glyphe
# #735e4f, und die Glyphe gewinnt die Flaeche). Ein Ring laesst den Grund stehen und bleibt
# trotzdem als Form lesbar — Redundanz, ohne die Farbe zu erschlagen, die sie redundant
# machen soll. Die vorderen, haeufigsten Indizes tragen die verschiedensten Silhouetten.
_POLITY_TONES: tuple[str, ...] = (P.love, P.gold, P.iris, P.foam, REALM_LEAF, P.text)
_POLITY_GLYPHS: tuple[str, ...] = ("○", "□", "◇", "▽", "◎", "▷")


# --- Farbrechnung -------------------------------------------------------------

def _luma(color: str) -> float:
    """Die wahrgenommene Helligkeit eines ``#rrggbb``-Tons (0..255).

    Die eine Zahl, nach der das Auge zuerst sortiert — und damit die Groesse, in der die
    Karte ihre Rangfolge Wasser < freies Land < Territorium ueberhaupt ausdrueckt.
    """
    return (
        0.299 * int(color[1:3], 16) + 0.587 * int(color[3:5], 16) + 0.114 * int(color[5:7], 16)
    )


def _tone_distance(a: str, b: str) -> float:
    """Der wahrgenommene Abstand zweier ``#rrggbb``-Toene ("redmean", ~perzeptuell).

    Der reine Euklid-Abstand im RGB-Wuerfel luegt (er haelt Gruentoene fuer weiter
    auseinander als sie wirken); redmean gewichtet die Kanaele nach der mittleren Roete
    und kommt der Wahrnehmung nahe genug, um "sehen diese zwei Reiche gleich aus?" zu
    beantworten — ohne dafuer einen Farbraum-Apparat einzufuehren (Ockham).
    """
    r1, g1, b1 = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    r2, g2, b2 = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    mean_red = (r1 + r2) / 2
    dr, dg, db = r1 - r2, g1 - g2, b1 - b2
    return math.sqrt(
        (2 + mean_red / 256) * dr * dr + 4 * dg * dg + (2 + (255 - mean_red) / 256) * db * db
    )


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


def _mix(base: str, other: str, amount: float) -> str:
    """Blende ``base`` anteilig nach ``other`` (``amount`` 0 = ``base``, 1 = ``other``).

    Damit steht jede Glyphe auf ihrem eigenen Grund: statt einen Ton absolut zu waehlen
    (und mal zu verschwinden, mal zu schreien), wird der Grund um einen festen Anteil
    Richtung Zielton verschoben. Der Kontrast ist dann eine Ansage, kein Zufall.
    """
    out = []
    for lo, hi in ((1, 3), (3, 5), (5, 7)):
        start, end = int(base[lo:hi], 16), int(other[lo:hi], 16)
        out.append(min(255, max(0, round(start + (end - start) * amount))))
    return f"#{out[0]:02x}{out[1]:02x}{out[2]:02x}"


_INK_PIVOT = 140.0  # ab dieser Grundhelligkeit schreibt man dunkel statt hell
_SEAT_DIM = 0.45    # der Sitz-Chip: so weit unter dem Polity-Ton, dass die Initiale traegt


def _ink(background: str) -> str:
    """Der lesbare Vordergrund auf ``background`` — dunkel auf hellem Grund, hell auf dunklem.

    Die Polity-Toene reichen von ``pine`` (Helligkeit 122) bis ``text`` (225); eine feste
    Schriftfarbe waere auf der einen Haelfte unlesbar. Der Umschlagpunkt liegt zwischen
    beiden Gruppen, also faellt die Wahl je Flaeche und nicht je Palette.
    """
    return P.base if _luma(background) > _INK_PIVOT else P.text


def _relief(factor: float, amount: float) -> float:
    """Wieviel von der Hoehenschattierung eine Lage abbekommt (0 = flach, 1 = voll)."""
    return 1.0 + (factor - 1.0) * amount


def _set_luma(color: str, target: float) -> str:
    """Ziehe einen Ton auf eine Zielhelligkeit — der Farbton bleibt, die Lautstaerke geht.

    Der Unterschied zum blossen Abdunkeln ist der ganze Punkt von Schritt 4: Daempfen ist
    multiplikativ und verschiebt das Helligkeitsband nur, es verschmaelert es nicht. Die
    Biomtoene spannen 3x (Regenwald 83, Schnee 236) — nach jeder Daempfung spannen sie
    immer noch 3x, und die freie Wueste ueberstrahlt weiter das besetzte Land. Auf EIN Ziel
    gezogen hoert das auf: der Ton sagt noch, WAS dort waechst, die Helligkeit nur noch,
    dass es frei ist.
    """
    here = _luma(color)
    if here <= 1.0:  # praktisch schwarz: es gibt nichts zu skalieren
        return color
    return _shade(color, target / here)


# --- Die Lagen ----------------------------------------------------------------

def _water_tone(depth: float, relief: float, oceanic: bool, coastal: bool) -> str:
    """Wasser ⇒ seine Tiefenstufe. Das entscheidet die Geologie, nicht das Klima.

    ``depth`` ist die Tiefe unter dem Meeresspiegel, ``relief`` die Hoehe ueber der
    eigenen Krustenbasis. Jeder Zweig sagt eine geologische Tatsache: ein Graben ist unter
    die eigene Kruste gerissener Meeresboden, ein Schelf ist ersoffener Kontinentalsockel.
    Nur der Kuestensaum ist keine Tatsache ueber die Tiefe, sondern eine ueber die Naehe —
    er zeichnet die Linie nach, an der Land und Meer sich beruehren, und macht damit den
    Uebergang hart: die hellste Wasserstufe stoesst unmittelbar auf das Land.
    """
    if coastal:
        return _COAST
    if oceanic and relief <= TRENCH_RELIEF:
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


def _quiet_land(tone: str, factor: float, view: _View) -> str:
    """Freies Land: entsaettigt, auf ein ruhiges Helligkeitsband gezogen, schwach reliefiert.

    Die Natur soll Landschaft bleiben, nicht mit der Politik um Aufmerksamkeit ringen —
    also erst zu Grau ziehen, dann auf die Zielhelligkeit setzen, dann nur einen Anteil der
    Reliefschattierung zulassen. In der Terrain-Ansicht ist jeder dieser drei Griffe
    neutral (``desaturation`` 0, ``luma`` None, ``relief`` 1), und dieselbe Funktion liefert
    die volle Erdfarbe: es gibt keinen zweiten Zeichenweg fuer die zweite Ansicht.
    """
    quiet = _desaturate(tone, view.desaturation)
    if view.luma is not None:
        quiet = _set_luma(quiet, view.luma)
    return _shade(quiet, _relief(factor, view.relief))


def _territory_tone(tone: str, factor: float, cfg: MapConfig, *, border: bool) -> str:
    """Beanspruchtes Land: die Polity-Farbe als Flaeche, durch die das Relief schwach scheint.

    Der **Rand traegt den reinen Ton und liegt flach**: so umreisst jedes Reich ein
    gleichmaessiger, kraeftiger Saum (Aufgabe 4), und die Farbe, die die Legende nennt, ist
    exakt die, die man am Umriss sieht. Das **Innere** sitzt auf ``territory_dim`` zurueck
    und laesst das Relief zu ``territory_relief`` durch — man sieht Besitz UND Landform in
    derselben Zelle. Dass das Innere nie heller wird als der Rand, ist dabei keine Klemme,
    sondern faellt aus der Rechnung: der Reliefanteil hebt hoechstens auf das 1.17-fache,
    mal 0.80 sind das 0.93 des Randes.
    """
    if border:
        return tone
    return _shade(tone, _relief(factor, cfg.territory_relief) * cfg.territory_dim)


# --- Raster: Beleuchtung, Kueste, Besitz, Grenzen ------------------------------

def _hillshade(elevation: np.ndarray, cfg: MapConfig) -> np.ndarray:
    """Beleuchte das Relief aus Nordwesten ⇒ ein Helligkeits-Faktor (~0.4..1.75) je Zelle.

    Kein 3D-Rendering, nur die eine billige Rechnung, die einer flachen Karte sofort
    Plastik gibt: der Neigungsvektor jeder Zelle wird gegen einen schraeg von oben-links
    einfallenden Lichtstrahl gehalten. Zum Licht geneigte Haenge kommen ueber 1.0 (heller),
    abgewandte darunter (dunkler); die Ebene bleibt bei 1.0. Der Faktor skaliert am Ende
    nur die Helligkeit des ohnehin gewaehlten Erdtons — er aendert weder Glyphe noch
    Farbton, also bleibt das Biom lesbar. Wieviel davon eine Lage abbekommt, entscheidet
    die Ansicht (:func:`_relief`); das **Wasser bekommt gar nichts** — eine je Zelle anders
    helle See ist Rauschen, kein Meer.

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
# ihren festen Breiten. Es ist die billige Andeutung einer Projektion, ohne eine echte
# Projektion zu rechnen oder Kartendaten zu verdecken.
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


def _capital_cells(
    world: World, owner_of: dict[EntityId, EntityId], rids: list[EntityId],
    nearest: np.ndarray, is_wet: np.ndarray,
) -> dict[tuple[int, int], tuple[str, EntityId]]:
    """Je gehaltenem Sitz die Zelle, in der sein Marker steht ⇒ (Initiale, Polity).

    Nur wo die Polity ihren Sitz aktuell auch haelt. Die Region traegt einen **Punkt**
    (``coord``), die Karte ein **Raster** — beim Runden kann der Sitz darum auf eine
    Wasserzelle neben seiner Region fallen. Dann rueckt er auf die naechste TROCKENE Zelle
    derselben Region: ein Sitz im Wasser waere eine Falschaussage (seit Schritt 2 liegen die
    Hauptstaedte auf dem besten Land), und er risse die Invariante auf, dass nur Land
    Zeichen traegt — der Marker wird zuerst gezeichnet und ueberschreibt sonst das Wasser.

    ``is_wet`` meint **Meer UND See**, nicht nur das Meer. Genau daran hing der Fehler:
    gegen ``is_sea`` allein gemessen sass der Sitz sechsmal (8 Seeds) mitten auf einem
    Binnensee, denn dort ist ``is_sea`` falsch — und ein See ist Wasser wie jedes andere.
    """
    height, width = is_wet.shape
    caps: dict[tuple[int, int], tuple[str, EntityId]] = {}
    for pid in sorted(world.polities):
        cap = world.polities[pid].capital
        if cap is None or cap not in world.regions or owner_of.get(cap) != pid:
            continue
        cx, cy = world.regions[cap].coord
        col = min(width - 1, int(cx * width))
        row = min(height - 1, int(cy * height))
        if is_wet[row, col]:
            index = rids.index(cap)
            dry = [
                (r, c)
                for r in range(height)
                for c in range(width)
                if not is_wet[r, c] and int(nearest[r, c]) == index
            ]
            if not dry:  # eine Region ganz ohne trockene Zelle: dann eben kein Marker
                continue
            row, col = min(dry, key=lambda rc: (rc[0] - row) ** 2 + (rc[1] - col) ** 2)
        caps[(row, col)] = (world.polities[pid].name[:1] or "?", pid)
    return caps


def _polity_neighbours(owner_grid: np.ndarray) -> dict[EntityId, set[EntityId]]:
    """Welche Polities sich auf der Karte beruehren (aus dem Besitzraster abgelesen)."""
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
    return adjacency


def _polity_styles(
    world: World, owner_grid: np.ndarray, cfg: MapConfig,
) -> dict[EntityId, int]:
    """Weise jeder Polity einen Farb-/Glyphen-Index zu, sodass Nachbarn sich UNAEHNLICH sehen.

    Gierige Graphfaerbung ueber der aus dem Territorium abgelesenen Nachbarschaft: die
    Polities werden in stabiler Id-Reihenfolge gefaerbt (damit die Farbe ueber die Jahre
    nicht flackert), jede nimmt bevorzugt ihren rang-eigenen Ton und weicht nur aus, wenn
    ein Nachbar zu nah dran liegt.

    Das entscheidende Wort ist **unaehnlich**, nicht "verschieden" (Aufgabe 5): die
    Palette enthaelt Paare, die sich als Flaeche nicht auseinanderhalten lassen —
    ``love #eb6f92`` und ``rose #ea9a97`` liegen nur 86 auseinander, ``gold``/``rose`` 93.
    Wer nur den INDEX vergleicht, faerbt solche Nachbarn brav "verschieden" und macht die
    Karte trotzdem unlesbar. Gemessen wird darum der Abstand selbst
    (:func:`_tone_distance`) gegen ``polity_tone_min_distance``. Findet sich kein Ton, der
    weit genug weg ist, gewinnt der **entfernteste** — so schlaegt die Faerbung nie fehl,
    sie wird nur im Notfall unschaerfer statt falsch.
    """
    adjacency = _polity_neighbours(owner_grid)
    ntones = len(_POLITY_TONES)
    ranks = {pid: i for i, pid in enumerate(sorted(world.polities))}
    style: dict[EntityId, int] = {}
    for pid in sorted(world.polities):
        taken = [
            _POLITY_TONES[style[n]] for n in sorted(adjacency.get(pid, ())) if n in style
        ]
        base = ranks[pid] % ntones
        # Bevorzugt den rang-eigenen Ton, sonst den naechsten hinreichend fernen (rotierend).
        order = [(base + k) % ntones for k in range(ntones)]
        gap = {
            idx: min((_tone_distance(_POLITY_TONES[idx], t) for t in taken), default=math.inf)
            for idx in order
        }
        style[pid] = next(
            (idx for idx in order if gap[idx] >= cfg.polity_tone_min_distance),
            max(order, key=lambda idx: gap[idx]),  # Notfall: der entfernteste Ton
        )
    return style


# --- Legende ------------------------------------------------------------------

def _legend(
    world: World, owner_grid: np.ndarray, style: dict[EntityId, int], view: _View,
    cfg: MapConfig, *, max_named: int = 5,
) -> Text:
    """Die kompakte Legende unter der Karte: die drei Flaechen und die groessten Reiche.

    Sie zeigt, was die Karte zeigt — als **Farbchip**, nicht als Glyphenfarbe: die Karte
    faerbt Flaechen, also muss die Legende Flaechen nennen, sonst erklaert sie ein anderes
    Bild als das darueber. Reiche nach Territoriumsgroesse (aus dem Raster gezaehlt, damit
    die Legende exakt zur gezeigten Karte passt); bei vielen werden nur die groessten
    namentlich genannt, der Rest als ``+k more`` zusammengefasst.
    """
    ids, counts = np.unique(owner_grid[owner_grid >= 0], return_counts=True)
    sizes = dict(zip(ids.tolist(), counts.tolist(), strict=True))
    ranked = sorted(sizes, key=lambda p: (sizes[p], -p), reverse=True)

    realms = Text("realms   ", style=P.subtle)
    if not ranked:
        realms.append("— no realm has claimed a field —", style=P.muted)
    for pid in ranked[:max_named]:
        idx = style.get(pid, 0)
        tone = _POLITY_TONES[idx]
        realms.append(f" {_POLITY_GLYPHS[idx]} ", style=f"bold {_ink(tone)} on {tone}")
        realms.append(f" {world.polities[pid].name}  ", style=tone)
    if len(ranked) > max_named:
        realms.append(f"+{len(ranked) - max_named} more", style=P.muted)

    # Die drei Flaechen in genau der Rangfolge, in der die Karte sie stapelt — das IST die
    # Legende der Lesbarkeit: dunkel = Wasser, ruhig = frei, kraeftig = jemandes Land.
    free = _quiet_land(N.grassland, 1.0, view)
    keys = Text("terrain  ", style=P.subtle)
    for tone, glyph, label in (
        (N.deep_sea, " ", "sea"),
        (N.sea_ice, " ", "ice"),
        (free, _BIOME_STYLE[Biome.GRASLAND][0], "free land"),
        (_quiet_land(N.alpine, 1.0, view), "▲", "mountains"),
        (_quiet_land(N.desert, 1.0, view), "░", "desert"),
    ):
        ink = _mix(tone, _ink(tone), cfg.nature_glyph_contrast)
        keys.append(f" {glyph} ", style=f"{ink} on {tone}")
        keys.append(f" {label}  ", style=P.muted)
    keys.append("━", style=N.stream)
    keys.append(" river", style=P.muted)

    legend = Text()
    legend.append_text(realms)
    legend.append("\n")
    legend.append_text(keys)
    return legend


# --- Die Karte ----------------------------------------------------------------

@dataclass(frozen=True)
class _Layers:
    """Die fertig gerechneten Raster einer Welt — einmal je Render gebaut, dann nur gelesen.

    Alles, was :func:`_cell` braucht, damit die Zellenrechnung eine kleine, lesbare
    Funktion bleiben kann statt einer Parameterlawine. Reine Daten, kein Verhalten (die
    Architektur-Invariante gilt auch in der Praesentation).
    """

    water: Hydrology
    biome: np.ndarray
    temperature: np.ndarray
    elevation: np.ndarray
    relief: np.ndarray
    oceanic: np.ndarray
    sea_level: float
    is_sea: np.ndarray
    coastal: np.ndarray
    shade: np.ndarray
    owner_grid: np.ndarray
    border: np.ndarray
    style: dict[EntityId, int]
    caps: dict[tuple[int, int], tuple[str, EntityId]]
    flashing: np.ndarray


def _cell(row: int, col: int, layers: _Layers, view: _View, cfg: MapConfig) -> tuple[str, str]:
    """Eine Zelle ⇒ (Glyphe, ``rich``-Stil). Der Grund sagt WEM, die Glyphe sagt WAS.

    Die Reihenfolge der Zweige ist die Aussage der Karte, von der staerksten zur
    schwaechsten: der Sitz zuerst (er ist ein Marker, kein Gelaende), dann ist Wasser
    Wasser (und traegt nie ein Zeichen), sonst faerbt der Besitz den Grund, und erst darauf
    kommt die Textur des Landes.
    """
    # 0. Der Sitz: die Initiale, hell auf einem dunklen Chip aus dem Ton der Polity — auch
    #    im Terrain-Modus sichtbar, wo er sonst in der Landschaft laege. Er steht garantiert
    #    auf Land (:func:`_capital_cells`), reisst die Wasser-Invariante also nicht auf.
    seat = layers.caps.get((row, col))
    if seat is not None:
        letter, pid = seat
        tone = _POLITY_TONES[layers.style.get(pid, 0)]
        return letter, f"bold {P.text} on {_shade(tone, _SEAT_DIM)}"

    # 1. Wasser — eine Flaeche in ihrer Tiefenstufe, ohne Glyphe. Suesswasser zaehlt dazu:
    #    ein See ist ein Wasserkoerper, kein Untergrund, auf dem man siedelt.
    if layers.is_sea[row, col]:
        if layers.temperature[row, col] < cfg.sea_ice_temp:
            return " ", f"on {_SEA_ICE}"  # der Polarozean ist gefroren: die Kappe
        tone = _water_tone(
            float(layers.elevation[row, col]) - layers.sea_level,
            float(layers.relief[row, col]),
            bool(layers.oceanic[row, col]),
            bool(layers.coastal[row, col]),
        )
        return " ", f"on {tone}"
    if layers.water.lake[row, col]:
        return " ", f"on {_LAKE}"

    # 2. Der Grund: wem gehoert die Zelle? Das ist die Frage, die auf einen Blick
    #    beantwortet sein muss, also traegt sie die Flaeche.
    owner = int(layers.owner_grid[row, col])
    factor = float(layers.shade[row, col])
    biome_glyph, biome_tone = _BIOME_STYLE[layers.biome[row, col]]
    owned = owner >= 0 and view.fill
    if owned:
        ground = _territory_tone(
            _POLITY_TONES[layers.style.get(owner, 0)], factor, cfg,
            border=bool(layers.border[row, col]),
        )
    else:
        ground = _quiet_land(biome_tone, factor, view)

    # 3. Die Glyphe auf diesem Grund. Ein Fluss laeuft ueber alles hinweg — er ist die
    #    Linie, an der man siedelt, nicht der Untergrund; in der politischen Ansicht aber
    #    nur noch als grosser Strom und nur noch angedeutet in den Grund gemischt.
    if (
        layers.water.river[row, col]
        and float(layers.water.flow[row, col]) >= view.river_flow * cfg.river_threshold
    ):
        glyph, tone = _river_style(layers.water, row, col, cfg.river_threshold)
        return glyph, f"{_mix(ground, tone, view.river_contrast)} on {ground}"

    if owned:
        idx = layers.style.get(owner, 0)
        if layers.flashing[row, col]:
            # Frischer Besitzwechsel (Watch-Modus): kurz hell aufblitzen.
            return _POLITY_GLYPHS[idx], f"bold {_ink(P.text)} on {P.text}"
        return (
            _POLITY_GLYPHS[idx],
            f"{_mix(ground, _ink(ground), cfg.polity_glyph_contrast)} on {ground}",
        )

    # In der Terrain-Ansicht zieht sich die Politik auf ihren Umriss zurueck: nur die
    # Grenzzelle traegt noch Farbe und Zeichen ihres Reiches, das Innere bleibt Landschaft.
    if owner >= 0 and layers.border[row, col]:
        tone = _POLITY_TONES[layers.style.get(owner, 0)]
        return _POLITY_GLYPHS[layers.style.get(owner, 0)], f"bold {tone} on {ground}"

    return biome_glyph, f"{_mix(ground, _ink(ground), cfg.nature_glyph_contrast)} on {ground}"


def render_map(
    world: World,
    seed: int = 0,
    owners: dict[EntityId, EntityId] | None = None,
    *,
    width: int = MAP_WIDTH,
    height: int = MAP_HEIGHT,
    flash: frozenset[EntityId] = frozenset(),
    view: str = POLITICAL_VIEW,
) -> Panel:
    """Rendere die Karte als ``rich``-Panel: Wasser, freies Land und Besitz auf einen Blick.

    ``owners`` erlaubt es dem Replay, einen **rekonstruierten** Besitzstand zu zeigen;
    ohne Angabe gilt der aktuelle Weltzustand (so wandern im Watch-Mode die Grenzen Jahr
    fuer Jahr). ``view`` waehlt zwischen :data:`POLITICAL_VIEW` (Politik als Flaeche, Land
    nur angedeutet) und :data:`TERRAIN_VIEW` (Land in voller Erdfarbe, Politik als Umriss);
    beide zeichnen dieselbe Welt, nur verschieden laut. ``flash`` (Regionen-Ids, im
    Watch-Modus die eben gewechselten) laesst deren Zellen kurz aufblitzen. Unter der Karte
    steht eine kompakte Legende (Flaechen + Reiche).
    """
    rids = sorted(world.regions)
    if not rids:
        return Panel(Text("(no regions)", style=P.muted), title=f"world map · seed {seed}")

    cfg = DEFAULT_MAP_CONFIG
    look = _view_of(view, cfg)
    coords = np.array([world.regions[rid].coord for rid in rids], dtype=float)
    water = build_hydrology(seed, width, height)  # einmal je Welt (gecacht), nie pro Tick
    climate, terrain = water.climate, water.terrain
    elevation = np.asarray(terrain.elevation)
    is_sea = elevation < terrain.sea_level
    nearest = _nearest_region(coords, width, height)
    owner_of = (
        owners
        if owners is not None
        else {rid: r.owner for rid, r in world.regions.items() if r.owner is not None}
    )

    # Die politische Lage: Besitzraster (Meer traegt nie Territorium), Grenzumriss und je
    # Polity ein unterscheidbarer Stil (Farbe + Glyphe, Nachbarn unaehnlich gefaerbt).
    owner_grid = _owner_grid(owner_of, nearest, rids, is_sea)
    style = _polity_styles(world, owner_grid, cfg)

    layers = _Layers(
        water=water,
        biome=climate.biome,
        temperature=np.asarray(climate.temperature),  # fuer das Meereis der Polkappen
        elevation=elevation,
        relief=terrain.relief,
        oceanic=terrain.oceanic,
        sea_level=terrain.sea_level,
        is_sea=is_sea,
        coastal=_coastline(is_sea),
        # Hoehenschattierung: einmal je Render aus dem Hoehenfeld gerechnet (reine Numerik,
        # kein Zufall). Nur das Land bekommt sie — die See bleibt glatt.
        shade=_hillshade(elevation, cfg),
        owner_grid=owner_grid,
        border=_borders(owner_grid),
        style=style,
        # Nass ist Meer UND See: der Sitz-Marker darf auf keinem von beiden landen.
        caps=_capital_cells(world, owner_of, rids, nearest, is_sea | np.asarray(water.lake)),
        flashing=(
            np.isin(nearest, [rids.index(r) for r in sorted(flash) if r in world.regions])
            if flash
            else np.zeros_like(is_sea)
        ),
    )

    axis = _latitude_axis(height)  # linke Breitengrad-Skala: es ist ein Planet
    text = Text()
    for row in range(height):
        text.append(axis[row], style=P.muted)
        for col in range(width):
            glyph, cell = _cell(row, col, layers, look, cfg)
            text.append(glyph, style=cell)
        if row != height - 1:
            text.append("\n")

    legend = _legend(world, owner_grid, style, look, cfg)
    return Panel(
        Group(text, Text(), legend),
        # Kein ``[...]`` im Titel: ``rich`` liest eckige Klammern als Markup und verschluckt
        # den Namen still.
        title=f"world map · seed {seed} · {look.name} view",
        title_align="left",
        border_style=P.muted,
    )
