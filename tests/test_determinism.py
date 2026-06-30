"""Determinismus: gleiche Eingabe ⇒ identische Welt, identischer Log, identische Chronik.

Determinismus ist eine Architektur-Invariante. ``simulate(seed, years)`` ist
eine reine Funktion; zwei Laeufe mit gleichem Seed muessen einen identischen
Weltzustand, einen identischen Event-Log (inkl. EventIds) und eine identische
Text-Chronik liefern.
"""

from __future__ import annotations

from worldsim.chronicle import chronik
from worldsim.config import DEFAULT_CONFIG
from worldsim.driver import simulate
from worldsim.events import Event
from worldsim.rng import Rng


def _log_snapshot(log) -> list[Event]:
    """Event-Log als Liste frozen Events — direkt auf Gleichheit pruefbar."""
    return list(log)


def test_simulate_is_reproducible() -> None:
    world_a, log_a = simulate(seed=42, years=100)
    world_b, log_b = simulate(seed=42, years=100)

    assert world_a == world_b
    assert _log_snapshot(log_a) == _log_snapshot(log_b)


def test_chronicle_is_reproducible() -> None:
    world_a, log_a = simulate(seed=7, years=120)
    world_b, log_b = simulate(seed=7, years=120)

    assert chronik(world_a, log_a, DEFAULT_CONFIG) == chronik(world_b, log_b, DEFAULT_CONFIG)


def test_event_ids_are_stable_across_runs() -> None:
    _, log_a = simulate(seed=7, years=80)
    _, log_b = simulate(seed=7, years=80)

    assert [e.id for e in log_a] == [e.id for e in log_b]


def test_different_seeds_diverge() -> None:
    """Verschiedene Seeds sollen verschiedene Geschichten erzeugen."""
    world_a, log_a = simulate(seed=1, years=100)
    world_b, log_b = simulate(seed=2, years=100)

    assert chronik(world_a, log_a, DEFAULT_CONFIG) != chronik(world_b, log_b, DEFAULT_CONFIG)


def test_rng_named_streams_are_stable_and_distinct() -> None:
    rng = Rng(123)

    # Gleicher Name ⇒ gleiche Sequenz.
    a = [rng.stream("battle").random() for _ in range(5)]
    b = [rng.stream("battle").random() for _ in range(5)]
    assert a == b

    # Andere Namen ⇒ andere Sequenz (mit ueberwaeltigender Wahrscheinlichkeit).
    c = [rng.stream("ruler").random() for _ in range(5)]
    assert a != c

    # Semantischer und kosmetischer Namensraum sind getrennt.
    sem = [rng.stream("names").random() for _ in range(5)]
    cos = [rng.cosmetic_stream("names").random() for _ in range(5)]
    assert sem != cos


def test_rng_streams_are_independent() -> None:
    """Verbrauch eines Stroms beeinflusst andere Stroeme nicht."""
    rng = Rng(99)

    drained = rng.stream("a")
    for _ in range(1000):
        drained.random()

    b_first = rng.stream("b").random()
    b_again = rng.stream("b").random()
    assert b_first == b_again
