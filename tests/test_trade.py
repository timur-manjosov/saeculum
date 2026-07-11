"""Aenderung 5: Handel und Abhaengigkeit — Krieg aus Handelsverflechtung.

Ressourcen fliessen zwischen benachbarten Nationen (Ueberschuss -> Defizit) entlang
der Beziehungskanten; aus anhaltender Lieferung waechst ``Relation.dependency``, und
eine gefaehrliche Abhaengigkeit (von einem feindlichen/instabilen Lieferanten) speist
als benannter Faktor das Ziel RESSOURCE_SICHERN (Aenderung 4). Diese Tests sichern die
Zusagen der Aufgabe: Determinismus, **Erhaltung** der Gesamtressourcen (keine Erzeugung
aus dem Nichts), dass die dependency die Fluesse spiegelt, und dass der Utility-Faktor
bei Abhaengigkeit auftaucht — bis hin dazu, dass er eine Kriegsentscheidung **kippen**
kann (das Kappen einer Abhaengigkeit kann Krieg ausloesen).
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from worldsim.chronicle import erzaehle
from worldsim.config import DEFAULT_CONFIG, Config
from worldsim.driver import simulate
from worldsim.events import EventKind, EventLog, FactorLabel
from worldsim.models import (
    GoalKind,
    NationTraits,
    Polity,
    Region,
    Relation,
    Stocks,
    Stratum,
    StratumKind,
    World,
)
from worldsim.rng import Rng
from worldsim.systems import (
    add_favor,
    dependency,
    goals,
    production,
    trade,
)

# Feste Ziel-Ids der synthetischen Welten (Regionen 0..n, Nationen ab 10).
W, X, Y, Z = 13, 10, 11, 12
RES = ("getreide", "eisen", "gold")


def _strata(
    workers: float = 0.0, soldiers: float = 0.0, grievance: float = 0.0
) -> tuple[Stratum, ...]:
    return (
        Stratum(StratumKind.ARBEITER, size=workers, grievance=grievance),
        Stratum(StratumKind.SOLDAT, size=soldiers, grievance=grievance),
        Stratum(StratumKind.ELITE, size=0.0),
    )


def _run_trade(world: World, cfg: Config, seed: int = 0) -> None:
    """Fuehre isoliert nur das ``trade``-System aus (kein RNG im Handel)."""
    trade(world, Rng(seed).stream("trade:0"), cfg, EventLog())


def _run_goals(world: World, cfg: Config, seed: int = 0) -> EventLog:
    log = EventLog()
    goals(world, Rng(seed).stream("goals:0"), cfg, log)
    return log


def _sustain_trade(world: World, cfg: Config, years: int, *, drain: int = Y) -> None:
    """Handel ueber Jahre, wobei ``drain`` sein Eisen jaehrlich verbraucht.

    Modelliert den stehenden Bedarf (Soldaten zehren Eisen): ohne Verbrauch fuellte
    sich der Bestand des Importeurs und die Lieferung — und damit die Abhaengigkeit —
    versiegte von selbst. Genau diesen Verbrauch leisten im echten Lauf Krieg/Zerfall.
    """
    for _ in range(years):
        pol = world.polities[drain]
        pol.stocks = replace(pol.stocks, eisen=0.0)
        _run_trade(world, cfg)


def _totals(world: World) -> dict[str, float]:
    return {r: sum(getattr(p.stocks, r) for p in world.polities.values()) for r in RES}


# === Fluesse: Umverteilung entlang der Grenzen, Erhaltung der Summen ==========

def _row_world() -> World:
    """Drei Nationen in einer Kette (X-Y-Z) mit gemischten Ueberschuessen/Defiziten."""
    regions = {
        0: Region(id=0, food_capacity=10.0, iron_rich=True, nachbarn=(1,), owner=X),
        1: Region(id=1, food_capacity=10.0, iron_rich=False, nachbarn=(0, 2), owner=Y),
        2: Region(id=2, food_capacity=10.0, iron_rich=True, nachbarn=(1,), owner=Z),
    }
    return World(
        regions=regions,
        polities={
            # X: satt und reich an Eisen/Gold, kaum Soldaten (grosser Ueberschuss).
            X: Polity(id=X, capital=0, territory=(0,), strata=_strata(workers=100.0),
                      stocks=Stocks(getreide=60.0, eisen=40.0, gold=60.0)),
            # Y: stark militarisiert, alles knapp (Defizit in allen drei).
            Y: Polity(id=Y, capital=1, territory=(1,), strata=_strata(workers=40.0, soldiers=60.0),
                      stocks=Stocks(getreide=0.0, eisen=0.0, gold=0.0)),
            # Z: Getreide-arm, aber Eisen-/Gold-reich.
            Z: Polity(id=Z, capital=2, territory=(2,), strata=_strata(workers=20.0, soldiers=10.0),
                      stocks=Stocks(getreide=0.0, eisen=30.0, gold=200.0)),
        },
    )


def test_trade_conserves_total_resources() -> None:
    """Fluesse sind reine Umverteilung: je Ressource bleibt die Weltsumme erhalten."""
    cfg = DEFAULT_CONFIG
    world = _row_world()
    before = _totals(world)
    _run_trade(world, cfg)
    after = _totals(world)
    for r in RES:
        assert after[r] == pytest.approx(before[r], abs=1e-9)
    # Und nichts wird negativ (keine Nation gibt unter null ab).
    for p in world.polities.values():
        assert p.stocks.getreide >= 0.0
        assert p.stocks.eisen >= 0.0
        assert p.stocks.gold >= 0.0


def test_trade_actually_moved_something() -> None:
    """Erhaltung waere trivial ohne Fluesse — hier fliesst nachweislich etwas."""
    cfg = DEFAULT_CONFIG
    world = _row_world()
    grain_y_before = world.polities[Y].stocks.getreide
    iron_y_before = world.polities[Y].stocks.eisen
    _run_trade(world, cfg)
    # Y hatte in allem ein Defizit und bekam von seinen Nachbarn geliefert.
    assert world.polities[Y].stocks.getreide > grain_y_before
    assert world.polities[Y].stocks.eisen > iron_y_before


def _star_world(*, hostile_z: bool) -> World:
    """X (Getreide-Ueberschuss) grenzt an Y und Z; W liegt ausser Reichweite."""
    regions = {
        0: Region(id=0, food_capacity=10.0, nachbarn=(1, 2), owner=X),
        1: Region(id=1, food_capacity=10.0, nachbarn=(0,), owner=Y),
        2: Region(id=2, food_capacity=10.0, nachbarn=(0,), owner=Z),
        3: Region(id=3, food_capacity=10.0, nachbarn=(), owner=W),
    }
    world = World(
        regions=regions,
        polities={
            X: Polity(id=X, capital=0, territory=(0,), strata=_strata(workers=100.0),
                      stocks=Stocks(getreide=60.0)),
            Y: Polity(id=Y, capital=1, territory=(1,), strata=_strata(workers=100.0)),
            Z: Polity(id=Z, capital=2, territory=(2,), strata=_strata(workers=100.0)),
            W: Polity(id=W, capital=3, territory=(3,), strata=_strata(workers=100.0)),
        },
    )
    if hostile_z:
        add_favor(world, X, Z, -0.4)
        add_favor(world, Z, X, -0.4)
    return world


def test_trade_needs_a_friendly_open_border() -> None:
    """Handel folgt der Adjazenz und meidet offene Feinde.

    X hat Getreide-Ueberschuss; Y (Nachbar, neutral) wird beliefert, Z (Nachbar,
    verfeindet) nicht, W (ausser Reichweite bei ``trade_max_distance=1``) nicht.
    """
    cfg = Config(trade_max_distance=1)
    world = _star_world(hostile_z=True)
    _run_trade(world, cfg)
    assert world.polities[Y].stocks.getreide > 0.0  # neutraler Nachbar: beliefert
    assert world.polities[Z].stocks.getreide == 0.0  # verfeindet: kein Handel
    assert world.polities[W].stocks.getreide == 0.0  # ausser Reichweite: kein Handel


def test_trade_prefers_the_friendlier_partner() -> None:
    """Bei gleichem Bedarf bekommt der wohlgesonnenere Partner mehr (favor-Praeferenz)."""
    cfg = DEFAULT_CONFIG
    world = _star_world(hostile_z=False)
    add_favor(world, X, Y, 0.5)  # Y ist X wohlgesonnen, Z ist neutral
    _run_trade(world, cfg)
    # Y und Z starteten beide bei 0 Getreide mit identischem Defizit.
    assert world.polities[Y].stocks.getreide > world.polities[Z].stocks.getreide > 0.0


# === Determinismus ===========================================================

@pytest.mark.parametrize("seed", [7, 42])
def test_determinism_of_trade_and_dependency(seed: int) -> None:
    """Gleicher Seed ⇒ identische Bestaende und identische dependency-Matrix."""
    wa, _ = simulate(seed=seed, years=150)
    wb, _ = simulate(seed=seed, years=150)
    assert {p.id: p.stocks for p in wa.polities.values()} == {
        p.id: p.stocks for p in wb.polities.values()
    }
    assert wa.relations == wb.relations


def test_trade_is_insertion_order_independent() -> None:
    """Determinismus-Vertrag: das Ergebnis haengt nicht an der Reihenfolge der Kanten."""
    cfg = DEFAULT_CONFIG

    def build() -> World:
        return _row_world()

    forward = build()
    backward = build()
    # dieselbe Welt, aber die favor-Kanten in verschiedener Reihenfolge einhaengen
    for a, b, v in [(X, Y, 0.3), (Y, X, 0.2), (Y, Z, 0.1), (Z, Y, 0.4)]:
        add_favor(forward, a, b, v)
    for a, b, v in [(Z, Y, 0.4), (Y, Z, 0.1), (Y, X, 0.2), (X, Y, 0.3)]:
        add_favor(backward, a, b, v)
    _run_trade(forward, cfg)
    _run_trade(backward, cfg)
    assert {p.id: p.stocks for p in forward.polities.values()} == {
        p.id: p.stocks for p in backward.polities.values()
    }
    assert forward.relations == backward.relations


# === dependency spiegelt die Fluesse =========================================

def _supplier_world() -> World:
    """Y (soldatenstark, eisenlos) grenzt an X (eisenreich); Z importiert nichts."""
    regions = {
        0: Region(id=0, food_capacity=10.0, iron_rich=True, nachbarn=(1,), owner=X),
        1: Region(id=1, food_capacity=10.0, iron_rich=False, nachbarn=(0,), owner=Y),
        2: Region(id=2, food_capacity=10.0, iron_rich=True, nachbarn=(), owner=Z),
    }
    return World(
        regions=regions,
        polities={
            X: Polity(id=X, capital=0, territory=(0,), strata=_strata(workers=100.0),
                      stocks=Stocks(getreide=80.0, eisen=2000.0, gold=200.0)),
            # Y braucht viel Eisen (Soldaten) und foerdert selbst keines.
            Y: Polity(id=Y, capital=1, territory=(1,), strata=_strata(workers=40.0, soldiers=60.0),
                      stocks=Stocks(getreide=80.0, eisen=0.0, gold=400.0)),
            Z: Polity(id=Z, capital=2, territory=(2,), strata=_strata(workers=100.0),
                      stocks=Stocks(getreide=80.0, eisen=50.0, gold=200.0)),
        },
    )


def test_dependency_reflects_the_flows() -> None:
    """Anhaltende Lieferung baut dependency auf; wer nichts importiert, bleibt bei 0."""
    cfg = DEFAULT_CONFIG
    world = _supplier_world()
    # Ein Jahr: schon eine erste, kleine Abhaengigkeit.
    _run_trade(world, cfg)
    after_one = dependency(world, Y, X)
    assert after_one > 0.0
    # Viele Jahre anhaltender Lieferung (Eisen wird verbraucht): sie waechst und saettigt.
    _sustain_trade(world, cfg, 30)
    grown = dependency(world, Y, X)
    assert grown > after_one
    assert 0.0 < grown <= 1.0
    # Z (isoliert, kein Import) traegt keine Abhaengigkeit.
    assert dependency(world, Z, X) == 0.0
    # Die Abhaengigkeit ist gerichtet: X haengt nicht an seinem Kunden Y.
    assert dependency(world, X, Y) == 0.0


def test_dependency_decays_when_the_supply_is_cut() -> None:
    """Das Kappen der Lieferung laesst die Abhaengigkeit ueber Jahre zerfallen (und entfallen)."""
    cfg = DEFAULT_CONFIG
    world = _supplier_world()
    _sustain_trade(world, cfg, 30)
    built = dependency(world, Y, X)
    assert built > 0.1

    # Kappen: X und Y verfeinden sich ⇒ kein Handel mehr.
    add_favor(world, Y, X, -1.0)
    add_favor(world, X, Y, -1.0)
    prev = built
    for _ in range(80):
        _run_trade(world, cfg)
        cur = dependency(world, Y, X)
        assert cur <= prev  # monoton fallend ohne Nachschub
        prev = cur
    assert dependency(world, Y, X) == 0.0  # verblasst und aus der Matrix entfernt


# === Eisen-Geografie: die Wurzel der Abhaengigkeit ===========================

def test_iron_is_geographic_not_universal() -> None:
    """Eisen ist "oft nicht lokal": manche Regionen tragen es, andere nicht."""
    world, _ = simulate(seed=42, years=0)
    rich = [r for r in world.regions.values() if r.iron_rich]
    assert 0 < len(rich) < len(world.regions)


def test_iron_production_requires_a_deposit() -> None:
    """Ohne Eisenvorkommen foerdert eine Region kein Eisen (Grundlage der Handelsnot)."""
    cfg = DEFAULT_CONFIG

    def eisen_after(iron_rich: bool) -> float:
        regions = {0: Region(id=0, food_capacity=10.0, iron_rich=iron_rich, owner=X)}
        world = World(
            regions=regions,
            polities={X: Polity(id=X, capital=0, territory=(0,), strata=_strata(workers=50.0))},
        )
        production(world, Rng(0).stream("production:0"), cfg, EventLog())
        return world.polities[X].stocks.eisen

    assert eisen_after(iron_rich=False) == 0.0
    assert eisen_after(iron_rich=True) > 0.0


# === Der Utility-Faktor: Abhaengigkeit traegt (und kippt) die Kriegswahl ======

def _dependent_on_unstable_supplier(dep: float) -> World:
    """X (satt, weites Land, geruestet) grenzt an Y (gleich stark, aber instabil).

    Bewusst so gebaut, dass X **ohne** Abhaengigkeit keinen Kriegsgrund hat: kein
    Landdruck, kein Hunger, kein Eisenmangel, favor neutral (kein Groll), gleiche
    Macht (keine Schwaeche, kein Vorteil). Der EINZIGE moegliche Antrieb ist die
    Abhaengigkeit von Y — und Y ist ein riskanter Lieferant (innerlich zerruettet:
    hoher Volksgroll). ``dep`` setzt die Abhaengigkeit direkt auf die Kante.
    """
    regions = {
        # X: eine weite, sichere Hauptstadt (Bevoelkerung weit unter Tragfaehigkeit).
        0: Region(id=0, food_capacity=100.0, nachbarn=(1, 2), owner=X),
        1: Region(id=1, food_capacity=10.0, nachbarn=(0, 2), owner=Y),  # Y-Hauptstadt
        2: Region(id=2, food_capacity=20.0, nachbarn=(0, 1), owner=Y),  # erreichbares Feld
    }
    world = World(
        regions=regions,
        polities={
            X: Polity(id=X, capital=0, territory=(0,), traits=NationTraits(),
                      strata=_strata(workers=200.0, soldiers=20.0),
                      stocks=Stocks(getreide=200.0, eisen=20.0, gold=40.0)),
            # Y: gleich stark (20 Soldaten, gleich geruestet) — aber innerlich instabil.
            Y: Polity(id=Y, capital=1, territory=(1, 2), traits=NationTraits(),
                      strata=_strata(workers=200.0, soldiers=20.0, grievance=8.0),
                      stocks=Stocks(getreide=200.0, eisen=20.0, gold=40.0)),
        },
    )
    if dep > 0.0:
        world.relations[(X, Y)] = Relation(dependency=dep)
    return world


def test_dependency_carries_the_reasoning_of_the_trade_war() -> None:
    """Der Handelskrieg nennt seine Abhaengigkeit — als benannten, positiven Faktor."""
    cfg = DEFAULT_CONFIG
    world = _dependent_on_unstable_supplier(dep=0.85)
    log = _run_goals(world, cfg)
    assert world.polities[X].goal is GoalKind.RESSOURCE_SICHERN
    war = next(e for e in log if e.kind == EventKind.KRIEG)
    assert war.subjects[:2] == (X, Y)  # der Krieg richtet sich gegen den Lieferanten
    labels = {f.label: f.weight for f in war.factors}
    assert labels[FactorLabel.HANDELSABHAENGIGKEIT] > 0.0
    # Nur Labels aus dem zentralen Vokabular, kein Null-Faktor (Aenderung-4-Vertrag).
    vocabulary = {label.value for label in FactorLabel}
    assert all(f.weight != 0.0 for f in war.factors)
    assert all(f.label in vocabulary for f in war.factors)


def test_cutting_a_dependency_can_trigger_a_war() -> None:
    """Dieselbe Lage, nur die Abhaengigkeit unterscheidet sich: sie **kippt** die Wahl.

    Ohne Abhaengigkeit hat X keinen Grund, den ebenbuertigen Nachbarn anzugreifen —
    es verharrt (UEBERLEBEN). Mit der Abhaengigkeit von genau diesem instabilen
    Lieferanten waehlt X den Krieg, um die Quelle zu sichern. Damit ist der Krieg
    **auf die Handelsverflechtung zurueckgefuehrt** — alles andere ist identisch.
    """
    cfg = DEFAULT_CONFIG

    calm = _dependent_on_unstable_supplier(dep=0.0)
    log_calm = _run_goals(calm, cfg)
    assert calm.polities[X].goal is GoalKind.UEBERLEBEN
    assert EventKind.KRIEG not in [e.kind for e in log_calm]

    entangled = _dependent_on_unstable_supplier(dep=0.85)
    log_war = _run_goals(entangled, cfg)
    assert entangled.polities[X].goal is GoalKind.RESSOURCE_SICHERN
    assert EventKind.KRIEG in [e.kind for e in log_war]


def test_the_chronicle_names_a_trade_war() -> None:
    """Am Chronik-Text: ein von Handelsabhaengigkeit getriebener Krieg heisst 'trade war'."""
    cfg = DEFAULT_CONFIG
    world = _dependent_on_unstable_supplier(dep=0.85)
    log = _run_goals(world, cfg)
    war = next(e for e in log if e.kind == EventKind.KRIEG)
    assert "trade war" in erzaehle(world, log, war)


# === Krieg aus Handelsverflechtung entsteht im echten Lauf ===================

def test_trade_dependency_wars_emerge_in_the_simulation() -> None:
    """Nicht nur konstruierbar: Handelsabhaengigkeit traegt Kriege im echten Lauf.

    Handelsnetze entstehen (dependency-Kanten fuellen sich), und mancher Krieg
    fuehrt die Abhaengigkeit als echten, spuerbaren Faktor — kein Rauschen.
    """
    world, log = simulate(seed=7, years=250)
    # Handelsnetze: die dependency-Matrix ist gefuellt.
    assert any(rel.dependency > 0.0 for rel in world.relations.values())

    wars = [e for e in log if e.kind == EventKind.KRIEG]
    dep_wars = [
        e for e in wars if any(f.label == FactorLabel.HANDELSABHAENGIGKEIT for f in e.factors)
    ]
    assert dep_wars  # Krieg aus Handelsverflechtung tritt auf
    # Und wenigstens einer traegt die Abhaengigkeit als gewichtigen Mit-Antrieb.
    strongest = max(
        f.weight
        for e in dep_wars
        for f in e.factors
        if f.label == FactorLabel.HANDELSABHAENGIGKEIT
    )
    assert strongest > 0.2
