"""Phase 6: Praesentation, Replay & Werkzeuge.

Geprueft wird das, was die Schicht garantiert: (a) die **zentrale**
Ereignis→Visuell-Abbildung treibt Live und Replay gleichermassen, sodass das
Replay die visuelle Historie **konsistent** reproduziert; (b) der ``ViewState``
rekonstruiert den territorialen Endzustand allein aus dem Log (keine
Re-Simulation); (c) die "Warum?"-Abfrage traversiert den Kausalgraphen korrekt
rueckwaerts; (d) Sparklines/Karte sind deterministisch; (e) der Kern bleibt
abhaengigkeitsfrei.
"""

from __future__ import annotations

import subprocess
import sys

from rich.console import Console
from worldsim.config import DEFAULT_CONFIG
from worldsim.driver import simulate
from worldsim.events import EventDraft, EventKind, EventLog, Factor, FactorLabel
from worldsim.models import World
from worldsim.presentation import (
    ViewState,
    VisualKind,
    bevoelkerung_verlauf,
    build_terrain,
    ereignisse_pro_jahr,
    event_to_visual,
    macht_verlauf,
    render_map,
    replay,
    sparkline,
    visuelle_historie,
    warum_entitaet,
    warum_event,
    watch,
    weltlauf,
    zusammenfassung_zeilen,
)
from worldsim.presentation.query import finde_kollaps

# --- Aufgabe 3 & 4: eine Abbildung treibt Live UND Replay, konsistent ---------

def test_visual_history_is_deterministic() -> None:
    """Gleicher Lauf ⇒ identische visuelle Historie (Save = Seed)."""
    _, la = simulate(seed=42, years=120)
    _, lb = simulate(seed=42, years=120)
    ha = visuelle_historie(la)
    hb = visuelle_historie(lb)
    assert ha == hb
    assert len(ha) == len(la)


def test_every_event_maps_to_a_visual() -> None:
    """Die zentrale Abbildung deckt jedes emittierte Event ab (kein KeyError)."""
    _, log = simulate(seed=7, years=120)
    for event in log:
        vis = event_to_visual(event)
        assert isinstance(vis.kind, VisualKind)
        assert vis.event_id == event.id
        assert vis.color and vis.glyph


def test_visual_kinds_match_intent() -> None:
    """Krieg traegt den roten Akzent, Katastrophen blitzen, Gruendung setzt eine Stadt."""
    from worldsim.presentation import ROSE_PINE_MOON

    _, log = simulate(seed=42, years=150)
    by_kind = {}
    for e in log:
        by_kind.setdefault(e.kind, event_to_visual(e))
    assert by_kind[EventKind.KRIEG].kind == VisualKind.KRIEG
    # Farbe traegt Bedeutung: Krieg ist der ``love``-Akzent (Rot) der zentralen Palette.
    assert by_kind[EventKind.KRIEG].color == ROSE_PINE_MOON.love
    assert by_kind[EventKind.GRUENDUNG].kind == VisualKind.STADT
    # Abspaltung ist eine dynastische Spaltung ⇒ violett (``iris``), nicht gruen.
    if EventKind.ABSPALTUNG in by_kind:
        assert by_kind[EventKind.ABSPALTUNG].color == ROSE_PINE_MOON.iris
    for shock in (EventKind.ERDBEBEN,):
        if shock in by_kind:
            assert by_kind[shock].flash is True


def test_replay_viewstate_reproduces_final_territory() -> None:
    """Das Nachspielen des Logs rekonstruiert den Endbesitz **exakt** — kein Re-Sim."""
    world, log = simulate(seed=1234, years=200)
    view = ViewState()
    for event in log:
        view.apply(event)
    reconstructed = view.owner
    actual = {rid: r.owner for rid, r in world.regions.items() if r.owner is not None}
    assert reconstructed == actual


def test_replay_incremental_matches_full_playback() -> None:
    """Zwei Abspiel-Durchlaeufe (Live-artig & Replay-artig) ergeben denselben Zustand."""
    _, log = simulate(seed=3, years=150)
    a = ViewState()
    for event in log:
        a.apply(event)
    # Zweiter Durchlauf, jahresweise gruppiert (wie der Renderer es tut).
    b = ViewState()
    by_year: dict[int, list] = {}
    for event in log:
        by_year.setdefault(event.year, []).append(event)
    for year in sorted(by_year):
        for event in by_year[year]:
            b.apply(event)
    assert a.owner == b.owner
    assert a.territory_counts() == b.territory_counts()


# --- Aufgabe 6: die "Warum?"-Abfrage traversiert korrekt rueckwaerts ----------

def test_why_event_traverses_causes_backwards() -> None:
    """Kausalkette e2→e1→e0: die Ausgabe erreicht die Wurzel, Ursachen sind frueher."""
    log = EventLog()
    e0 = log.append(EventDraft(year=0, kind=EventKind.ERDBEBEN, subjects=(1,)))
    e1 = log.append(EventDraft(year=1, kind=EventKind.KRIEG, subjects=(1, 2), causes=(e0,)))
    e2 = log.append(EventDraft(year=2, kind=EventKind.SCHLACHT, subjects=(2, 1), causes=(e1,)))

    world = World()
    lines = warum_event(world, log, e2)
    text = "\n".join(lines)
    # Alle drei Ebenen erscheinen (Wurzel-Ursache inklusive).
    assert "Year 2" in text and "Year 1" in text and "Year 0" in text
    # Kopfzeile (= e2) plus die zwei Ursachen e1 und e0, keine Dubletten.
    assert len(lines) == 3
    # Reihenfolge: die Kette laeuft von der Wirkung (e2) zur Wurzel (e0).
    assert text.index("Year 2") < text.index("Year 1") < text.index("Year 0")


def _reibung(log: EventLog, year: int, a: int, b: int, weight: float) -> int:
    """Ein GRENZREIBUNG-Event der Richtung a→b mit gegebenem Gewicht."""
    return log.append(
        EventDraft(
            year=year,
            kind=EventKind.GRENZREIBUNG,
            subjects=(a, b),
            factors=(Factor(FactorLabel.GRENZREIBUNG, weight),),
        )
    )


def test_why_event_collapses_mirrored_friction_pairs() -> None:
    """Gespiegelte Reibung (A,B)/(B,A) erzaehlt EINE Aussage — nicht zwei Zeilen.

    ``friction`` fuehrt die Reibung je Richtung und emittiert pro Schwelle zwei
    Events; beide erzaehlen "between A and B". Gezeigt wird die staerkere Seite.
    """
    log = EventLog()
    schwach = _reibung(log, 40, 1, 2, 2.20)
    stark = _reibung(log, 40, 2, 1, 3.10)
    krieg = log.append(
        EventDraft(year=41, kind=EventKind.KRIEG, subjects=(1, 2), causes=(schwach, stark))
    )

    lines = warum_event(World(), log, krieg)
    reibungszeilen = [line for line in lines if "border tension" in line]
    assert len(reibungszeilen) == 1, reibungszeilen
    # Es ueberlebt die staerkere Richtung — der Betrag darf nicht verlorengehen.
    assert "+3.10" in reibungszeilen[0]


def test_why_event_keeps_directional_kinds_apart() -> None:
    """Nur symmetrische Arten fallen zusammen: bei SCHLACHT TRAEGT die Reihenfolge Sinn.

    (A schlaegt B) und (B schlaegt A) im selben Jahr sind zwei Ereignisse — ein
    Zusammenfassen wuerde eine echte Umkehr verbergen.
    """
    log = EventLog()
    hin = log.append(EventDraft(year=40, kind=EventKind.SCHLACHT, subjects=(1, 2)))
    zurueck = log.append(EventDraft(year=40, kind=EventKind.SCHLACHT, subjects=(2, 1)))
    wende = log.append(
        EventDraft(year=41, kind=EventKind.WENDEPUNKT, subjects=(1,), causes=(hin, zurueck))
    )

    lines = warum_event(World(), log, wende)
    assert len(lines) == 3  # Kopf + beide Schlachten


def test_why_chain_shows_no_mirrored_narration_in_a_real_run() -> None:
    """Im laufenden Lauf traegt keine Warum-Kette zwei gespiegelte Reibungszeilen.

    Gegenprobe am echten Log (nicht an einer gebauten Welt): fuer jeden Krieg mit
    Reibungs-Ursachen darf je Jahr hoechstens EINE Reibungszeile erscheinen.
    """
    world, log = simulate(seed=5, years=200)
    kriege = [e for e in log if e.kind == EventKind.KRIEG and e.causes]
    assert kriege, "Lauf ohne Krieg mit Ursachen — Testannahme gebrochen"

    geprueft = 0
    for krieg in kriege:
        lines = warum_event(world, log, krieg.id)
        reibung = [line for line in lines if "border tension" in line]
        if not reibung:
            continue
        geprueft += 1
        # "  └─ Year N: border tension rose between A and B. [Grenzreibung +w]"
        # Der Faktor-Anhang muss zuerst weg, sonst klebt er am zweiten Namen und
        # kein Spiegelpaar faende je sein Gegenstueck (der Test waere wirkungslos).
        schluessel = []
        for line in reibung:
            kern = line.split(" [")[0]
            jahr = kern.split(":")[0].strip(" └─")
            paar = frozenset(kern.split("between")[1].strip(" .").split(" and "))
            schluessel.append((jahr, paar))
        assert len(schluessel) == len(set(schluessel)), lines
    assert geprueft > 0, "keine Reibungs-Ursachen erreicht — Test ohne Aussage"


def test_why_event_root_has_no_cause_note() -> None:
    """Ein Wurzel-Event (ohne Ursachen) meldet ehrlich, dass es keine Ursache hat."""
    log = EventLog()
    e0 = log.append(EventDraft(year=0, kind=EventKind.ERDBEBEN, subjects=(1,)))
    lines = warum_event(World(), log, e0)
    assert any("root event" in line for line in lines)


def test_finde_kollaps_prefers_territorial_collapse() -> None:
    """Zu einer kollabierten Nation wird ihr Gebietskollaps-Wendepunkt gefunden."""
    _, log = simulate(seed=42, years=200)
    collapses = [
        e
        for e in log
        if e.kind == EventKind.WENDEPUNKT
        and any(f.label == FactorLabel.GEBIETSKOLLAPS.value for f in e.factors)
    ]
    assert collapses
    entity = collapses[0].subjects[0]
    found = finde_kollaps(log, entity)
    assert found is not None
    assert log.get(found).kind == EventKind.WENDEPUNKT


def test_why_entity_chain_reaches_a_root_cause() -> None:
    """Die Warum-Kette einer kollabierten Nation endet in einem Wurzel-Ereignis."""
    world, log = simulate(seed=42, years=200)
    collapses = [
        e
        for e in log
        if e.kind == EventKind.WENDEPUNKT
        and any(f.label == FactorLabel.GEBIETSKOLLAPS.value for f in e.factors)
    ]
    entity = collapses[0].subjects[0]
    lines = warum_entitaet(world, log, entity)
    assert len(lines) >= 2  # Kopf + mindestens eine Ursache
    assert lines[0].startswith("Why did")


def test_why_query_only_follows_earlier_causes() -> None:
    """Jede zitierte Ursache ist ein frueheres Event (keine Vorwaertskante)."""
    _, log = simulate(seed=1, years=150)
    # Ein Wendepunkt mit Ursachen dient als Wurzel der Abfrage.
    turning = next(e for e in log if e.kind == EventKind.WENDEPUNKT and e.causes)

    def check(eid: int) -> None:
        for cause in log.get(eid).causes:
            assert cause < eid
            check(cause)

    check(turning.id)


# --- Aufgabe 7: Statistik/Sparklines (deterministisch, aus dem Log) -----------

def test_sparkline_shapes_and_edge_cases() -> None:
    assert sparkline([]) == ""
    line = sparkline([1, 2, 3, 4, 5])
    assert len(line) == 5
    assert all(ch in "▁▂▃▄▅▆▇█" for ch in line)
    # Konstante Reihe ⇒ keine Nulldivision, gleiche Bloecke.
    flat = sparkline([3, 3, 3])
    assert len(flat) == 3 and len(set(flat)) == 1


def test_power_series_matches_final_world() -> None:
    """Die Gebiets-Zeitreihe endet exakt bei der Zahl belegter Felder der Welt."""
    world, log = simulate(seed=42, years=200)
    macht = macht_verlauf(log, 200)
    owned = sum(1 for r in world.regions.values() if r.owner is not None)
    assert int(macht[-1]) == owned
    # Deterministisch.
    assert list(macht) == list(macht_verlauf(log, 200))


def test_stats_series_are_derivable_and_nonempty() -> None:
    _, log = simulate(seed=7, years=100)
    events = ereignisse_pro_jahr(log, 100)
    pop = bevoelkerung_verlauf(log, DEFAULT_CONFIG, 100)
    assert events.shape == (100,)
    assert pop.shape == (100,)
    assert int(events.sum()) == len(log)
    assert pop[-1] > 0.0
    lines = zusammenfassung_zeilen(*simulate(seed=7, years=100), DEFAULT_CONFIG, 100)
    assert any("strongest nations" in ln for ln in lines)


# --- Aufgabe 5: prozedurale Karte (deterministisch) ---------------------------

def test_terrain_is_deterministic() -> None:
    """Das Hoehenfeld ist eine reine, reproduzierbare Funktion des Seeds (2D-Gitter)."""
    a = build_terrain(42).elevation
    assert a.ndim == 2 and a.shape[0] >= 1 and a.shape[1] >= 1
    assert a.tolist() == build_terrain(42).elevation.tolist()  # deterministisch (gecacht)
    # Anderer Seed ⇒ andere Welt.
    assert a.tolist() != build_terrain(99).elevation.tolist()


def test_render_map_runs_headless() -> None:
    world, log = simulate(seed=42, years=100)
    view = ViewState()
    for e in log:
        view.apply(e)
    console = Console(force_terminal=False, width=120, record=True)
    console.print(render_map(world, seed=42, owners=dict(view.owner)))
    out = console.export_text()
    assert "world map" in out


def test_map_paints_territories_in_polity_palette() -> None:
    """Territorien erscheinen in Polity-Farben der Rosé-Pine-Palette (wandernde Grenzen)."""
    from worldsim.presentation import ROSE_PINE_MOON

    world, _ = simulate(seed=42, years=150)
    assert any(r.owner is not None for r in world.regions.values())  # es gibt Territorien

    console = Console(force_terminal=True, color_system="truecolor", width=120, record=True)
    console.print(render_map(world, seed=42))
    ansi = console.export_text(styles=True)

    def rgb(hex_color: str) -> str:
        return f"{int(hex_color[1:3], 16)};{int(hex_color[3:5], 16)};{int(hex_color[5:7], 16)}"

    # Mindestens eine der Haupt-Polity-Farben faerbt Land ein.
    tones = (ROSE_PINE_MOON.love, ROSE_PINE_MOON.gold, ROSE_PINE_MOON.iris, ROSE_PINE_MOON.rose)
    assert any(rgb(t) in ansi for t in tones)


# --- Aufgabe 2/4/8: Live & Replay laufen headless (Schnappschuss-Modus) -------

def test_replay_runs_without_terminal() -> None:
    """Ohne TTY druckt Replay Schnappschuss-Frames — schnell, ohne Sleep."""
    world, log = simulate(seed=42, years=120)
    console = Console(force_terminal=False, width=100, record=True)
    replay(world, log, DEFAULT_CONFIG, seed=42, show_map=True, console=console)
    out = console.export_text()
    assert "REPLAY" in out
    assert "year" in out


def test_replay_banners_age_transitions() -> None:
    """Der Zeitraffer benennt das laufende Zeitalter und bannert Zeitalter-Wechsel."""
    from worldsim.chronicle import epochen

    world, log = simulate(seed=42, years=200)
    ages = epochen(world, log)
    console = Console(force_terminal=False, width=100, record=True)
    replay(world, log, DEFAULT_CONFIG, seed=42, show_map=False, console=console)
    out = console.export_text()
    # Jahr 0 ist immer ein Schnappschuss ⇒ das eroeffnende Zeitalter samt Banner erscheint.
    assert ages[0][1] in out  # "the First Expansion" (Kopfzeile + Banner)
    assert "from year 0" in out  # die Banner-Beschriftung des Zeitalter-Wechsels


def test_watch_drives_the_world_without_terminal() -> None:
    """watch treibt die Welt Jahr fuer Jahr; ohne TTY druckt es Schnappschuss-Frames."""
    console = Console(force_terminal=False, width=120, record=True)
    world, log = watch(42, 120, DEFAULT_CONFIG, speed=50, console=console)
    out = console.export_text()
    assert "WATCH" in out
    assert "year" in out
    assert "strongest polities" in out
    assert "world map" in out  # die Karte ist eingebunden
    # watch gibt den Endstand zurueck (fuer Fusszeile/Zusatzansichten).
    assert world.year == 119
    assert len(log) > 0


def test_key_mode_is_a_no_op_without_a_terminal() -> None:
    """Ohne TTY (Pipe/Test/Windows) gibt es nichts umzuschalten — und nichts zu retten."""
    from worldsim.presentation.render import _tastenmodus

    with _tastenmodus():
        pass  # kein Terminal, kein termios-Zugriff, keine Ausnahme


def test_live_views_show_their_keys_on_screen() -> None:
    """Beide bewegten Ansichten zeigen dieselbe Tastenleiste — Bedienung ohne Handbuch."""
    world, log = simulate(seed=42, years=30)

    for render in (
        lambda c: replay(world, log, DEFAULT_CONFIG, seed=42, show_map=False, console=c),
        lambda c: watch(42, 30, DEFAULT_CONFIG, speed=50, show_map=False, console=c),
    ):
        console = Console(force_terminal=False, width=100, record=True)
        render(console)
        out = console.export_text()
        assert "space pause" in out
        assert "q quit" in out


def test_live_views_start_in_the_requested_map_view() -> None:
    """--view waehlt die Anfangsansicht der Karte (die Taste 'm' bleibt der Rest)."""
    world, log = simulate(seed=42, years=30)

    console = Console(force_terminal=False, width=120, record=True)
    watch(42, 30, DEFAULT_CONFIG, speed=50, view="terrain", console=console)
    assert "terrain view" in console.export_text()

    console = Console(force_terminal=False, width=120, record=True)
    replay(world, log, DEFAULT_CONFIG, seed=42, view="terrain", console=console)
    assert "terrain view" in console.export_text()


def test_watch_drives_identically_to_simulate() -> None:
    """weltlauf spiegelt simulate exakt: gleiche Welt UND gleiche EventIds (Kern unberuehrt)."""
    from collections import deque

    wa, la = simulate(seed=42, years=150)
    letzte = deque(weltlauf(42, 150, DEFAULT_CONFIG), maxlen=1)
    assert letzte  # der Lauf hat Jahre
    world, log = letzte[0]
    assert world == wa
    assert tuple(log) == tuple(la)


# --- Aufgabe 5/7: interaktive Erkundung des Kausalgraphen (explore) ------------

def test_explore_traces_collapse_and_zooms_into_causes() -> None:
    """„Warum ist Polity X zerfallen?" — die Kette samt Faktoren, dann in die Ursache zoomen."""
    import re

    from worldsim.chronicle import erzaehle
    from worldsim.presentation import explore
    from worldsim.presentation.query import finde_kollaps

    world, log = simulate(seed=42, years=200)
    target = next(p for p in world.polities.values() if finde_kollaps(log, p.id) is not None)
    collapse = finde_kollaps(log, target.id)
    assert collapse is not None
    causes = sorted(log.get(collapse).causes)

    cmds = [f"why {target.name}"] + ([f"into {causes[0]}"] if causes else [])
    console = Console(force_terminal=False, width=100, record=True)
    explore(world, log, DEFAULT_CONFIG, seed=42, console=console, commands=cmds)
    out = console.export_text()
    flat = " ".join(out.split())  # robust gegen Zeilenumbruch im Baum

    assert "EXPLORE" in flat
    assert f"why did {target.name} suffer" in flat
    # Der Kopf der Kette ist exakt die Chronik-Narration des Rueckschlags (nur abgeleitet).
    assert " ".join(erzaehle(world, log, log.get(collapse)).split()) in flat
    # Jede Baumzeile traegt ihre dominanten Faktoren: ``label: +/-gewicht``.
    assert re.search(r"\w: [+-]\d", flat)
    assert f"#{collapse}" in flat  # Event-ids sind sichtbar (navigierbar)


def test_explore_shows_entity_biography() -> None:
    """Eine Entitaet waehlen ⇒ ihr Lebenslauf (alle Events mit ihr im Subjekt).

    Jede Biographie oeffnet mit der GEBURT der Nation — und die hat zwei Gestalten, seit
    Reiche zerbrechen koennen: eine Nation der Weltgenerierung wurde *gegruendet*, eine
    aus einer Mutter geborene hat sich *abgespalten* (oder ist aus deren Kollaps
    hervorgegangen). Beides steht am Anfang ihres Lebenslaufs, und beides ist ein Event
    mit Ursache — ein zusaetzliches Gruendungs-Event waere eine zweite, ursachenlose
    Geburt (Aenderung 7: der Graph ist lueckenlos, aber er erzaehlt nichts doppelt).
    """
    from worldsim.presentation import explore

    world, log = simulate(seed=42, years=120)
    for target in sorted(world.polities.values(), key=lambda p: -len(p.territory))[:3]:
        console = Console(force_terminal=False, width=100, record=True)
        explore(
            world, log, DEFAULT_CONFIG, seed=42, console=console, commands=[f"who {target.name}"]
        )
        out = console.export_text()
        assert f"life of {target.name}" in out
        assert "was founded in" in out or "split" in out or "collapsed" in out


def test_explore_headless_demo_is_derived_only() -> None:
    """Ohne Kommandos laeuft die Beispiel-Sitzung; sie erfindet nichts (nur Log-Ableitung)."""
    from worldsim.presentation import explore

    world, log = simulate(seed=7, years=120)
    console = Console(force_terminal=False, width=100, record=True)
    explore(world, log, DEFAULT_CONFIG, seed=7, console=console)  # commands=None ⇒ Demo
    out = console.export_text()

    assert "EXPLORE" in out
    # Unbekannte Eingaben werden abgewiesen, nicht halluziniert.
    console2 = Console(force_terminal=False, width=100, record=True)
    explore(world, log, DEFAULT_CONFIG, console=console2, commands=["who Nirgendwo", "why 99999"])
    assert "unknown entity" in console2.export_text()


# --- static-Renderer: die schoen gegliederte Gesamt-Chronik -------------------

def test_static_renderer_prints_structured_chronicle() -> None:
    """Der static-Renderer zeigt Titel, Zeitalter-Ueberschriften, Eintraege und Bilanz."""
    from worldsim.presentation import render_chronik

    world, log = simulate(seed=42, years=150)
    console = Console(force_terminal=False, width=100, record=True)
    render_chronik(world, log, DEFAULT_CONFIG, seed=42, years=150, console=console)
    out = console.export_text()

    assert "History Machine — seed 42, 150 years" in out  # Titel + Seed
    assert "the First Expansion" in out  # erste Zeitalter-Ueberschrift
    assert "the Age of" in out  # weitere, benannte Zeitalter
    assert "was founded in" in out  # erzaehlte Eintraege
    assert "the world at the end" in out  # Welt-Zusammenfassung
    assert "greatest realm" in out and "formative figures" in out


def test_static_and_watch_share_event_styling() -> None:
    """static und watch nutzen denselben Baustein: gleiche Glyphe je Ereignisart."""
    from worldsim.presentation.components import ereignis_text

    # Krieg traegt die Kriegsglyphe in beiden Ansichten (gemeinsame Optik-Quelle).
    war_line = ereignis_text(EventKind.KRIEG, "Year 5: A declared war on B.")
    assert "⚔" in war_line.plain
    assert "declared war on" in war_line.plain


def test_event_colors_come_from_the_central_palette() -> None:
    """Farbe aus EINER Quelle: jede Ereignisfarbe ist ein Ton der Rosé-Pine-Palette."""
    from dataclasses import astuple

    from worldsim.presentation import ROSE_PINE_MOON
    from worldsim.presentation.visual import stil_fuer

    palette_hexes = set(astuple(ROSE_PINE_MOON))
    for kind in EventKind:
        color, glyph, _ = stil_fuer(kind)
        assert color in palette_hexes, (kind, color)  # kein hartkodierter Hex-Wert
        assert glyph


def test_factor_and_cause_components_render_readably() -> None:
    """Dominante Faktoren erscheinen als ``label: gewicht``; Ursachen als ``↳ …``."""
    from worldsim.presentation import faktoren_text, kausal_zeile

    faktoren = faktoren_text([("Machtwechsel", 1.3), ("Furcht", -0.5)])
    assert "Machtwechsel: +1.3" in faktoren.plain
    assert "Furcht: -0.5" in faktoren.plain

    cause = kausal_zeile("Year 3: an earthquake struck Oreisa.")
    assert cause.plain.strip().startswith("↳")
    assert "an earthquake struck Oreisa" in cause.plain


def test_static_shows_indented_why_note_for_turning_points() -> None:
    """Unter Wendepunkten steht eingerueckt die dezente Warum-Kette (Faktoren + Ursache)."""
    from worldsim.presentation import render_chronik

    world, log = simulate(seed=42, years=150)
    console = Console(force_terminal=False, width=100, record=True)
    render_chronik(world, log, DEFAULT_CONFIG, seed=42, years=150, console=console)
    out = console.export_text()

    assert "a turning point" in out
    # Die Warum-Kette ist eingerueckt und verweist mit ↳ auf ein frueheres Ereignis.
    assert "↳ Year" in out


# --- Invariante: der headless Kern bleibt abhaengigkeitsfrei ------------------

def test_core_imports_without_presentation_deps() -> None:
    """Import des Kerns zieht die RENDERING-Schicht (``rich``) nicht nach.

    Schritt 2 hat die Geografie in den Kern gezogen: ``worldsim.geo`` leitet die
    Region-Eigenschaften ab (die Simulation laeuft AUF der Geografie), und der Worldgen
    baut sie ueber numpy/opensimplex. Diese sind seither legitime **Worldgen**-
    Abhaengigkeiten — kein Rendering. Die Einbahn-Invariante, die bleibt und die dieser
    Test schuetzt: der Kern weiss nichts von der DARSTELLUNG. ``rich`` (TUI/Farbe/Chronik-
    Optik) darf beim blossen ``simulate`` NIE geladen werden.
    """
    code = (
        "import sys, worldsim.driver, worldsim.chronicle\n"
        "worldsim.driver.simulate(seed=1, years=3)\n"
        "leaked = [m for m in ('rich',) if m in sys.modules]\n"
        "print('LEAK' if leaked else 'CLEAN', leaked)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.startswith("CLEAN"), result.stdout
