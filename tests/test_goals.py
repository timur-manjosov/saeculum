"""Aenderung 4: utility-basierte Zielwahl (gierig, ein Schritt, erklaerbar).

Fraktionen waehlen pro Tick per ``argmax`` aus einem festen Zielmenue, statt auf
Trait-Schwellen zu reagieren. Diese Tests sichern die drei Zusagen: Determinismus
(inklusive der Gleichstands-Regel "Zielreihenfolge, dann EntityId"), jede
Handlung traegt die **exakt** verwendete Faktorliste als Begruendung, und der
Ressourcenkrieg entsteht nachweisbar aus der Ressourcenlage — nicht aus Zufall.
"""

from __future__ import annotations

import pytest
from worldsim import systems
from worldsim.config import DEFAULT_CONFIG, Config
from worldsim.driver import simulate
from worldsim.events import EventKind, EventLog, FactorLabel
from worldsim.models import (
    GoalKind,
    NationTraits,
    Polity,
    Region,
    Stocks,
    Stratum,
    StratumKind,
    World,
)
from worldsim.rng import Rng
from worldsim.systems import demografie, favor, goals

# Feste Ziel-Ids der synthetischen Welten (Regionen 0..n, Nationen ab 10).
X, Y, Z = 10, 11, 12

# Faktoren, die einen Krieg als Ressourcenkrieg ausweisen.
RESOURCE_LABELS = {FactorLabel.RESSOURCENDRUCK, FactorLabel.EISENBEDARF}


def _strata(workers: float = 0.0, soldiers: float = 0.0) -> tuple[Stratum, ...]:
    return (
        Stratum(StratumKind.ARBEITER, size=workers),
        Stratum(StratumKind.SOLDAT, size=soldiers),
        Stratum(StratumKind.ELITE, size=0.0),
    )


def _run_goals(world: World, cfg: Config, seed: int = 0) -> EventLog:
    """Fuehre nur das ``goals``-System aus (isoliert die Zielwahl)."""
    log = EventLog()
    goals(world, Rng(seed).stream("goals:0"), cfg, log)
    return log


def _kinds(log: EventLog) -> list[EventKind]:
    return [e.kind for e in log]


# === Das Menue und das entfernte Schwellen-Modell ============================

def test_goal_menu_is_small_fixed_and_ordered() -> None:
    """Ein kleines, festes Menue; die Deklarationsreihenfolge bricht Gleichstaende."""
    assert list(GoalKind) == [
        GoalKind.UEBERLEBEN,
        GoalKind.WACHSEN,
        GoalKind.RESSOURCE_SICHERN,
        GoalKind.GROLL_VERGELTEN,
        GoalKind.VERBUENDEN,
    ]
    # UEBERLEBEN steht zuerst: die stets erfuellbare Option "abwarten" gewinnt
    # jeden Gleichstand, also muss sich jede Handlung echt lohnen.
    assert next(iter(GoalKind)) is GoalKind.UEBERLEBEN


def test_reactive_trait_thresholds_are_gone() -> None:
    """Das alte Modell (eigene Schwelle je Reaktion) ist ersatzlos entfernt."""
    cfg = Config()
    assert not hasattr(cfg, "war_threshold")
    assert not hasattr(cfg, "expand_threshold")
    # Expansion und Krieg sind keine eigenen Systeme mehr, sondern Vollzuege.
    assert not hasattr(systems, "expansion")
    assert not hasattr(systems, "war")


def test_every_established_nation_declares_a_goal() -> None:
    """Jede Nation traegt je Tick ein Ziel (nur im Gruendungsjahr noch keines)."""
    world, _ = simulate(seed=42, years=40)
    for pol in world.polities.values():
        if pol.founded_year < world.year:
            assert pol.goal in set(GoalKind)


# === Determinismus & Gleichstands-Regel =====================================

@pytest.mark.parametrize("seed", [7, 42])
def test_determinism_of_goal_choice_and_actions(seed: int) -> None:
    """Gleicher Seed ⇒ identische Ziele und identische Handlungs-Events."""
    wa, la = simulate(seed=seed, years=120)
    wb, lb = simulate(seed=seed, years=120)
    assert {p.id: p.goal for p in wa.polities.values()} == {
        p.id: p.goal for p in wb.polities.values()
    }

    def trace(log: EventLog) -> list[object]:
        return [
            (e.id, e.kind, e.subjects, e.factors, e.causes)
            for e in log
            if e.kind in (EventKind.KRIEG, EventKind.EXPANSION)
        ]

    assert trace(la) == trace(lb)


def _one_nation_with_free_land(cfg: Config, traits: NationTraits) -> World:
    """Eine Nation, zwei gleich fruchtbare freie Nachbarfelder (Gleichstand)."""
    regions = {
        0: Region(id=0, food_capacity=10.0, nachbarn=(1, 2), owner=X),
        1: Region(id=1, food_capacity=8.0, nachbarn=(0,)),
        2: Region(id=2, food_capacity=8.0, nachbarn=(0,)),
    }
    return World(
        regions=regions,
        polities={
            X: Polity(
                id=X,
                capital=0,
                territory=(0,),
                strata=_strata(),
                traits=traits,
                # Genau der doppelte Preis ⇒ WOHLSTAND-Faktor exakt 1.0.
                stocks=Stocks(gold=2 * cfg.expand_gold_cost),
            )
        },
    )


def test_tie_between_goals_breaks_by_menu_order() -> None:
    """Gleichstand UEBERLEBEN vs. WACHSEN ⇒ das fruehere Ziel des Menues gewinnt.

    Beide Ziele werden auf exakt 1.0 gebracht: UEBERLEBEN traegt nur die
    Beharrung, WACHSEN nur den Wohlstand (alle anderen Beitraege sind 0 und
    fallen aus der Begruendung).
    """
    def quiet(status_quo: float) -> Config:
        return Config(
            goal_status_quo=status_quo,
            goal_hunger_weight=0.0,
            goal_unrest_weight=0.0,
            goal_fear_weight=0.0,
            goal_caution_weight=0.0,
        )

    traits = NationTraits()  # expansion=0, caution=0 ⇒ WACHSEN = WOHLSTAND = 1.0

    tie = quiet(1.0)
    world = _one_nation_with_free_land(tie, traits)
    log = _run_goals(world, tie)
    assert world.polities[X].goal is GoalKind.UEBERLEBEN
    assert EventKind.EXPANSION not in _kinds(log)

    # Ein Hauch weniger Beharrung kippt denselben Zustand zur Handlung.
    acts = quiet(0.999)
    world = _one_nation_with_free_land(acts, traits)
    log = _run_goals(world, acts)
    assert world.polities[X].goal is GoalKind.WACHSEN
    assert EventKind.EXPANSION in _kinds(log)


def test_tie_between_targets_breaks_by_entity_id() -> None:
    """Gleichstand zwischen zwei gleichwertigen Partnern ⇒ kleinste EntityId.

    Drei Nationen ohne Grenzen zueinander: die Werbung (VERBUENDEN) ist das
    einzige erfuellbare Ziel, und aus X' Sicht sind Y und Z ununterscheidbar.
    Nur X hat einen Diplomatie-Trait; Y und Z verharren (Gleichstand bei 0.0 geht
    an das fruehere UEBERLEBEN) und stoeren die Matrix nicht — ohne Treue-Gewicht
    erwidert auch der Umworbene die Werbung nicht sofort.
    """
    cfg = Config(goal_status_quo=0.0, goal_loyalty_weight=0.0)
    regions = {i: Region(id=i, food_capacity=10.0, owner=10 + i) for i in range(3)}
    world = World(
        regions=regions,
        polities={
            pid: Polity(
                id=pid,
                capital=pid - 10,
                territory=(pid - 10,),
                strata=_strata(),
                traits=NationTraits(diplomacy=1.0 if pid == X else 0.0),
            )
            for pid in (X, Y, Z)
        },
    )
    _run_goals(world, cfg)

    assert world.polities[X].goal is GoalKind.VERBUENDEN
    assert world.polities[Y].goal is GoalKind.UEBERLEBEN
    assert world.polities[Z].goal is GoalKind.UEBERLEBEN
    assert favor(world, X, Y) > 0.0  # der kleinere Partner wurde umworben
    assert favor(world, X, Z) == 0.0


# === Die Faktoren SIND die Begruendung ======================================

def test_decision_events_carry_their_exact_reasoning() -> None:
    """Jedes Handlungs-Event traegt eine nicht-leere, korrekte Faktorliste.

    "Korrekt" heisst hier pruefbar: kein Faktor mit Gewicht 0 (er hat das
    Ergebnis nicht beeinflusst), nur Labels aus dem zentralen Vokabular — und die
    Summe **muss** die Beharrung uebertreffen, denn die Handlung hat die stets
    erfuellbare Option UEBERLEBEN geschlagen, deren Score nie unter
    ``goal_status_quo`` liegt (alle ihre uebrigen Beitraege sind >= 0).
    """
    cfg = DEFAULT_CONFIG
    _, log = simulate(seed=42, years=200, cfg=cfg)
    vocabulary = {label.value for label in FactorLabel}
    decisions = [e for e in log if e.kind in (EventKind.KRIEG, EventKind.EXPANSION)]
    assert decisions

    for event in decisions:
        assert event.factors
        assert all(f.weight != 0.0 for f in event.factors)
        assert all(f.label in vocabulary for f in event.factors)
        assert sum(f.weight for f in event.factors) > cfg.goal_status_quo


# === Krieg aus der Ressourcenlage, nicht aus Zufall =========================

def _crowded_versus_weak_neighbor(*, roomy: bool) -> World:
    """X grenzt an das schwaechere Y, dessen Grenzfeld fruchtbarer ist als X' Land.

    ``roomy=True`` gibt X dieselbe Nachbarschaft, aber weites Land: die
    Bevoelkerung liegt weit unter der Tragfaehigkeit, es fehlt also nichts.
    """
    capital_capacity = 100.0 if roomy else 10.0
    regions = {
        0: Region(id=0, food_capacity=capital_capacity, nachbarn=(1, 2), owner=X),
        1: Region(id=1, food_capacity=10.0, nachbarn=(0, 2), owner=Y),
        2: Region(id=2, food_capacity=20.0, nachbarn=(0, 1), owner=Y),
    }
    return World(
        regions=regions,
        polities={
            # Gross, satt und voll geruestet — der einzige Mangel ist Land.
            X: Polity(
                id=X,
                capital=0,
                territory=(0,),
                strata=_strata(workers=200.0, soldiers=60.0),
                stocks=Stocks(eisen=60.0, gold=120.0),
            ),
            # Klein, unbewaffnet, unbesoldet: ein schwaches, fruchtbares Ziel.
            Y: Polity(
                id=Y,
                capital=1,
                territory=(1, 2),
                strata=_strata(workers=50.0, soldiers=10.0),
            ),
        },
    )


def test_war_arises_from_the_resource_situation() -> None:
    """Dieselbe Nachbarschaft: eng ⇒ Eroberungskrieg, weit ⇒ kein Krieg.

    Der einzige Unterschied ist die Tragfaehigkeit des eigenen Landes. Damit ist
    der Krieg **auf die Ressourcenlage zurueckgefuehrt** — Traits, Groll, Reibung
    und Furcht sind in beiden Welten identisch (und null).
    """
    cfg = DEFAULT_CONFIG

    crowded = _crowded_versus_weak_neighbor(roomy=False)
    log = _run_goals(crowded, cfg)
    assert crowded.polities[X].goal is GoalKind.RESSOURCE_SICHERN
    assert EventKind.KRIEG in _kinds(log)

    roomy = _crowded_versus_weak_neighbor(roomy=True)
    log = _run_goals(roomy, cfg)
    assert roomy.polities[X].goal is GoalKind.UEBERLEBEN
    assert EventKind.KRIEG not in _kinds(log)


def test_resource_war_names_the_scarcity_that_drove_it() -> None:
    """Die Begruendung des Krieges nennt den Mangel — und er dominiert sie."""
    world = _crowded_versus_weak_neighbor(roomy=False)
    log = _run_goals(world, DEFAULT_CONFIG)
    war = next(e for e in log if e.kind == EventKind.KRIEG)

    labels = {f.label: f.weight for f in war.factors}
    assert labels[FactorLabel.RESSOURCENDRUCK] > 0.0
    assert labels[FactorLabel.BEUTE] > 0.0  # das fruchtbare Grenzfeld lockt
    dominant = max(war.factors, key=lambda f: abs(f.weight))
    assert dominant.label == FactorLabel.RESSOURCENDRUCK


def test_the_war_decision_contains_no_chance() -> None:
    """Verschiedene Zufalls-Stroeme ⇒ identische Kriegs-Entscheidung.

    Der RNG faerbt nur den Ausgang der Schlacht (benannter Faktor "Zufall"), nie
    die Zielwahl: die Entscheidung ist eine reine Funktion der Weltlage.
    """
    decisions = []
    for seed in range(6):
        world = _crowded_versus_weak_neighbor(roomy=False)
        log = _run_goals(world, DEFAULT_CONFIG, seed=seed)
        war = next(e for e in log if e.kind == EventKind.KRIEG)
        decisions.append((war.subjects, war.factors))
    assert len(set(decisions)) == 1


def test_resource_wars_actually_occur_in_the_simulation() -> None:
    """Nicht nur konstruierbar: Ressourcenkriege treten im echten Lauf auf."""
    _, log = simulate(seed=42, years=200)
    wars = [e for e in log if e.kind == EventKind.KRIEG]
    resource_wars = [
        e for e in wars if any(f.label in RESOURCE_LABELS for f in e.factors)
    ]
    assert resource_wars
    # Und sie sind kein Randphaenomen neben den Groll-Kriegen.
    assert len(resource_wars) >= 0.05 * len(wars)
    # Jeder von ihnen nennt das erreichbare Feld: ein Krieg um Ressourcen wird nur
    # gegen ein Ziel gefuehrt, das ueberhaupt Land hergibt (Erfuellbarkeit).
    for war in resource_wars:
        assert any(f.label == FactorLabel.BEUTE for f in war.factors)


# === Das Ziel treibt die Handlung ===========================================

def test_famine_makes_a_nation_retrench_instead_of_expand() -> None:
    """Dieselbe Nation, nur hungrig: sie beansprucht kein Land mehr.

    Frueher war das eine harte Vorbedingung (``if food_deficit: continue``);
    jetzt gewinnt schlicht das dringendere Ziel.
    """
    cfg = DEFAULT_CONFIG
    traits = NationTraits(expansion=0.3)

    fed = _one_nation_with_free_land(cfg, traits)
    fed.polities[X].strata = _strata(workers=100.0)
    _run_goals(fed, cfg)
    assert fed.polities[X].goal is GoalKind.WACHSEN

    hungry = _one_nation_with_free_land(cfg, traits)
    hungry.polities[X].strata = _strata(workers=100.0)
    hungry.polities[X].food_deficit = 100.0 * cfg.food_per_person * cfg.famine_reference
    log = _run_goals(hungry, cfg)
    assert hungry.polities[X].goal is GoalKind.UEBERLEBEN
    assert EventKind.EXPANSION not in _kinds(log)


def test_survival_goal_sends_soldiers_back_to_the_fields() -> None:
    """Das erklaerte Ziel steuert die Rekrutierung (guns versus butter)."""
    cfg = DEFAULT_CONFIG

    def soldiers_after_a_year(goal: GoalKind | None) -> float:
        world = _one_nation_with_free_land(cfg, NationTraits())
        pol = world.polities[X]
        pol.strata = _strata(workers=90.0, soldiers=10.0)
        pol.goal = goal
        demografie(world, Rng(0).stream("demografie:0"), cfg, EventLog())
        return next(s.size for s in pol.strata if s.kind == StratumKind.SOLDAT)

    assert soldiers_after_a_year(GoalKind.UEBERLEBEN) < soldiers_after_a_year(None)
