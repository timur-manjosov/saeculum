"""Die aufgeraeumte Karte: liest man auf EINEN Blick, was wo ist? (Schritt 4)

Die Behauptung dieses Schritts ist nicht "die Farben sind jetzt anders", sondern:
**Wasser, freies Land und wessen Territorium sind auf einen Blick auseinanderzuhalten, und
die Grenzen sind scharf.** Das ist messbar, also wird es hier gemessen — als Verteilung
ueber die LAUFENDE Simulation, nicht an einer gebauten Welt (vgl. ``test_wegekosten``).

Zwei Dinge tragen die Pruefungen, und beide sind gegen die naheliegende falsche Kontrolle
gebaut:

1. **Die richtige Kontrolle ist die Nachbarschaft.** Zwei Toene, die auf keiner Karte je
   nebeneinander liegen, kann niemand verwechseln — sie gegeneinander zu messen erzeugt
   nur Fehlalarm. Geprueft wird darum je Paar BENACHBARTER Zellen (und je Paar
   benachbarter Reiche), nicht kreuzweise ueber alles. Dieselbe Lehre wie in Schritt 3.
2. **Die Metrik ist ueberall dieselbe** (:func:`worldmap._tone_distance`, redmean): sowohl
   "sehen zwei Reiche gleich aus?" als auch "sieht ein Reich aus wie das Meer?" ist die
   Frage nach wahrgenommenem Abstand. Eine Zahl, ein Massstab.

Aussen vor bleibt bewusst der Geschmack: dass die See blau ist, prueft hier nichts. Nur
was man **verwechseln** kann, ist ein Fehler.
"""

from __future__ import annotations

import numpy as np
import pytest
from worldsim.config import DEFAULT_MAP_CONFIG
from worldsim.driver import simulate
from worldsim.presentation import worldmap as W
from worldsim.presentation.render import Steuerung
from worldsim.presentation.worldmap import (
    MAP_VIEWS,
    POLITICAL_VIEW,
    TERRAIN_VIEW,
    _luma,
    _tone_distance,
)

SEEDS = range(8)
YEARS = 250

# Ab hier gelten zwei Toene als sicher auseinanderzuhalten.
#
# Bewusst UNTER ``polity_tone_min_distance`` (170): darauf ZIELT die Faerbung, garantieren
# kann sie es nicht. Hat eine Polity mehr Nachbarn, als die Palette weit auseinander-
# liegende Toene hat, nimmt sie den entferntesten — das ist der Notfall, und er ist besser
# als jede Alternative (Abbruch gibt es nicht, und eine Faerbung nach Nachbarzahl liesse
# die Farben von Jahr zu Jahr flackern). Gemessen faellt sie dabei nie unter **105.9**, und
# das ist immer dasselbe Paar: ``iris`` gegen ``foam``, Violett gegen Cyan — unschoen nah
# beieinander, aber nicht zu verwechseln. Nie trugen zwei Nachbarn denselben Ton
# (30 Seeds x 250 J. und 20 Seeds x 400 J.: 0 von 776 Paaren).
#
# Die Schranke laesst dem Notfall diese Luft und schlaegt trotzdem hart an, sobald die
# alten Beinah-Zwillinge (love/rose 86, gold/rose 93) zurueckkehren.
_REALM_GAP = 100.0
# Fuer die drei FLAECHEN reicht weniger: sie muessen unverwechselbar sein, konkurrieren
# aber nicht um dieselbe Rolle. Der Wert ist die gemessene Untergrenze mit etwas Luft, und
# die beiden engsten Paare sind beide keine Reglerfrage mehr, sondern eine des Farbtons:
#
# * **Packeis neben einem Reich (63)** — das schwaechste Paar der Karte. Das Eis ist der
#   einzige Ton in einer LUECKE statt in einem Band: nach oben draengt das weissliche
#   ``text``-Reich (225), nach unten das freie Land (~102). Hell kommt es ``text`` auf 38
#   nahe, dunkel dem freien Polarland auf 33; bei 175 haelt es zu beidem Abstand, bleibt
#   aber einem blassen ``foam``-Saum auf 63 nahe (beides blasse Blautoene). Dass das Wasser
#   KEIN Zeichen traegt, ist genau hier die Rueckfallebene.
# * **freies Land am Schelf (81)** — Graugruen gegen Blau; auch das ist ausgereizt.
_FIELD_GAP = 60.0


def _render(seed: int, years: int = YEARS, view: str = POLITICAL_VIEW):
    """Rendere eine echte Welt und gib je Zelle (Art, Glyphe, Grundton) zurueck.

    ``Art`` ist ``"sea"``, ``"ice"``, ``"free"``, ``"realm:<id>"`` oder ``"seat"`` — die
    Frage, die die Karte beantworten soll. Gemessen wird der Grund, denn seit Schritt 4
    traegt die **Flaeche** die Antwort und die Glyphe nur die Textur.

    Die Reihenfolge der Zuordnung ist Absicht: **erst Wasser, dann der Sitz**. Der
    Sitz-Marker wird beim Zeichnen zuerst gesetzt und ueberschreibt jede Zelle — wuerde er
    hier auch zuerst zugeordnet, koennte ein Sitz mitten im Wasser stehen, ohne dass es
    auffiele. Genau so blieb es sechsmal unbemerkt (er sass auf einem Binnensee). So
    herum faellt ein solcher Sitz der Wasser-Invariante zum Opfer, wie er soll.
    """
    world, _ = simulate(seed=seed, years=years)
    cfg = DEFAULT_MAP_CONFIG
    look = W._view_of(view, cfg)
    rids = sorted(world.regions)
    coords = np.array([world.regions[rid].coord for rid in rids], dtype=float)
    water = W.build_hydrology(seed, W.MAP_WIDTH, W.MAP_HEIGHT)
    climate, terrain = water.climate, water.terrain
    elevation = np.asarray(terrain.elevation)
    is_sea = elevation < terrain.sea_level
    nearest = W._nearest_region(coords, W.MAP_WIDTH, W.MAP_HEIGHT)
    owner_of = {rid: r.owner for rid, r in world.regions.items() if r.owner is not None}
    owner_grid = W._owner_grid(owner_of, nearest, rids, is_sea)
    layers = W._Layers(
        water=water, biome=climate.biome, temperature=np.asarray(climate.temperature),
        elevation=elevation, relief=terrain.relief, oceanic=terrain.oceanic,
        sea_level=terrain.sea_level, is_sea=is_sea, coastal=W._coastline(is_sea),
        shade=W._hillshade(elevation, cfg), owner_grid=owner_grid,
        border=W._borders(owner_grid), style=W._polity_styles(world, owner_grid, cfg),
        # Die Sitz-Marker gehoeren dazu: sie werden ZUERST gezeichnet und ueberschreiben
        # jede Zelle. Sie hier wegzulassen hiesse, die Karte zu pruefen, die nicht gedruckt
        # wird — genau so blieb sechsmal ein Sitz-Buchstabe auf einer Wasserzelle unbemerkt.
        caps=W._capital_cells(
            world, owner_of, rids, nearest, is_sea | np.asarray(water.lake)
        ),
        flashing=np.zeros_like(is_sea),
    )
    cells: dict[tuple[int, int], tuple[str, str, str]] = {}
    for row in range(W.MAP_HEIGHT):
        for col in range(W.MAP_WIDTH):
            glyph, style = W._cell(row, col, layers, look, cfg)
            ground = style.rsplit("on ", 1)[-1].strip()
            if is_sea[row, col]:
                frozen = climate.temperature[row, col] < cfg.sea_ice_temp
                kind = "ice" if frozen else "sea"
            elif water.lake[row, col]:
                kind = "sea"
            elif (row, col) in layers.caps:
                # Der Sitz ist ein Marker, keine Flaeche: ein dunkler Chip, der die
                # Helligkeits-Rangfolge bewusst durchbricht. Er zaehlt nur fuer die Frage,
                # ob er auf Land steht — nicht fuer die Baender der Flaechen.
                kind = "seat"
            elif owner_grid[row, col] >= 0:
                kind = f"realm:{int(owner_grid[row, col])}"
            else:
                kind = "free"
            cells[(row, col)] = (kind, glyph, ground)
    return world, layers, cells


# === Wasser: ruhig, geschlossen, unverwechselbar (Aufgabe 1) ================

def _printed(seed: int, view: str, years: int = YEARS) -> dict[tuple[int, int], str]:
    """Die WIRKLICH gedruckte Karte: je Zelle ihre Glyphe, aus dem fertigen Panel gelesen.

    Der Umweg ueber die Konsole ist Absicht. :func:`_render` baut die Lagen selbst nach und
    kann deshalb einen Fehler in der **Verdrahtung** von ``render_map`` gar nicht sehen —
    es prueft dann die Karte, die niemand druckt. Genau so entging der Sitz-Marker auf dem
    Binnensee dem ersten Anlauf dieses Tests: der Test baute die Marker richtig, der
    Renderer nicht.
    """
    from rich.console import Console

    world, _ = simulate(seed=seed, years=years)
    console = Console(force_terminal=False, width=W.MAP_WIDTH + 12, record=True)
    console.print(W.render_map(world, seed=seed, view=view))
    lines = console.export_text().split("\n")
    left = 2 + W._AXIS_WIDTH  # Rahmen "│ " plus die Breitengrad-Skala
    body = [line[left : left + W.MAP_WIDTH] for line in lines[1 : 1 + W.MAP_HEIGHT]]
    assert len(body) == W.MAP_HEIGHT and all(len(r) == W.MAP_WIDTH for r in body)
    return {(r, c): body[r][c] for r in range(W.MAP_HEIGHT) for c in range(W.MAP_WIDTH)}


def _wet_cells(seed: int) -> set[tuple[int, int]]:
    """Welche Zellen Wasser sind — Meer UND Binnensee — direkt aus der Geografie."""
    water = W.build_hydrology(seed, W.MAP_WIDTH, W.MAP_HEIGHT)
    is_sea = np.asarray(water.terrain.elevation) < water.terrain.sea_level
    wet = is_sea | np.asarray(water.lake)
    return {
        (r, c) for r in range(W.MAP_HEIGHT) for c in range(W.MAP_WIDTH) if wet[r, c]
    }


def test_water_is_the_only_field_without_a_sign() -> None:
    """Die Invariante, an der "Wasser ist nie mit Land verwechselbar" ueberhaupt haengt.

    Eine Zusage ueber Farben allein waere weich — Toene wandern, sobald jemand einen Regler
    dreht. Diese hier ist hart und billig zu pruefen: **die See ist die einzige Flaeche
    ohne Zeichen**. Jede Landzelle traegt eine Glyphe (Biom, Fluss, Polity oder Sitz), keine
    Wasserzelle traegt eine. Wer die Karte ueberfliegt, braucht darum gar keine Farbe, um
    Land von Meer zu trennen; und wer sie umfaerbt, kann diese Trennung nicht versehentlich
    kaputtmachen.

    Geprueft wird am **gedruckten** Panel gegen die Geografie — nicht an nachgebauten
    Lagen. Der Unterschied ist nicht theoretisch: der Sitz-Marker wird zuerst gezeichnet und
    ueberschreibt jede Zelle, und er sass gemessen sechsmal (8 Seeds) mitten auf einem
    Binnensee, weil die Verdrahtung nur das MEER als nass ansah.
    """
    for seed in SEEDS:
        for view in MAP_VIEWS:
            wet = _wet_cells(seed)
            for (row, col), glyph in _printed(seed, view).items():
                where = f"Seed {seed} {view} bei {row},{col}"
                if (row, col) in wet:
                    assert glyph == " ", f"{where}: Wasser traegt {glyph!r}"
                else:
                    assert glyph != " ", f"{where}: Land ohne Zeichen"


def test_the_sea_is_one_calm_surface() -> None:
    """Der Ozean traegt nur seine Tiefenstufen — kein Rauschen je Zelle.

    Vorher lag die Hoehenschattierung auch auf dem Wasser (``hillshade_water = 0.35``): das
    gab jeder Meerzelle ihre eigene Helligkeit und machte ~70 % der Karte zu einem
    flimmernden Feld. "Ruhig" heisst darum nachpruefbar: die ganze See kommt mit einer
    Handvoll Toenen aus (Graben, Tiefsee, Schelf, Saum, Eis, Suesswasser) — und nicht mit
    einem pro Zelle.
    """
    tones: set[str] = set()
    cells_seen = 0
    for seed in SEEDS:
        _, _, cells = _render(seed)
        for kind, _, ground in cells.values():
            if kind in ("sea", "ice"):
                tones.add(ground)
                cells_seen += 1
    assert cells_seen > 1000  # es gibt ueberhaupt Meer zu messen
    assert len(tones) <= 6, f"Die See traegt {len(tones)} Toene: {sorted(tones)}"


# === Die Hierarchie: Natur gedaempft, Politik dominant (Aufgabe 2) ==========

def test_no_free_land_outshines_a_realm() -> None:
    """Das hellste freie Land bleibt dunkler als das dunkelste Territorium.

    Der eigentliche Befund von Schritt 4: die Karte hatte keine **Helligkeits-Hierarchie**,
    und das Auge sortiert zuerst nach Helligkeit. Gemessen ueberlappten die Baender vorher
    restlos (freies Land 83..236 gegen Territorium 122..225) — eine freie Wueste (195)
    strahlte jedes ``pine``-Reich (122) nieder, und "Natur gedaempft, Politik dominant" war
    damit auf der Flaeche schlicht unwahr, so entsaettigt sie auch war.

    Blosses Daempfen konnte das nicht heilen, weil es MULTIPLIKATIV ist: es verschiebt das
    Band, ohne es zu verschmaelern. Erst das Ziehen auf eine Zielhelligkeit
    (``nature_luma``) stapelt die beiden Baender wirklich.
    """
    brightest_free = 0.0
    darkest_realm = 255.0
    for seed in SEEDS:
        _, _, cells = _render(seed)
        for kind, _, ground in cells.values():
            if kind == "free":
                brightest_free = max(brightest_free, _luma(ground))
            elif kind.startswith("realm:"):
                darkest_realm = min(darkest_realm, _luma(ground))
    assert brightest_free > 0.0 and darkest_realm < 255.0  # beides kommt vor
    assert brightest_free < darkest_realm, (
        f"Freies Land wird bis {brightest_free:.1f} hell, ein Reich nur bis "
        f"{darkest_realm:.1f} dunkel — die Natur ueberstrahlt die Politik."
    )


def test_neighbouring_fields_are_never_confusable() -> None:
    """Wo zwei verschiedene Flaechen einander BERUEHREN, sind sie klar verschieden.

    Die richtige Kontrolle: nur angrenzende Zellen. Kreuzweise ueber die ganze Karte zu
    messen faende Paare, die nie nebeneinander liegen (das Packeis der Pole gegen ein Reich
    am Aequator) — und wuerde an einem Problem alarmieren, das niemand sehen kann.

    Der Fall, der diesen Test wert macht, ist echt: ``pine #3e8fb0`` heisst zwar "Kiefer",
    ist aber ein Meeresblau, und ein pine-farbenes Reich an der Kueste lag gemessen **18**
    von der See entfernt — es WAR die See. Kein Regler half, weil es der Farbton selbst war.
    """
    worst: dict[tuple[str, str], float] = {}
    for seed in SEEDS:
        _, _, cells = _render(seed)
        for (row, col), (kind, _, ground) in cells.items():
            for drow, dcol in ((1, 0), (0, 1)):
                other = cells.get((row + drow, col + dcol))
                if other is None or other[0] == kind:
                    continue
                a = "realm" if kind.startswith("realm:") else kind
                b = "realm" if other[0].startswith("realm:") else other[0]
                if a == b:  # zwei Reiche: das prueft der Faerbungs-Test schaerfer
                    continue
                if "seat" in (a, b):  # ein Marker darf abstechen, das ist sein Zweck
                    continue
                key = (a, b) if a < b else (b, a)
                gap = _tone_distance(ground, other[2])
                worst[key] = min(worst.get(key, 1e9), gap)

    assert worst, "es gab keine benachbarten Flaechen zu messen"
    for (a, b), gap in sorted(worst.items()):
        assert gap >= _FIELD_GAP, f"{a} neben {b} liegen nur {gap:.1f} auseinander"


# === Grenzen und Unterscheidbarkeit (Aufgaben 4, 5) =========================

def test_a_realm_reads_as_one_body() -> None:
    """JE REICH gilt: der Rand ist heller als jede Zelle seines Inneren.

    Global gemessen sagte das nichts — ein helles ``text``-Reich haette jedes dunkle
    Nachbarreich "widerlegt", obwohl beide sauber umrissen sind. Die Frage ist immer die
    nach EINEM Reich: hebt sich sein Saum von seiner eigenen Flaeche ab? Nur dann liest es
    sich als zusammenhaengendes Gebilde und nicht als Wolke.
    """
    checked = 0
    for seed in SEEDS:
        _, layers, cells = _render(seed)
        rims: dict[str, set[str]] = {}
        cores: dict[str, set[str]] = {}
        for (row, col), (kind, _, ground) in cells.items():
            if not kind.startswith("realm:"):
                continue
            bucket = rims if layers.border[row, col] else cores
            bucket.setdefault(kind, set()).add(ground)
        for realm, rim in rims.items():
            core = cores.get(realm)
            if not core:
                continue  # ein Reich, das nur aus Rand besteht: nichts zu vergleichen
            checked += 1
            assert min(map(_luma, rim)) > max(map(_luma, core)), (
                f"Seed {seed}, {realm}: das Innere wird heller als der Rand"
            )
    assert checked > 20, f"nur {checked} Reiche mit Innerem gemessen — zu duenn"


def test_neighbouring_realms_never_wear_similar_colours() -> None:
    """Benachbarte Reiche tragen nie aehnliche Toene — und nie dieselbe Glyphe.

    "Verschieden" reicht dafuer nicht, und das ist der Kern von Aufgabe 5: die alte
    Faerbung mied nur denselben INDEX. Da ``love #eb6f92`` und ``rose #ea9a97`` aber nur 86
    auseinanderliegen, faerbte sie zwei Nachbarn brav "verschieden" und trotzdem
    ununterscheidbar — gemessen betraf das **27 % aller benachbarten Reichspaare**. Jetzt
    entscheidet der Abstand selbst.

    Die Glyphe haengt am selben Index wie der Ton: verschiedene Farbe ⇒ verschiedene Form.
    Darum bleibt der Besitz auch fuer farbschwache Augen lesbar.
    """
    pairs = 0
    for seed in SEEDS:
        world, _, cells = _render(seed)
        owner_grid = np.full((W.MAP_HEIGHT, W.MAP_WIDTH), -1, dtype=int)
        for (row, col), (kind, _, _) in cells.items():
            if kind.startswith("realm:"):
                owner_grid[row, col] = int(kind.split(":")[1])
        style = W._polity_styles(world, owner_grid, DEFAULT_MAP_CONFIG)
        for pid, others in W._polity_neighbours(owner_grid).items():
            for other in others:
                if pid >= other:
                    continue
                pairs += 1
                a, b = style[pid], style[other]
                assert a != b, f"Seed {seed}: Reiche {pid}/{other} teilen einen Ton"
                assert W._POLITY_GLYPHS[a] != W._POLITY_GLYPHS[b]
                gap = _tone_distance(W._POLITY_TONES[a], W._POLITY_TONES[b])
                assert gap >= _REALM_GAP, (
                    f"Seed {seed}: Reiche {pid}/{other} liegen nur {gap:.1f} auseinander"
                )
    assert pairs > 40, f"nur {pairs} Nachbarpaare gemessen — zu duenn"


def test_the_realm_symbol_never_swallows_its_own_field() -> None:
    """Die Polity-Glyphe ist HOHL — sonst erschlaegt sie die Farbe, die sie erklaeren soll.

    Seit die Flaeche die Polity-Farbe traegt, ist eine flaechige Glyphe ihr Gegner, und
    zwar nicht ein bisschen: ``■`` deckt fast die ganze Zelle ab, und in Kontrast-Tinte
    (auf ``gold #f6c177`` wird das ``#735e4f``) las sich ein goldenes Reich gemessen als
    **dunkelbraunes Feld**. Die Redundanz haette damit genau das Signal getilgt, dem sie
    Redundanz sein soll. Ein Ring laesst den Grund stehen und bleibt trotzdem eine Form.

    Der Test pinnt die Regel und nicht den Geschmack: welche Zeichen hohl sind, laesst sich
    aus dem Codepoint nicht rechnen, also steht die Liste hier — samt Grund, damit niemand
    die alten ``● ■ ◆`` beilaeufig zurueckholt, wenn ihm ein Ring zu zart vorkommt.
    """
    filled = set("●■◆◉◈▲▼◤◥◣◢★✦")
    for glyph in W._POLITY_GLYPHS:
        assert glyph not in filled, (
            f"{glyph} ist flaechig und deckt den Polity-Ton ab, statt auf ihm zu liegen"
        )


def test_the_realm_tones_stay_far_apart_and_out_of_the_sea() -> None:
    """Die Palette selbst haelt Abstand — von sich und vom Meer.

    Pinnt die beiden gemessenen Entscheidungen hinter ``_POLITY_TONES``, damit niemand
    ``rose`` oder ``pine`` beilaeufig zurueckholt: ``rose`` steckt in beiden schlechten
    Paaren der Palette (86 und 93), ``pine`` liegt 24 vom Ozean entfernt. Beide bleiben
    Ereignisfarben — nur als Landesfarbe taugen sie nicht.
    """
    from worldsim.presentation.palette import NATURAL_EARTH as N
    from worldsim.presentation.palette import ROSE_PINE_MOON as P

    assert P.rose not in W._POLITY_TONES
    assert P.pine not in W._POLITY_TONES
    assert len(W._POLITY_TONES) == len(W._POLITY_GLYPHS)
    # Fuenf Toene sind gemessen zu wenig: dann bekommen Nachbarn wieder denselben.
    assert len(W._POLITY_TONES) >= 6

    ocean = (N.abyss, N.deep_sea, N.shelf, N.coast, N.lake)
    for tone in W._POLITY_TONES:
        nearest = min(_tone_distance(tone, wet) for wet in ocean)
        assert nearest > 100.0, f"{tone} liegt nur {nearest:.1f} vom Meer entfernt"


# === Die zwei Ansichten (Aufgabe 6) ========================================

def test_both_views_draw_the_same_world() -> None:
    """Die Ansichten unterscheiden nur die Lautstaerke, nie die Tatsachen.

    Sonst waere die Umschalttaste eine zweite Wahrheit statt einer zweiten Brille: was
    Wasser ist, ist in beiden Wasser; wo eine Grenze laeuft, laeuft sie in beiden.
    """
    for seed in SEEDS:
        _, layers_a, cells_a = _render(seed, view=POLITICAL_VIEW)
        _, layers_b, cells_b = _render(seed, view=TERRAIN_VIEW)
        wet_a = {rc for rc, (kind, _, _) in cells_a.items() if kind in ("sea", "ice")}
        wet_b = {rc for rc, (kind, _, _) in cells_b.items() if kind in ("sea", "ice")}
        assert wet_a == wet_b
        assert layers_a.owner_grid.tolist() == layers_b.owner_grid.tolist()
        assert layers_a.border.tolist() == layers_b.border.tolist()


def test_the_political_view_hushes_the_land_the_terrain_view_shows() -> None:
    """Die politische Ansicht ist messbar die ruhigere — und die Terrain-Ansicht die reichere.

    Beides in einer Zahl: die Spanne der Helligkeiten, die freies Land annimmt. "Terrain nur
    angedeutet" heisst, dass diese Spanne schmal ist; "Geografie reich" heisst, dass sie es
    nicht ist. Ohne diesen Vergleich waere der Umschalter Dekoration.
    """
    spans: dict[str, float] = {}
    for view in MAP_VIEWS:
        lo, hi = 255.0, 0.0
        for seed in SEEDS:
            _, _, cells = _render(seed, view=view)
            for kind, _, ground in cells.values():
                if kind == "free":
                    lo, hi = min(lo, _luma(ground)), max(hi, _luma(ground))
        spans[view] = hi - lo
    assert spans[POLITICAL_VIEW] * 2 < spans[TERRAIN_VIEW], (
        f"politisch spannt {spans[POLITICAL_VIEW]:.1f}, terrain {spans[TERRAIN_VIEW]:.1f} — "
        "die politische Ansicht ist nicht wesentlich ruhiger"
    )


def test_the_map_view_is_a_key_not_a_rerun() -> None:
    """``m`` schaltet die Ansicht um; die Umschaltung ist reine Beobachtung."""
    ctrl = Steuerung()
    assert ctrl.view == POLITICAL_VIEW
    ctrl.taste("m")
    assert ctrl.view == TERRAIN_VIEW
    ctrl.taste("m")
    assert ctrl.view == POLITICAL_VIEW  # zyklisch, nicht einbahnig


@pytest.mark.parametrize("view", MAP_VIEWS)
def test_the_view_cannot_bend_the_world(view: str) -> None:
    """Zeichnen ist folgenlos und wiederholbar — in JEDER Ansicht.

    Die Karte ist seit Schritt 2 kanonisch (die Welt laeuft AUF ihr), aber sie zu ZEICHNEN
    darf sie nicht anruehren: kein Master-RNG, keine Mutation. Sonst haette die Wahl der
    Ansicht die Geschichte verbogen — der teuerste denkbare Fehler in einer reinen
    Praesentations-Aenderung.
    """
    from rich.console import Console

    def trace(seed: int) -> list[tuple[int, str]]:
        _, log = simulate(seed=seed, years=80)
        return [(e.year, e.kind.name) for e in log]

    before = trace(7)
    world, _ = simulate(seed=3, years=120)
    console = Console(force_terminal=True, color_system="truecolor", width=120, record=True)
    console.print(W.render_map(world, seed=3, view=view))
    once = console.export_text(styles=True)

    console = Console(force_terminal=True, color_system="truecolor", width=120, record=True)
    console.print(W.render_map(world, seed=3, view=view))
    assert console.export_text(styles=True) == once  # deterministisch
    assert trace(7) == before  # und folgenlos
