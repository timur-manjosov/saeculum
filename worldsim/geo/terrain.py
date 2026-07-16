"""terrain — die Geologie der Karte: Tektonik als grosse Struktur, fBm als Rauheit.

Erdaehnlichkeit entsteht aus sichtbaren **Prozessen**, nicht aus schoenerem Rauschen.
Ein Gebirge ist kein Hoehenfleck, es ist eine **Naht**: dort, wo zwei Platten
aufeinander zulaufen. Darum wird die Hoehe hier nicht gewuerfelt, sondern *hergeleitet*:

1. **Platten.** Eine Handvoll Keimpunkte spannt Voronoi-Zellen auf. Jede Platte
   bekommt eine Bewegungsrichtung, eine Art (kontinental/ozeanisch) und eine Dichte.
   Das ist ein **Standbild**, keine Drift ueber Zeit — Ockham: der sichtbare Effekt
   der Tektonik ist die Hoehenstruktur, und die braucht keine Zeitachse.
2. **Grenzen formen die Hoehe**, je nach relativer Bewegung der beiden Nachbarn.
   Die dichtere Platte taucht unter die leichtere ab (ozeanisch ist immer dichter
   als kontinental) — aus dieser einen Regel folgen alle Faelle:

   ===================== ================================================================
   Grenze                Ergebnis
   ===================== ================================================================
   Kollision (kont+kont) breite Gebirgskette ueber der Naht (Himalaya)
   Subduktion (kont)     Kuestengebirge, etwas landeinwaerts versetzt (Anden)
   Subduktion (ozean)    Tiefseegraben, seewaerts der Grenze (Peru-Chile-Graben)
   Inselbogen            schmaler Ruecken auf der ozeanischen Oberplatte — das fBm
                         zerhackt ihn zur **Inselkette** (Japan, Aleuten)
   Divergenz             Rift/Graben: Grabenbruch an Land, tiefes Becken im Ozean
   Transform (Scherung)  fast nichts — die Amplitude haengt an der Konvergenz und
                         geht mit ihr gegen null
   ===================== ================================================================

3. **fBm ueberlagert**, es ersetzt nicht: die Tektonik gibt die grosse Struktur, das
   Rauschen (mehrere Oktaven) nur die Detailrauheit der Haenge.
4. **Danach** faellt die Land/Wasser-Entscheidung — der Meeresspiegel ist ein Quantil
   der fertigen Hoehenverteilung (``land_fraction``), keine feste Hoehe.

Zufalls-Vertrag
---------------
Die Karte ist **kosmetisch**: sie aendert nie, welche Fakten die Simulation erzeugt.
Entsprechend zieht sie aus dem **kosmetischen** Namensraum
(:meth:`Rng.cosmetic_stream`), der den semantischen Strom per Konstruktion nicht
beruehren kann — an der Tektonik zu drehen kann eine Historie nicht verbiegen.
Der Aufbau laeuft **einmal** je Welt (gecacht), nie pro Tick.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
from opensimplex import OpenSimplex

from worldsim.config import DEFAULT_MAP_CONFIG, MapConfig
from worldsim.geo.flow import accumulate, steepest_descent
from worldsim.geo.rain import moisture_and_rain
from worldsim.rng import Rng, Stream

__all__ = [
    "HILL_RELIEF",
    "MAP_HEIGHT",
    "MAP_WIDTH",
    "PEAK_RELIEF",
    "TRENCH_RELIEF",
    "Plate",
    "Terrain",
    "build_terrain",
]

# Relief-Schwellen (Hoehe ueber der EIGENEN Krustenbasis, s. :attr:`Terrain.relief`) —
# die geografische Klassifikation, an der sowohl die Karte die Land-Glyphen waehlt als
# auch der Worldgen die Ressourcen ableitet (Berge tragen Eisen). Sie leben hier, weil
# sie Eigenschaften des Reliefs sind, nicht der Darstellung. Geeicht an der gemessenen
# Relief-Verteilung ueber 60 Seeds (Land p90 +0.47, p97 +0.95; Ozeanboden p10 -0.40).
# Huegel liegen auf der Skala des fBm (Rauheit bis ~0.08) ⇒ JEDE Welt traegt Huegel;
# Gebirge auf der Skala der Tektonik ⇒ nur eine Welt mit Konvergenz traegt Gebirge.
HILL_RELIEF = 0.08     # darueber: gewelltes Land (Huegel) — das macht schon das Rauschen
PEAK_RELIEF = 0.35     # darueber: Gebirge — das macht nur die Tektonik
TRENCH_RELIEF = -0.55  # darunter: unter die eigene Kruste gerissen ⇒ Tiefseegraben

# Kartengroesse in Zeichen. Breite und Hoehe legen zusammen mit ``_CHAR_RATIO`` das
# **Seitenverhaeltnis der Welt** fest — der eine sichtbare Regler dafuer, ob die Karte
# wie eine abgewickelte Kugel liegt oder wie ein Quadrat. Weil die Zeichenzelle doppelt
# so hoch wie breit ist, ist das dargestellte Verhaeltnis (Breite/_CHAR_RATIO)/Hoehe:
# 68/2/17 = **2:1** (breit, erdkarten-artig). Die Hoehe von 17 Zeilen ist kein Zufall,
# sondern die untere Grenze, ab der die Geologie noch traegt: sie muss die Pole flaechen-
# treu aufloesen (Klima), zusammenhaengende Gebirgsketten zulassen (Tektonik) und darf die
# Einzugsgebiete nicht so vergroessern, dass die Karte in Fluessen ersaeuft (Hydrologie).
# Wer hier dreht, aendert nur die ANSICHT (die Karte ist kosmetisch); die Flussdichte
# muss dann ueber ``MapConfig.river_threshold`` nachgezogen werden (skaliert mit der
# Einzugsflaeche, also mit der Zellzahl).
MAP_WIDTH = 68   # Kartenbreite in Zeichen
MAP_HEIGHT = 17  # Kartenhoehe in Zeilen

# Zeichenzellen sind etwa doppelt so hoch wie breit. Das Feld lebt im Einheits-
# quadrat (wie ``Region.coord``), erscheint dort aber horizontal gestreckt; die
# Distanzmetrik korrigiert das, damit Platten und Ketten nicht breitgezogen wirken.
_CHAR_RATIO = 2.0

# --- Geologie-Konstanten (nicht die Stellschrauben — die stehen in MapConfig) ---
# Grundhoehe der beiden Plattenarten: Kontinente liegen hoch, Ozeanboeden tief. Aus
# diesem Kontrast (nicht aus dem Rauschen) entsteht die grobe Land/Meer-Verteilung.
_BASE_CONTINENTAL = 0.30
_BASE_OCEANIC = -0.55
_BASE_JITTER = 0.06  # ... damit nicht alle Platten derselben Art gleich hoch liegen
# Dichte: die dichtere Platte subduziert. Die Baender ueberlappen nie, also taucht
# ozeanisch **immer** unter kontinental ab; ozean/ozean entscheidet die Dichte.
_DENSITY_CONTINENTAL = (0.10, 0.40)
_DENSITY_OCEANIC = (0.60, 0.95)

# Profile quer zur Grenze. ``u`` ist der Abstand zur Grenze in Einheiten von
# ``boundary_width`` (0 = auf der Naht). (Zentrum, Breite) je Gauss-Ruecken.
_COLLISION_PROFILE = (0.00, 0.75)   # breit, ueber der Naht — beide Seiten heben sich
_CORDILLERA_PROFILE = (0.45, 0.35)  # etwas landeinwaerts vom Graben
_ARC_PROFILE = (0.50, 0.22)         # schmal ⇒ das fBm zerlegt ihn in Inseln
_TRENCH_PROFILE = (0.28, 0.30)      # seewaerts, direkt an der Grenze
_TRENCH_GAIN = 1.30   # Graeben sind tiefer als Gebirge hoch (relativ zu mountain_strength)
_ARC_GAIN = 1.30      # Inselboegen muessen den Ozeanboden bis UEBER die Wasserlinie heben,
                      #     sonst bleibt der Bogen unsichtbar (gemessen: bei 0.95 tauchte
                      #     nichts auf). Weil der Ruecken schmal ist, zerhackt ihn das fBm
                      #     zur Inselkette statt zu einem langen Wall.
_RIFT_GAIN_LAND = 0.55
_RIFT_GAIN_SEA = 0.60  # flacher als der Graben: der tiefste Punkt gehoert der Subduktion
_RIFT_WIDTH_LAND = 0.35
_RIFT_WIDTH_SEA = 0.55

# fBm: Grundfrequenz, dann je Oktave doppelt so fein und halb so stark.
_NOISE_BASE_FREQ = 3.0
_NOISE_LACUNARITY = 2.0
_NOISE_GAIN = 0.5
# Domain-Warp der Plattengrenzen: ohne ihn sind Voronoi-Kanten schnurgerade und die
# Ketten sehen gezeichnet aus. Ein wenig Rauschen im Koordinatenraum genuegt, damit
# sie maeandern.
_WARP_AMPLITUDE = 0.075
_WARP_FREQ = 2.5


@dataclass(frozen=True)
class Plate:
    """Eine tektonische Platte: Keimpunkt, Bewegungsrichtung, Art, Dichte."""

    seed_point: tuple[float, float]  # im Einheitsquadrat, wie ``Region.coord``
    drift: tuple[float, float]       # Einheitsvektor: wohin die Platte laeuft
    oceanic: bool
    density: float                   # die dichtere Platte subduziert unter die leichtere
    base_height: float


@dataclass(frozen=True)
class Terrain:
    """Die fertige Geologie einer Welt — einmal je Seed gebaut, nie pro Tick."""

    elevation: np.ndarray  # (H, W) float: die fertige Hoehe
    crust: np.ndarray      # (H, W) float: die unverformte Plattenbasis darunter
    plate_of: np.ndarray   # (H, W) int: Index der Platte, auf der die Zelle liegt
    plates: tuple[Plate, ...]
    sea_level: float       # elevation < sea_level ⇒ Wasser

    @property
    def relief(self) -> np.ndarray:
        """Wie weit eine Zelle von ihrer EIGENEN Kruste weggeschoben wurde.

        Das ist das Mass, in dem die Karte spricht — nicht die Hoehe ueber dem
        Meeresspiegel. Ein Berg ist, was sich ueber seine Plattenbasis hebt; ein Graben,
        was unter sie gerissen wird. Am Meeresspiegel gemessen luegen beide: er schwimmt
        mit dem Verhaeltnis von kontinentaler zu ozeanischer Flaeche, und ein Kontinental-
        sockel ueber einem tiefen Ozean gilt dann als "Gebirge", ganz ohne Hebung.
        """
        return self.elevation - self.crust

    @property
    def oceanic(self) -> np.ndarray:
        """(H, W) bool: liegt die Zelle auf ozeanischer Kruste?"""
        return np.array([p.oceanic for p in self.plates], dtype=bool)[self.plate_of]

    @property
    def land_fraction(self) -> float:
        """Anteil der Zellen ueber dem Meeresspiegel."""
        return float((self.elevation >= self.sea_level).mean())


def _scatter_plates(gen: Stream, cfg: MapConfig) -> tuple[Plate, ...]:
    """Streue die Keimpunkte und gib jeder Platte Richtung, Art und Dichte.

    Die Keimpunkte werden per *best candidate* gestreut (aus mehreren Vorschlaegen
    jeweils der entlegenste): rein gleichverteilte Punkte klumpen und erzeugen dann
    eine Riesenplatte neben Splittern — und damit genau eine Gebirgskette statt eines
    Netzes aus Grenzen.
    """
    points: list[tuple[float, float]] = []
    for _ in range(cfg.plate_count):
        best: tuple[float, float] = (gen.random(), gen.random())
        best_dist = -1.0
        for _ in range(8):  # Kandidaten je Keimpunkt
            cand = (gen.random(), gen.random())
            if points:
                d = min((cand[0] - px) ** 2 + (cand[1] - py) ** 2 for px, py in points)
            else:
                d = 1.0
            if d > best_dist:
                best, best_dist = cand, d
        points.append(best)

    # Mindestens eine Platte je Art — ohne beide gibt es keine Subduktion und damit
    # weder Kuestengebirge noch Tiefseegraben. Der Anteil schwankt um eine Platte,
    # sonst traegt JEDE Welt dieselbe Land/Meer-Bilanz.
    n_ocean = round(cfg.plate_count * cfg.oceanic_plate_fraction) + gen.choice((-1, 0, 1))
    n_ocean = max(1, min(cfg.plate_count - 1, n_ocean))
    kinds = [True] * n_ocean + [False] * (cfg.plate_count - n_ocean)
    gen.shuffle(kinds)

    plates: list[Plate] = []
    for point, oceanic in zip(points, kinds, strict=True):
        angle = gen.uniform(0.0, 2.0 * math.pi)
        lo, hi = _DENSITY_OCEANIC if oceanic else _DENSITY_CONTINENTAL
        base = _BASE_OCEANIC if oceanic else _BASE_CONTINENTAL
        plates.append(
            Plate(
                seed_point=point,
                drift=(math.cos(angle), math.sin(angle)),
                oceanic=oceanic,
                density=gen.uniform(lo, hi),
                base_height=base + gen.uniform(-_BASE_JITTER, _BASE_JITTER),
            )
        )
    return tuple(plates)


def _fbm(gen: OpenSimplex, xs: np.ndarray, ys: np.ndarray, octaves: int) -> np.ndarray:
    """Fraktales Rauschen: Oktaven mit doppelter Frequenz und halber Amplitude."""
    total = np.zeros_like(xs)
    amplitude, frequency, norm = 1.0, _NOISE_BASE_FREQ, 0.0
    for octave in range(octaves):
        # Versatz je Oktave, damit die Oktaven nicht am Ursprung uebereinanderliegen.
        offset = 17.0 * octave
        total += amplitude * _noise_field(gen, xs * frequency + offset, ys * frequency - offset)
        norm += amplitude
        amplitude *= _NOISE_GAIN
        frequency *= _NOISE_LACUNARITY
    return total / norm


def _noise_field(gen: OpenSimplex, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """``opensimplex`` ueber einem Gitter, elementweise (das Feld ist winzig)."""
    out = np.empty_like(xs)
    flat_x, flat_y, flat_out = xs.ravel(), ys.ravel(), out.ravel()
    for i in range(flat_x.size):
        flat_out[i] = gen.noise2(float(flat_x[i]), float(flat_y[i]))
    return out


def _gauss(u: np.ndarray, center: float, width: float) -> np.ndarray:
    """Gauss-Ruecken quer zur Grenze."""
    return np.exp(-(((u - center) / width) ** 2))


def _tectonic_relief(
    xs: np.ndarray, ys: np.ndarray, plates: tuple[Plate, ...], cfg: MapConfig, aspect: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Grundhoehe und Grenzrelief aus den Platten. ⇒ ``(base, relief, plate_of)``."""
    seeds = np.array([p.seed_point for p in plates], dtype=float)
    drift = np.array([p.drift for p in plates], dtype=float)
    oceanic = np.array([p.oceanic for p in plates], dtype=bool)
    density = np.array([p.density for p in plates], dtype=float)
    base_h = np.array([p.base_height for p in plates], dtype=float)

    # Abstand zu jedem Keimpunkt; die x-Achse gestaucht, weil die Zeichenzelle
    # doppelt so hoch wie breit ist (sonst werden alle Platten breitgezogen).
    dx = (xs[..., None] - seeds[:, 0]) * aspect
    dy = ys[..., None] - seeds[:, 1]
    dist = np.hypot(dx, dy)  # (H, W, P)

    order = np.argsort(dist, axis=2, kind="stable")  # stabil ⇒ Gleichstaende reproduzierbar
    first, second = order[..., 0], order[..., 1]
    d1 = np.take_along_axis(dist, first[..., None], axis=2)[..., 0]
    d2 = np.take_along_axis(dist, second[..., None], axis=2)[..., 0]

    # Abstand zur Grenze, in Einheiten der Saumbreite: 0 auf der Naht, 1 am Saumrand.
    u = (d2 - d1) / cfg.boundary_width

    # Grundhoehe: an der Naht die Mittelung beider Platten, nach innen die eigene —
    # sonst stuenden zwischen den Platten Klippen.
    blend = 0.5 + 0.5 * np.clip(u, 0.0, 1.0)
    base = base_h[first] * blend + base_h[second] * (1.0 - blend)

    # Relative Bewegung entlang der Grenznormalen (vom eigenen zum Nachbar-Keimpunkt).
    # Konstant je Grenzpaar ⇒ eine Grenze traegt ein einziges tektonisches Regime.
    nx = seeds[second, 0] - seeds[first, 0]
    ny = seeds[second, 1] - seeds[first, 1]
    norm = np.hypot(nx, ny)
    norm[norm == 0.0] = 1.0
    nx, ny = nx / norm, ny / norm
    approach = (drift[first, 0] - drift[second, 0]) * nx + (
        drift[first, 1] - drift[second, 1]
    ) * ny
    # Driftvektoren sind Einheitsvektoren ⇒ ``approach`` liegt in -2..2. Bei 1 laufen
    # beide mit halber Geschwindigkeit direkt aufeinander zu — das ist volle Wucht;
    # darueber (der Frontalfall) saettigt es. Kappen statt halbieren, sonst bleibt die
    # typische Grenze bei ~0.35 Wucht und die Tektonik ertrinkt im Rauschen.
    converging = np.clip(approach, 0.0, 1.0)   # laufen aufeinander zu
    diverging = np.clip(-approach, 0.0, 1.0)   # laufen auseinander

    own_ocean, other_ocean = oceanic[first], oceanic[second]
    strength = cfg.mountain_strength
    collision = ~own_ocean & ~other_ocean          # kontinental trifft kontinental
    subduction = ~collision                        # mindestens eine ozeanische Platte
    dives = density[first] > density[second]       # DIESE Zelle liegt auf der Unterplatte

    relief = np.zeros_like(u)
    # Kollision: breite Kette ueber der Naht, beide Seiten heben sich.
    relief += np.where(
        collision, strength * converging * _gauss(u, *_COLLISION_PROFILE), 0.0
    )
    # Subduktion, Unterplatte: der Tiefseegraben — seewaerts der Grenze.
    relief -= np.where(
        subduction & dives,
        _TRENCH_GAIN * strength * converging * _gauss(u, *_TRENCH_PROFILE),
        0.0,
    )
    # Subduktion, Oberplatte: Kuestengebirge (kontinental) bzw. Inselbogen (ozeanisch).
    over_gain = np.where(own_ocean, _ARC_GAIN, 1.0) * strength
    over_profile = np.where(
        own_ocean, _gauss(u, *_ARC_PROFILE), _gauss(u, *_CORDILLERA_PROFILE)
    )
    relief += np.where(subduction & ~dives, over_gain * converging * over_profile, 0.0)
    # Divergenz: Rift. Wie tief es reisst, haengt an der Kruste, auf der man STEHT —
    # kontinental ein Grabenbruch, ozeanisch ein breites, tiefes Becken. (Nach dem
    # Nachbarn zu gehen, riss auch die Kontinentalseite bis auf Grabentiefe auf.)
    rift_gain = np.where(own_ocean, _RIFT_GAIN_SEA, _RIFT_GAIN_LAND) * strength
    rift_width = np.where(own_ocean, _RIFT_WIDTH_SEA, _RIFT_WIDTH_LAND)
    relief -= rift_gain * diverging * np.exp(-((u / rift_width) ** 2))

    return base, relief, first


def _erode(elevation: np.ndarray, sea_level: float, cfg: MapConfig) -> np.ndarray:
    """EIN Durchgang Erosion: wo viel Wasser abfliesst, senkt es sein Bett.

    Abgetragen wird nach ``sqrt(Abfluss)`` — ein Rinnsal kratzt, ein Strom graebt. Das
    ist die ganze Regel, und sie genuegt, weil der Abfluss selbst schon alles weiss: er
    ist gross in den Taelern (dort sammelt sich das Wasser vieler Zellen) und winzig auf
    einem Kamm (dort faellt nur der eigene Regen). Also sinken die Taeler und die Kaemme
    bleiben stehen — die Kette bekommt eine Struktur, statt eine glatte Wand zu sein, und
    genau in die eingeschnittenen Rinnen legt sich hinterher der Fluss.

    Zwei Dinge daran sind gemessen, nicht geraten:

    * Der Regen ist der **echte Niederschlag** (:func:`rain.moisture_and_rain`), nicht
      etwa gleichverteilt. Mit gleichverteiltem Regen sucht die Erosion das Wasser dort,
      wo keines faellt: sie trug die Haenge um die Fluesse ab, und die Talquerschnitte an
      den Flusszellen wurden FLACHER als ganz ohne Erosion (+0.001 statt +0.053). Mit dem
      Regen, der die Fluesse auch fuellt, vertieft sie sie (+0.065). Wer das Tal schneidet,
      muss das Wasser sein, das darin fliesst.
    * Das **Gefaelle** steht NICHT in der Formel, obwohl die Lehrbuchform (``Stream
      Power``, ~ ``sqrt(A) x S``) es fordert. Es kehrte die Wirkung ebenfalls um: ein
      Talboden laeuft flach, ein Hang faellt steil — mit dem Gefaelle im Produkt trug die
      Erosion die HAENGE ab und liess die Rinne stehen, und nebenbei kostete es ein
      Fuenftel aller Gebirgsketten den Gipfel. Der Term gehoert in ein Modell mit
      Zeitschritten, in dem der Hang nachrutscht; in EINEM Durchgang luegt er.

    Ein Durchgang, keine Zeitachse (Ockham).
    """
    if cfg.erosion_strength <= 0.0:
        return elevation

    is_sea = elevation < sea_level
    _, rainfall = moisture_and_rain(elevation, sea_level, cfg)
    down, upstream_first = steepest_descent(elevation, is_sea)
    flow = accumulate(down, upstream_first, np.where(is_sea, 0.0, rainfall))

    peak_flow = float(flow.max()) or 1.0
    carve = cfg.erosion_strength * np.sqrt(flow / peak_flow)
    eroded = np.where(is_sea, elevation, elevation - carve).ravel()

    # Ein Bach kann sich nicht unter das Bett graben, in das er muendet. Bergab
    # durchlaufen (also gegen ``upstream_first``) sieht jede Zelle ihren Unterlauf schon
    # fertig — ein Durchgang genuegt, um das Gefaelle zu retten. Ohne ihn risse die
    # Erosion Loecher in ihr eigenes Flussbett (bergab waechst zwar der Abfluss, aber die
    # Abtragung ist nicht exakt monoton), und die Hydrologie fuellte sie hinterher brav zu
    # einer Kette winziger "Seen": kein Ergebnis, ein Artefakt.
    #
    # Die abflusslosen Senken (``down == -1``) bleiben davon unberuehrt — sie haben kein
    # Bett, in das sie muenden. Sie sammeln den Abfluss ihres Beckens und sinken darum
    # TIEFER: aus der Erosion faellt der See heraus, statt ihm zum Opfer zu fallen.
    for index in upstream_first[::-1]:
        target = int(down[index])
        if target >= 0:
            eroded[index] = max(eroded[index], eroded[target])
    return eroded.reshape(elevation.shape)


@lru_cache(maxsize=8)
def build_terrain(
    seed: int,
    width: int = MAP_WIDTH,
    height: int = MAP_HEIGHT,
    cfg: MapConfig = DEFAULT_MAP_CONFIG,
) -> Terrain:
    """Baue die Geologie einer Welt: Platten ⇒ Grenzrelief ⇒ fBm ⇒ Meeresspiegel.

    Reine Funktion von ``(seed, width, height, cfg)`` und gecacht: sie laeuft
    **einmal** je Welt, nie pro Tick. Der Zufall kommt aus dem **kosmetischen**
    Sub-Strom ``"terrain"`` — die Karte kann den semantischen Pfad nicht beruehren.
    """
    gen = Rng(seed).cosmetic_stream("terrain")
    plates = _scatter_plates(gen, cfg)
    noise = OpenSimplex(gen.getrandbits(63))

    # Zellmittelpunkte im Einheitsquadrat — derselbe Raum wie ``Region.coord``.
    xs, ys = np.meshgrid(
        (np.arange(width) + 0.5) / width, (np.arange(height) + 0.5) / height
    )
    aspect = (width / _CHAR_RATIO) / height

    # Domain-Warp: die Plattengrenzen maeandern, statt schnurgerade zu verlaufen.
    warp_x = xs + _WARP_AMPLITUDE * _noise_field(noise, xs * _WARP_FREQ, ys * _WARP_FREQ)
    warp_y = ys + _WARP_AMPLITUDE * _noise_field(
        noise, xs * _WARP_FREQ + 41.0, ys * _WARP_FREQ + 13.0
    )

    crust, relief, plate_of = _tectonic_relief(warp_x, warp_y, plates, cfg, aspect)
    # UEBERLAGERN, nicht ersetzen: die Tektonik traegt die Struktur, das fBm die Rauheit.
    roughness = cfg.noise_strength * _fbm(noise, xs, ys, cfg.noise_octaves)
    elevation = crust + relief + roughness

    # Erosion braucht schon eine Kueste, um zu wissen, wohin das Wasser laeuft; der
    # endgueltige Meeresspiegel faellt aber erst DANACH (das Abgetragene verschoebe ihn
    # sonst). Also zweimal dasselbe Quantil — beim zweiten Mal auf dem fertigen Relief.
    elevation = _erode(elevation, float(np.quantile(elevation, 1.0 - cfg.land_fraction)), cfg)

    # Der Meeresspiegel faellt ZULETZT, als Quantil der fertigen Hoehen: so traegt jeder
    # Seed denselben Landanteil, statt mal Wasserwelt, mal Trockenplanet zu sein. Er
    # entscheidet aber NUR ueber Land und Wasser — was eine Zelle IST (Ebene, Gebirge,
    # Graben), liest die Karte am ``relief``, nicht an ihm. Siehe :attr:`Terrain.relief`:
    # der Meeresspiegel schwimmt mit dem Verhaeltnis von Kontinent zu Ozean, und an ihm
    # gemessen gilt ein blosser Kontinentalsockel ueber tiefem Meer als "Gebirge".
    sea_level = float(np.quantile(elevation, 1.0 - cfg.land_fraction))

    for field in (elevation, crust, plate_of):
        field.setflags(write=False)  # gecacht ⇒ nicht mutieren
    return Terrain(
        elevation=elevation,
        crust=crust,
        plate_of=plate_of,
        plates=plates,
        sea_level=sea_level,
    )
