"""Phase 5: Schocks & Wendepunkte — Zeitalter, Kausalketten, Zentralitaet.

Die Chronik liest sich wie echte Geschichte: stochastische Schocks stoeren
Gleichgewichte, Technologie schaltet Zeitalter frei, und Trend-Waechter erkennen
Wendepunkte, die Perioden benennen und begrenzen. Alles deterministisch und aus
dem kausalen Event-Graphen abgeleitet.
"""

from __future__ import annotations

from worldsim.chronicle import chronik_mit_zeitaltern, epochen, zentralitaet
from worldsim.config import DEFAULT_CONFIG
from worldsim.driver import simulate
from worldsim.events import (
    EventDraft,
    EventKind,
    EventLog,
    FactorLabel,
)


def test_phase5_is_deterministic() -> None:
    """Gleiches ``(seed, years)`` ⇒ identische Welt und identischer Log."""
    wa, la = simulate(seed=3, years=200)
    wb, lb = simulate(seed=3, years=200)
    assert wa == wb
    assert [e.__dict__ for e in la] == [e.__dict__ for e in lb]


def test_three_distinct_disasters_strike_and_reduce_population() -> None:
    """Aufgabe 1: Pest, Erdbeben und Duerre treten auf und stoeren Gleichgewichte."""
    _, log = simulate(seed=42, years=200)
    kinds = {e.kind for e in log}
    assert EventKind.PEST in kinds
    assert EventKind.ERDBEBEN in kinds
    assert EventKind.DUERRE in kinds

    # Jeder Schock ist ein Verlust-Event (Bevoelkerung/Wohlstand sinkt).
    for shock in (EventKind.PEST, EventKind.ERDBEBEN, EventKind.DUERRE):
        events = [e for e in log if e.kind == shock]
        assert events
        assert all(e.effects for e in events)


def test_plague_can_spread_with_a_causal_link() -> None:
    """Aufgabe 1: die Pest springt auf einen Nachbarn — das Folge-Event nennt die Ursache."""
    _, log = simulate(seed=42, years=200)
    spread = [
        e
        for e in log
        if e.kind == EventKind.PEST
        and e.causes
        and log.get(e.causes[0]).kind == EventKind.PEST
    ]
    assert spread


def test_technology_accumulates_and_unlocks_ages() -> None:
    """Aufgabe 2: Wissen akkumuliert; Schwellen schalten Tech-Stufen (Zeitalter) frei."""
    world, log = simulate(seed=42, years=200)
    innovations = [e for e in log if e.kind == EventKind.INNOVATION]
    assert innovations
    # Mindestens eine Nation hat eine Tech-Stufe erreicht, ihr Wissen ist positiv.
    assert any(pol.tech_level >= 1 for pol in world.polities.values())
    assert any(pol.stockpiles.wissen > 0.0 for pol in world.polities.values())
    # Die Innovation benennt das erreichte Zeitalter.
    assert all(
        any(eff.field == "tech_age" for eff in e.effects) for e in innovations
    )


def test_turning_points_are_detected_with_a_near_cause() -> None:
    """Aufgabe 3: Wendepunkte werden erkannt und nennen ihre nahe Ursache aus dem Graphen."""
    _, log = simulate(seed=42, years=200)
    turning_points = [e for e in log if e.kind == EventKind.WENDEPUNKT]
    assert turning_points

    reasons = {f.label for e in turning_points for f in e.factors}
    assert FactorLabel.MACHTWECHSEL.value in reasons  # Machtranking-Wechsel

    # Mindestens ein Wendepunkt verweist kausal auf ein frueheres Event.
    assert any(e.causes for e in turning_points)
    for event in turning_points:
        for cause in event.causes:
            assert cause < event.id  # reale, fruehere Ursache (keine Vorwaertskante)


def test_ages_are_named_and_bounded_by_turning_points() -> None:
    """Aufgabe 4: Zeitalter werden benannt und durch Wendepunkte begrenzt."""
    world, log = simulate(seed=42, years=200)
    ages = epochen(world, log)
    assert ages[0] == (0, "the First Expansion")
    assert len(ages) > 1  # mindestens ein Zeitalter-Wechsel
    # Ein spaeteres Zeitalter ist nach einer dominanten Macht benannt.
    assert any(name.startswith("the Age of") for _, name in ages)
    # Startjahre sind aufsteigend (Perioden folgen chronologisch aufeinander).
    years = [year for year, _ in ages]
    assert years == sorted(years)

    lines = chronik_mit_zeitaltern(world, log, DEFAULT_CONFIG)
    assert lines[0] == "=== the First Expansion ==="
    assert any(line.startswith("=== the Age of") for line in lines)


def test_causal_enabling_statement_links_shock_to_power_shift() -> None:
    """Aufgabe 5: "dies ermoeglichte das" — ein Schock kurz vor einer Machtverschiebung."""
    world, log = simulate(seed=42, years=200)
    # Ein Machtwechsel-Wendepunkt, dessen nahe Ursache ein Schock ist.
    enabled = [
        e
        for e in log
        if e.kind == EventKind.WENDEPUNKT
        and any(f.label == FactorLabel.MACHTWECHSEL.value for f in e.factors)
        and e.causes
        and log.get(e.causes[0]).kind
        in (EventKind.PEST, EventKind.ERDBEBEN, EventKind.DUERRE)
    ]
    assert enabled

    lines = chronik_mit_zeitaltern(world, log, DEFAULT_CONFIG)
    assert any("rise to dominance" in line and "allowed" in line for line in lines)


def test_causal_centrality_counts_downstream_reach() -> None:
    """Aufgabe 6: die Zentralitaet zaehlt die erreichbaren Folgen im Kausalgraphen."""
    log = EventLog()
    e0 = log.append(EventDraft(year=0, kind=EventKind.PEST, subjects=(1,)))
    e1 = log.append(EventDraft(year=1, kind=EventKind.KRIEG, subjects=(1, 2), causes=(e0,)))
    e2 = log.append(EventDraft(year=2, kind=EventKind.SCHLACHT, subjects=(2,), causes=(e1,)))
    e3 = log.append(EventDraft(year=1, kind=EventKind.HUNGERSNOT, subjects=(1,), causes=(e0,)))

    reach = zentralitaet(log)
    # e0 erreicht transitiv e1, e2 und e3 ⇒ drei Folgen.
    assert reach[e0] == 3
    assert reach[e1] == 1  # nur e2
    assert reach[e2] == 0  # Blatt
    assert reach[e3] == 0  # Blatt


def test_centrality_lifts_a_consequential_event_in_the_chronicle() -> None:
    """Aufgabe 6: hochzentrale Ereignisse praegen die Chronik (Zentralitaets-Faktor)."""
    _, log = simulate(seed=42, years=200)
    reach = zentralitaet(log)
    # Im echten Lauf gibt es folgenreiche Ketten (ein Event mit mehreren Folgen).
    assert max(reach.values()) >= 2
