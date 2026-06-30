"""Phase 2: kausaler Event-Graph, trait-getriebene Diplomatie und Krieg."""

from __future__ import annotations

from worldsim.driver import simulate
from worldsim.events import EventKind


def test_world_has_diplomacy_and_war() -> None:
    """Aus den Wechselwirkungen entstehen Buendnisse, Kriege und Schlachten."""
    _, log = simulate(seed=42, years=200)
    kinds = {e.kind for e in log}
    assert EventKind.BUENDNIS in kinds
    assert EventKind.KRIEG in kinds
    assert EventKind.SCHLACHT in kinds


def test_every_war_event_has_nonempty_factors() -> None:
    """Verbindlich (§10.2): jedes Kriegs-Event traegt seine Begruendung."""
    _, log = simulate(seed=42, years=200)
    wars = [e for e in log if e.kind == EventKind.KRIEG]
    assert wars
    for event in wars:
        assert event.factors  # nicht leer
        # Ein Faktor mit Gewicht 0 darf nicht in der Begruendung stehen.
        assert all(factor.weight != 0.0 for factor in event.factors)


def test_causes_are_real_earlier_events() -> None:
    """Kausal-Invariante: causes sind real, frueher, nicht haengend/vorwaerts."""
    _, log = simulate(seed=42, years=200)
    for event in log:
        for cause_id in event.causes:
            assert 0 <= cause_id < event.id
            assert log.get(cause_id).year <= event.year


def test_battles_are_caused_by_their_war() -> None:
    """Jede Schlacht verweist kausal auf das ausloesende KRIEG-Event."""
    _, log = simulate(seed=42, years=200)
    battles = [e for e in log if e.kind == EventKind.SCHLACHT]
    assert battles
    for battle in battles:
        assert any(log.get(c).kind == EventKind.KRIEG for c in battle.causes)


def test_some_wars_cite_triggering_events() -> None:
    """Der Kriegswunsch verlinkt die ausloesenden Grenzreibungs-/Verlust-Events."""
    _, log = simulate(seed=42, years=200)
    wars = [e for e in log if e.kind == EventKind.KRIEG]
    assert any(event.causes for event in wars)


def test_war_factors_come_from_controlled_vocabulary() -> None:
    """Faktor-Labels stammen aus der zentralen FactorLabel-Sammlung (§8)."""
    from worldsim.events import FactorLabel

    vocabulary = {label.value for label in FactorLabel}
    _, log = simulate(seed=42, years=200)
    for event in log:
        for factor in event.factors:
            assert factor.label in vocabulary
