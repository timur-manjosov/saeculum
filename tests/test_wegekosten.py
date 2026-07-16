"""Wegekosten: wird das Terrain wirklich zu Barriere und Korridor? (Schritt 3)

Die Behauptung dieses Schritts ist nicht "Kanten haben jetzt Zahlen", sondern:
**Reiche werden durch Gebirge und Wasser begrenzt, Handel und Expansion folgen Taelern,
Fluessen und Kuesten** — und zwar ohne jede Sonderregel, allein weil die bestehenden
Systeme Kosten gegen Ertrag abwaegen und endlich die richtigen Kosten bekommen.

Das ist eine messbare Aussage, also wird sie hier als **Verteilung ueber viele Seeds** in
der LAUFENDEN Simulation geprueft, nicht an einer gebauten Welt: eine gebaute Welt beweist
nur, dass der Hebel greift, den sie selbst hingestellt hat (vgl. ``test_tension``).

Der Angelpunkt ist der Bezugspunkt **1.0 = offene Ebene**. Er wird hier zuerst gepinnt,
denn an ihm haengt alles andere: eine Welt aus lauter 1.0-Kanten verhaelt sich exakt wie
vor Schritt 3, und darum bleiben die gebauten Welten aller anderen Tests gueltig.
"""

from __future__ import annotations

import numpy as np
import pytest
from worldsim.config import DEFAULT_CONFIG, DEFAULT_MAP_CONFIG, Config
from worldsim.driver import simulate
from worldsim.events import EventKind, FactorLabel
from worldsim.geo.climate import Biome
from worldsim.geo.derive import (
    _cell_fertility,
    _cell_travel_cost,
    _place_centers,
    _touches,
    _voronoi,
    derive_regions,
)
from worldsim.geo.hydrology import build_hydrology
from worldsim.geo.terrain import MAP_HEIGHT, MAP_WIDTH, PEAK_RELIEF
from worldsim.models import Polity, Region, World
from worldsim.systems import _border_cost, _trade_distances, wegekosten

SEEDS = range(6)
YEARS = 200

# Eine neutrale Geografie: jede Kante kostet 1.0. Das IST die Welt vor Schritt 3.
FLAT = Config(
    terrain_cost_mountain=0.0,
    terrain_cost_water=1.0,
    terrain_cost_desert=1.0,
    terrain_river_bonus=1.0,
    terrain_coast_bonus=1.0,
)


# === Der Bezugspunkt: 1.0 ist die offene Ebene ==============================

def test_a_world_without_costs_is_the_world_before_this_change() -> None:
    """Fehlt der Eintrag, gilt die offene Ebene (1.0) — der Vertrag mit allen Alt-Tests.

    Jede gebaute Testwelt im Projekt setzt ``nachbarn``, aber keine ``wegekosten``. Sie
    darf sich durch Schritt 3 um kein Jota anders verhalten, sonst waeren die Aussagen
    aller anderen Tests stillschweigend verschoben.
    """
    world = World(regions={0: Region(id=0, nachbarn=(1,)), 1: Region(id=1, nachbarn=(0,))})
    assert wegekosten(world, 0, 1) == 1.0
    assert wegekosten(world, 1, 0) == 1.0


def test_the_cost_budget_reproduces_the_old_hop_distance() -> None:
    """Auf lauter 1.0-Kanten IST das Kosten-Budget die alte Sprungzahl.

    Der Handel zaehlte frueher Spruenge (``trade_max_distance``); jetzt summiert er
    Wegekosten (``trade_max_cost``). Beides muss auf der uniformen Welt dasselbe sein —
    die Sprung-Distanz ist der Sonderfall "jede Kante kostet gleich".
    """
    # Kette X — Y — Z: Y liegt eine Kante weg, Z zwei.
    x, y, z = 10, 11, 12
    world = World(
        regions={
            0: Region(id=0, nachbarn=(1,), owner=x),
            1: Region(id=1, nachbarn=(0, 2), owner=y),
            2: Region(id=2, nachbarn=(1,), owner=z),
        },
        polities={
            x: Polity(id=x, territory=(0,)),
            y: Polity(id=y, territory=(1,)),
            z: Polity(id=z, territory=(2,)),
        },
    )
    pids = [x, y, z]
    near = _trade_distances(world, pids, Config(trade_max_cost=1.0))
    assert near[(x, y)] == 1.0
    assert (x, z) not in near  # zwei Kanten: ausser Budget, wie bei max_distance=1

    far = _trade_distances(world, pids, Config(trade_max_cost=2.0))
    assert far[(x, y)] == 1.0
    assert far[(x, z)] == 2.0  # transitiert ueber Y, wie bei max_distance=2


def test_flat_terrain_leaves_no_trace_in_the_reasoning() -> None:
    """Auf der Ebene traegt ``Wegekosten`` exakt 0 — und faellt aus der Begruendung.

    ``Decision.add`` verwirft ein Gewicht von 0 (es hat nichts entschieden, also darf es
    nicht in der Begruendung stehen). Steht der Faktor an einem Event, hat die Geografie
    wirklich mitgeredet; steht er nicht da, war das Gelaende gleichgueltig.
    """
    _world, log = simulate(seed=3, years=YEARS, cfg=FLAT)
    events = [e for e in log if e.kind in (EventKind.KRIEG, EventKind.EXPANSION)]
    assert events  # der Test darf nicht leer durchlaufen
    assert not [
        e for e in events
        for f in e.factors
        if f.label == FactorLabel.WEGEKOSTEN.value
    ]


# === Die Kosten kommen aus dem Terrain =====================================

@pytest.mark.parametrize("seed", [0, 7, 42])
def test_edge_costs_are_a_pure_symmetric_function_of_the_seed(seed: int) -> None:
    """Gleiche Eingabe ⇒ gleiche Kanten; und die Naht ist von beiden Seiten dieselbe."""
    a = derive_regions(seed, DEFAULT_CONFIG)
    b = derive_regions(seed, DEFAULT_CONFIG)
    assert a.edge_cost == b.edge_cost

    for r, neighbours in enumerate(a.adjacency):
        assert len(a.edge_cost[r]) == len(neighbours)  # index-gleich zur Adjazenz
        for i, nb in enumerate(neighbours):
            back = a.adjacency[nb].index(r)
            assert a.edge_cost[nb][back] == pytest.approx(a.edge_cost[r][i])


def test_barriers_are_dear_and_corridors_are_cheap() -> None:
    """Die fuenf Terrain-Faktoren schlagen im Zell-Preis durch — ueber viele Seeds.

    Der Ankerpunkt ist die Ebene bei 1.0; alles andere wird gegen SIE gemessen. Die
    Doppelrolle des Wassers ist die Pointe: dieselbe See ist am Ufer der billigste Weg
    der Welt und drei Zellen weiter draussen die teuerste Wand.
    """
    medians: dict[str, list[float]] = {}
    for seed in SEEDS:
        hydro = build_hydrology(seed, MAP_WIDTH, MAP_HEIGHT, DEFAULT_MAP_CONFIG)
        terrain = hydro.terrain
        is_land = np.asarray(terrain.elevation) >= terrain.sea_level
        cost = _cell_travel_cost(hydro, is_land, DEFAULT_CONFIG)
        sea = ~is_land
        shelf = _touches(is_land) & sea
        masks = {
            "ebene": is_land
            & (np.asarray(terrain.relief) < 0.08)
            & ~np.asarray(hydro.river)
            & (hydro.climate.biome != Biome.WUESTE),
            "gebirge": is_land & (np.asarray(terrain.relief) >= PEAK_RELIEF),
            "wueste": hydro.climate.biome == Biome.WUESTE,
            "offene_see": sea & ~shelf,
            "fluss": np.asarray(hydro.river),
            "schelf": shelf,
        }
        for name, mask in masks.items():
            if mask.any():
                medians.setdefault(name, []).append(float(np.median(cost[mask])))

    med = {name: float(np.median(vals)) for name, vals in medians.items()}
    assert med["ebene"] == pytest.approx(1.0)  # der Bezugspunkt
    # Barrieren: teurer als die Ebene.
    assert med["gebirge"] > 1.5
    assert med["wueste"] > 1.5
    assert med["offene_see"] > med["gebirge"]  # die groesste Barriere ueberhaupt
    # Korridore: billiger als die Ebene.
    assert med["fluss"] < 0.8
    assert med["schelf"] < 0.8
    # Und die Doppelrolle des Wassers: dieselbe See, zwei Preise, Faktor > 5.
    assert med["offene_see"] / med["schelf"] > 5.0


# === Die Zusage: Reiche wachsen durch Korridore und stocken an Barrieren ====

def test_realms_grow_through_the_cheap_land_and_stop_at_the_barriers() -> None:
    """DIE Zusage von Schritt 3, gemessen in der gewachsenen Welt.

    Die Kontrolle ist der Punkt. "Grenzen sind gebirgig" allein sagt nichts — die Karte
    ist voller Gebirge. Verglichen werden darum zwei Kantenmengen DESSELBEN Reichs, also
    zwei Entscheidungen, die es wirklich gegenueberstehen hatte:

      GENOMMEN = Kanten in Land, das es besitzt
      GELASSEN = Kanten in Land, das bis zuletzt FREI blieb (es haette gekonnt)

    Liegt das Genommene hinter billigeren Kanten als das Gelassene, dann hat die Geografie
    die Grenze gezogen — und zwar ohne dass eine Zeile sie dorthin legt.
    """
    taken: list[float] = []
    left: list[float] = []
    for seed in SEEDS:
        world, _log = simulate(seed=seed, years=YEARS, cfg=DEFAULT_CONFIG)
        for pol in world.polities.values():
            territory = set(pol.territory)
            if len(territory) < 2:
                continue  # ein Reich, das nie wuchs, hat nichts gewaehlt
            for rid in sorted(territory):
                for nb in world.regions[rid].nachbarn:
                    cost = wegekosten(world, rid, nb)
                    if nb in territory:
                        taken.append(cost)
                    elif world.regions[nb].owner is None:
                        left.append(cost)

    assert len(taken) >= 50 and len(left) >= 10  # genug, um von Verteilungen zu reden
    # Das genommene Land liegt hinter KORRIDOREN, das gelassene hinter WAENDEN.
    assert float(np.median(taken)) < 1.0
    assert float(np.median(left)) > 2.0
    assert float(np.mean(taken)) < 0.6 * float(np.mean(left))


def test_the_terrain_toll_selects_corridors_for_war() -> None:
    """Ein Angriff ueber eine Barriere ist teurer — also finden die Kriege die Korridore.

    Gepinnt wird die AUSWAHL, nicht eine Daempfung: die Kriege, die stattfinden, tragen
    ueberwiegend einen positiven Aufschlag (sie liefen einen Korridor entlang). Waere das
    Gelaende bloss eine pauschale Strafe auf jeden Krieg, laege der Schnitt negativ.
    """
    tolls: list[float] = []
    for seed in SEEDS:
        _world, log = simulate(seed=seed, years=YEARS, cfg=DEFAULT_CONFIG)
        for e in log:
            if e.kind is not EventKind.KRIEG:
                continue
            tolls.append(
                next(
                    (f.weight for f in e.factors if f.label == FactorLabel.WEGEKOSTEN.value),
                    0.0,
                )
            )
    assert len(tolls) >= 50
    arr = np.array(tolls)
    assert arr.mean() > 0.0  # die Kriege, die bleiben, sind die durch die Korridore
    assert (arr > 0.0).mean() > 0.5  # und zwar die Mehrheit
    assert (arr < 0.0).any()  # aber die Barriere ist ein Preis, kein Verbot


def test_landlocked_nations_are_more_isolated_than_port_nations() -> None:
    """Binnenlaender sind isolierter als Kuestennationen (Aufgabe 3).

    "Binnenland" wird auf der KARTE gemessen (keine einzige Kuestenzelle), die Isolation
    im VERHALTEN (aufgebaute Handelsabhaengigkeit) — sonst waere die Aussage eine
    Tautologie ueber den Kantenpreis. Nur die echte Landsperre zaehlt: der Anteil der
    Kuestenzellen einer Nation misst nicht ihren Hafen, sondern ihre Insel-artigkeit
    (85 % Kueste heisst "Fleck im Meer"), und die haengt an der Kontinentgroesse.
    """
    landlocked: list[float] = []
    with_port: list[float] = []
    for seed in range(12):  # mehr Seeds: echtes Binnenland ist selten (~6 % der Nationen)
        world, _log = simulate(seed=seed, years=YEARS, cfg=DEFAULT_CONFIG)
        hydro = build_hydrology(seed, MAP_WIDTH, MAP_HEIGHT, DEFAULT_MAP_CONFIG)
        terrain = hydro.terrain
        is_land = np.asarray(terrain.elevation) >= terrain.sea_level
        coast = _touches(~is_land) & is_land
        # Dieselbe Zerlegung, auf der die Simulation laeuft (und die die Karte zeichnet).
        fertility = _cell_fertility(hydro, is_land, DEFAULT_CONFIG)
        centers = _place_centers(is_land, fertility, DEFAULT_CONFIG.num_regions)
        region_of = _voronoi(centers, MAP_WIDTH, MAP_HEIGHT)

        for pid, pol in world.polities.items():
            if not pol.territory:
                continue
            cells = np.isin(region_of, list(pol.territory))
            has_port = bool((coast & cells).any())
            dep = sum(r.dependency for (a, _b), r in world.relations.items() if a == pid)
            (with_port if has_port else landlocked).append(dep)

    assert landlocked and with_port  # beide Arten kommen vor
    assert float(np.mean(landlocked)) < float(np.mean(with_port))


# === Die Barriere ist ein Preis, kein Verbot ===============================

def test_a_barrier_is_a_price_not_a_law() -> None:
    """Dieselbe Welt, teureres Gelaende ⇒ weniger Uebertritte, aber nie null.

    Der Unterschied zwischen "stoppe am Berg" (eine Regel) und "der Berg kostet" (ein
    Preis): dreht man die Kosten hoch, geht die Zahl der teuren Uebertritte zurueck — sie
    faellt aber nicht auf einen Schlag auf null, denn ein Reich mit genug Not oder
    Expansionsdrang bezahlt.
    """
    def dear_crossings(cfg: Config) -> int:
        n = 0
        for seed in SEEDS:
            world, _log = simulate(seed=seed, years=YEARS, cfg=cfg)
            for pol in world.polities.values():
                territory = set(pol.territory)
                for rid in sorted(territory):
                    for nb in world.regions[rid].nachbarn:
                        if nb in territory and wegekosten(world, rid, nb) > 1.5:
                            n += 1
        return n

    lax = dear_crossings(Config(expand_terrain_weight=0.0, war_terrain_weight=0.0))
    strict = dear_crossings(DEFAULT_CONFIG)
    assert strict < lax  # der Preis wirkt ...
    assert strict > 0  # ... aber er verbietet nichts


def test_border_cost_is_the_cheapest_seam_between_two_realms() -> None:
    """Das Heer marschiert durch den Pass: es zaehlt die BILLIGSTE gemeinsame Naht."""
    x, y = 10, 11
    world = World(
        regions={
            0: Region(id=0, nachbarn=(2, 3), wegekosten={2: 4.0, 3: 0.5}, owner=x),
            1: Region(id=1, nachbarn=(), owner=x),
            2: Region(id=2, nachbarn=(0,), wegekosten={0: 4.0}, owner=y),
            3: Region(id=3, nachbarn=(0,), wegekosten={0: 0.5}, owner=y),
        },
        polities={x: Polity(id=x, territory=(0, 1)), y: Polity(id=y, territory=(2, 3))},
    )
    assert _border_cost(world, x, y) == 0.5  # nicht 4.0, nicht der Schnitt
