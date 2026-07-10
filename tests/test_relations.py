"""Aenderung 3: das historische Gedaechtnis — die zerfallende Beziehungs-Matrix.

Binaere Allianz-Schalter sind ersetzt: ``World.relations`` haelt gerichtete
``Relation``-Kanten (favor/dependency, sparse), favor zerfaellt ueber Jahrzehnte
Richtung 0, und Buendnis/Feindschaft werden pro Tick aus Schwellen ABGELEITET
statt gespeichert. Diese Tests sichern: Determinismus (inkl. Unabhaengigkeit
von der Einfuegereihenfolge der Kanten), monotoner Zerfall ohne neue Aktionen,
und dass der abgeleitete Status mit favor uebereinstimmt — alte Feinde werden
nach Jahrzehnten wieder neutral.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from worldsim.config import Config
from worldsim.driver import simulate
from worldsim.events import EventKind, EventLog
from worldsim.models import Polity, Region, Relation, World
from worldsim.rng import Rng
from worldsim.systems import add_favor, allied, diplomacy, favor, hostile

A, B = 10, 11


def _two_nation_world(
    favor_ab: float, favor_ba: float, *, adjacent: bool = False
) -> World:
    """Minimale Welt mit zwei Nationen und gesetzten favor-Kanten.

    Ohne Soldaten (leere Schichten) ist alle Macht 0 ⇒ keine Furcht, keine
    Kooperation; ``adjacent`` steuert, ob die Nachbarschafts-Annaeherung wirkt.
    """
    regions = {
        0: Region(id=0, food_capacity=10.0, nachbarn=(1,) if adjacent else (), owner=A),
        1: Region(id=1, food_capacity=10.0, nachbarn=(0,) if adjacent else (), owner=B),
    }
    world = World(
        regions=regions,
        polities={
            A: Polity(id=A, capital=0, territory=(0,)),
            B: Polity(id=B, capital=1, territory=(1,)),
        },
    )
    add_favor(world, A, B, favor_ab)
    add_favor(world, B, A, favor_ba)
    return world


def _run_diplomacy(world: World, years: int, cfg: Config) -> EventLog:
    """Laufe nur das diplomacy-System (isoliert den favor-Zerfall)."""
    master = Rng(0)
    log = EventLog()
    for year in range(years):
        world.year = year
        diplomacy(world, master.stream(f"diplomacy:{year}"), cfg, log)
    return log


def test_polity_has_no_alliance_fields() -> None:
    """Buendnis/Trust sind keine Nations-Felder mehr — die Matrix lebt in World."""
    pol = Polity(id=0)
    assert not hasattr(pol, "allies")
    assert not hasattr(pol, "relations")
    assert World().relations == {}


def test_relation_is_frozen_pure_data() -> None:
    """``Relation`` ist reiner, unveraenderlicher Wert (fortgeschrieben per replace)."""
    rel = Relation()
    assert (rel.favor, rel.dependency) == (0.0, 0.0)
    with pytest.raises(FrozenInstanceError):
        rel.favor = 1.0  # type: ignore[misc]


def test_add_favor_clamps_and_ignores_self_edges() -> None:
    """Der zentrale Helfer klammert favor auf [-1, +1] und verwirft a==a."""
    world = _two_nation_world(0.0, 0.0)
    for _ in range(5):
        add_favor(world, A, B, 0.6)
        add_favor(world, B, A, -0.6)
    assert favor(world, A, B) == 1.0
    assert favor(world, B, A) == -1.0
    add_favor(world, A, A, 0.9)
    assert (A, A) not in world.relations


def test_favor_decays_monotonically_toward_zero() -> None:
    """Ohne neue Aktionen zerfaellt favor monoton Richtung 0 — beide Vorzeichen.

    Winzige Kanten entfallen ganz (sparse Matrix): nach genug Jahrzehnten ist
    die Matrix leer.
    """
    cfg = Config()
    world = _two_nation_world(0.8, -0.8, adjacent=False)
    prev_ab, prev_ba = favor(world, A, B), favor(world, B, A)
    master = Rng(0)
    log = EventLog()
    for year in range(150):
        world.year = year
        diplomacy(world, master.stream(f"diplomacy:{year}"), cfg, log)
        cur_ab, cur_ba = favor(world, A, B), favor(world, B, A)
        if (A, B) in world.relations:
            assert 0.0 < cur_ab < prev_ab  # monoton, Vorzeichen bleibt
        if (B, A) in world.relations:
            assert prev_ba < cur_ba < 0.0
        prev_ab, prev_ba = cur_ab, cur_ba
    assert world.relations == {}  # verblasst = geloescht (sparse)


def test_derived_status_matches_favor() -> None:
    """Buendnis-/Feindschafts-Status folgen exakt den favor-Schwellen."""
    cfg = Config()  # alliance_favor_threshold=0.5, enmity_favor_threshold=-0.25

    both_high = _two_nation_world(0.6, 0.55)
    assert allied(both_high, A, B, cfg) and allied(both_high, B, A, cfg)
    assert not hostile(both_high, A, B, cfg)

    one_sided = _two_nation_world(0.9, 0.4)
    assert not allied(one_sided, A, B, cfg)  # Buendnis verlangt BEIDE Seiten

    one_grudge = _two_nation_world(0.9, -0.3)
    assert hostile(one_grudge, A, B, cfg)  # einseitiger Groll vergiftet das Paar
    assert hostile(one_grudge, B, A, cfg)  # ... symmetrisch abgeleitet

    mild = _two_nation_world(-0.2, -0.2)
    assert not hostile(mild, A, B, cfg)  # oberhalb der Schwelle: nur Verstimmung

    neutral = _two_nation_world(0.0, 0.0)
    assert not allied(neutral, A, B, cfg)
    assert not hostile(neutral, A, B, cfg)


def test_old_enemies_become_neutral_after_decades() -> None:
    """Der Zerfall ist die Vergebung: tiefer Groll verblasst, dann greift die
    Annaeherung friedlicher Nachbarn wieder — alte Feinde werden neutral."""
    cfg = Config()
    world = _two_nation_world(-0.9, -0.9, adjacent=True)
    assert hostile(world, A, B, cfg)
    _run_diplomacy(world, 100, cfg)
    assert not hostile(world, A, B, cfg)
    assert favor(world, A, B) > 0.0  # nach der Vergebung: wieder Annaeherung
    assert favor(world, B, A) > 0.0


@pytest.mark.parametrize("seed", [11, 42])
def test_determinism_of_relations(seed: int) -> None:
    """Gleicher Seed ⇒ identische Matrix und identische Buendnis-Events."""
    wa, la = simulate(seed=seed, years=120)
    wb, lb = simulate(seed=seed, years=120)
    assert wa.relations == wb.relations

    def alliance_trace(log: EventLog) -> list[tuple[int, EventKind, tuple[int, ...]]]:
        return [
            (e.id, e.kind, e.subjects)
            for e in log
            if e.kind in (EventKind.BUENDNIS, EventKind.BUENDNIS_BRUCH)
        ]

    assert alliance_trace(la) == alliance_trace(lb)


def test_matrix_iteration_is_insertion_order_independent() -> None:
    """Determinismus-Vertrag: ueber die Matrix wird nur (a_id, b_id)-sortiert
    iteriert — die Einfuegereihenfolge der Kanten darf nichts aendern."""
    cfg = Config()
    edges = [((A, B), 0.7), ((B, A), 0.6), ((A, 12), -0.5), ((12, A), 0.3)]

    def build(ordering: list[tuple[tuple[int, int], float]]) -> World:
        world = _two_nation_world(0.0, 0.0)
        world.polities[12] = Polity(id=12)
        for (a, b), value in ordering:
            add_favor(world, a, b, value)
        return world

    forward, backward = build(edges), build(edges[::-1])
    log_f = _run_diplomacy(forward, 30, cfg)
    log_b = _run_diplomacy(backward, 30, cfg)
    assert forward.relations == backward.relations
    assert [(e.kind, e.subjects) for e in log_f] == [(e.kind, e.subjects) for e in log_b]


def test_alliances_emerge_and_are_reported_from_favor() -> None:
    """In der echten Sim entstehen Buendnisse aus der Matrix (BUENDNIS-Events),
    und mancher Bruch kommt vom blossen Zerfall — Feinde/Freunde sind dynamisch."""
    _, log = simulate(seed=42, years=200)
    kinds = [e.kind for e in log]
    assert EventKind.BUENDNIS in kinds
    assert EventKind.BUENDNIS_BRUCH in kinds
