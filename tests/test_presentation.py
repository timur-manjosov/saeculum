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
from worldsim.events import EventDraft, EventKind, EventLog, FactorLabel
from worldsim.models import World
from worldsim.presentation import (
    ViewState,
    VisualKind,
    bevoelkerung_verlauf,
    biome_grid,
    ereignisse_pro_jahr,
    event_to_visual,
    live_dashboard,
    macht_verlauf,
    render_map,
    replay,
    sparkline,
    visuelle_historie,
    warum_entitaet,
    warum_event,
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
    """Krieg ist rot, Katastrophen blitzen, Gruendung setzt eine Stadt."""
    _, log = simulate(seed=42, years=150)
    by_kind = {}
    for e in log:
        by_kind.setdefault(e.kind, event_to_visual(e))
    assert by_kind[EventKind.KRIEG].kind == VisualKind.KRIEG
    assert "red" in by_kind[EventKind.KRIEG].color
    assert by_kind[EventKind.GRUENDUNG].kind == VisualKind.STADT
    for shock in (EventKind.PEST, EventKind.ERDBEBEN, EventKind.DUERRE):
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
    e0 = log.append(EventDraft(year=0, kind=EventKind.PEST, subjects=(1,)))
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


def test_why_event_root_has_no_cause_note() -> None:
    """Ein Wurzel-Event (ohne Ursachen) meldet ehrlich, dass es keine Ursache hat."""
    log = EventLog()
    e0 = log.append(EventDraft(year=0, kind=EventKind.PEST, subjects=(1,)))
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

def test_biome_grid_is_deterministic() -> None:
    world, _ = simulate(seed=42, years=10)
    a = biome_grid(world, seed=42)
    b = biome_grid(world, seed=42)
    assert list(a) == list(b)
    assert a.shape == (len(world.regions),)
    # Anderer Seed ⇒ (mit hoher Wahrscheinlichkeit) andere Biome.
    c = biome_grid(world, seed=99)
    assert list(a) != list(c)


def test_render_map_runs_headless() -> None:
    world, log = simulate(seed=42, years=100)
    view = ViewState()
    for e in log:
        view.apply(e)
    console = Console(force_terminal=False, width=100, record=True)
    console.print(render_map(world, seed=42, owners=dict(view.owner)))
    out = console.export_text()
    assert "world map" in out


# --- Aufgabe 2/4/8: Live & Replay laufen headless (Schnappschuss-Modus) -------

def test_live_and_replay_run_without_terminal() -> None:
    """Ohne TTY drucken Live und Replay Schnappschuss-Frames — schnell, ohne Sleep."""
    world, log = simulate(seed=42, years=120)
    console = Console(force_terminal=False, width=100, record=True)
    live_dashboard(world, log, DEFAULT_CONFIG, seed=42, show_map=False, console=console)
    replay(world, log, DEFAULT_CONFIG, seed=42, show_map=True, console=console)
    out = console.export_text()
    assert "LIVE" in out and "REPLAY" in out
    assert "year" in out


# --- Invariante: der headless Kern bleibt abhaengigkeitsfrei ------------------

def test_core_imports_without_presentation_deps() -> None:
    """Import des Kerns zieht **kein** rich/numpy/opensimplex nach (Einbahn-Schichten)."""
    code = (
        "import sys, worldsim.driver, worldsim.chronicle\n"
        "worldsim.driver.simulate(seed=1, years=3)\n"
        "leaked = [m for m in ('rich', 'numpy', 'opensimplex') if m in sys.modules]\n"
        "print('LEAK' if leaked else 'CLEAN', leaked)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.startswith("CLEAN"), result.stdout
