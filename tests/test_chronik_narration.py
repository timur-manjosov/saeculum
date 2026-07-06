"""Strukturierte Chronik-Narration + Welt-Bilanz (Grundlage des static-Renderers).

Die Praesentation konsumiert diese Daten; hier wird geprueft, dass sie
**deterministisch** sind (kein RNG in der Chronik), korrekt gegliedert und mit der
bestehenden String-Chronik konsistent. Reine Chronik-Ebene — ohne ``rich``.
"""

from __future__ import annotations

from worldsim.chronicle import (
    Weltbilanz,
    Zeitalter,
    chronik_mit_zeitaltern,
    chronik_strukturiert,
    epochen,
    weltbilanz,
)
from worldsim.config import DEFAULT_CONFIG
from worldsim.driver import simulate
from worldsim.events import EventKind


def test_structured_chronicle_is_deterministic() -> None:
    """Gleicher Lauf ⇒ identische strukturierte Chronik (Narration ohne RNG)."""
    wa, la = simulate(seed=42, years=150)
    wb, lb = simulate(seed=42, years=150)
    assert chronik_strukturiert(wa, la, DEFAULT_CONFIG) == chronik_strukturiert(
        wb, lb, DEFAULT_CONFIG
    )


def test_weltbilanz_is_deterministic_and_consistent() -> None:
    """Die Welt-Bilanz ist deterministisch und stimmt mit dem Weltzustand ueberein."""
    world, log = simulate(seed=42, years=150)
    a = weltbilanz(world, log)
    b = weltbilanz(*simulate(seed=42, years=150))
    assert a == b
    assert isinstance(a, Weltbilanz)
    assert a.nationen == len(world.polities)
    assert a.glauben == len(world.identities)
    assert a.zeitalter == len(epochen(world, log))
    # Die groesste Nation traegt wirklich das groesste Territorium.
    assert a.groesstes_territorium == max(len(p.territory) for p in world.polities.values())


def test_structured_ages_match_epochs_and_are_named() -> None:
    """Die Zeitalter-Gliederung deckt sich mit ``epochen`` (Name + Startjahr)."""
    world, log = simulate(seed=42, years=150)
    ages = chronik_strukturiert(world, log, DEFAULT_CONFIG)
    assert all(isinstance(a, Zeitalter) for a in ages)
    assert (ages[0].name, ages[0].start_year) == ("the First Expansion", 0)
    assert [(a.start_year, a.name) for a in ages] == epochen(world, log)
    # Jeder Eintrag traegt eine Ereignisart und eine "Year N: ..."-Narration.
    entries = [e for a in ages for e in a.eintraege]
    assert entries
    assert all(isinstance(e.kind, EventKind) for e in entries)
    assert all(e.text.startswith(f"Year {e.year}:") for e in entries)


def test_structured_narration_matches_string_chronicle() -> None:
    """Die flachen Eintragstexte gleichen exakt den "Year ..."-Zeilen der String-Chronik."""
    world, log = simulate(seed=7, years=120)
    ages = chronik_strukturiert(world, log, DEFAULT_CONFIG)
    flat = [e.text for a in ages for e in a.eintraege]
    string_lines = [
        line for line in chronik_mit_zeitaltern(world, log, DEFAULT_CONFIG)
        if line.startswith("Year ")
    ]
    assert flat == string_lines


def test_formative_figures_are_turning_point_successions() -> None:
    """Praegende Figuren sind genau Herrscher, deren Sukzession ein Wendepunkt war."""
    world, log = simulate(seed=42, years=200)
    bilanz = weltbilanz(world, log, max_figuren=5)
    turning_successions = [
        e
        for e in log
        if e.kind == EventKind.SUKZESSION
        and any(eff.field == "wendepunkt" for eff in e.effects)
    ]
    assert turning_successions  # der Lauf hat welche
    assert len(bilanz.figuren) == min(5, len(turning_successions))
    # Die letzte gefuehrte Figur entspricht der juengsten Wendepunkt-Sukzession.
    assert bilanz.figuren[-1].year == turning_successions[-1].year
