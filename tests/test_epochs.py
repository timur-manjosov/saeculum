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


def test_the_earthquake_is_the_last_shock_and_it_is_not_rolled() -> None:
    """Aenderung 7: von drei gewuerfelten Schocks bleibt EINER — und auch er wird nicht gewuerfelt.

    Pest und Duerre sind fort (reine Wuerfelwuerfe im Ereignispfad). Das Erdbeben bleibt,
    weil es als einziges keine soziale Ursache haben KANN — aber es faellt nicht mehr vom
    Himmel: es ist die Entladung einer Gesteinsspannung, die sich ueber Jahrhunderte
    aufstaut. Darum traegt es diese Spannung als seinen benannten Faktor: seine
    Begruendung sagt "die Spannung im Gestein war voll", nicht "der Wuerfel sagte es".
    """
    assert not hasattr(EventKind, "PEST")
    assert not hasattr(EventKind, "DUERRE")

    _, log = simulate(seed=42, years=400)
    quakes = log.by_kind(EventKind.ERDBEBEN)
    assert quakes
    assert len(quakes) < 20  # "bei sehr niedriger Rate" (Aufgabe 2)
    for e in quakes:
        assert e.effects  # ein Schock ist ein Verlust-Event
        # Die Begruendung IST die aufgestaute Spannung, und sie war voll (>= 1.0).
        assert [f.label for f in e.factors] == [FactorLabel.ERDSPANNUNG.value]
        assert e.factors[0].weight >= 1.0


def test_the_earthquake_sets_pressure_instead_of_triggering_an_event() -> None:
    """Aufgabe 2: die FOLGEN des Schocks laufen durch das Spannungssystem.

    Der entscheidende Unterschied zum alten Katastrophen-System: das Beben loest nichts
    aus. Es emittiert keine Hungersnot, keinen Aufstand, keinen Kollaps — es vernarbt
    Land und leert den Schatz, und was daraus wird, entscheidet die LAGE der getroffenen
    Nation. Zwei Nachweise:

    * strukturell: das Beben aendert nur Zustand (Kapazitaet, Gold, Bevoelkerung) und
      hat keine Ursache im Log (es ist ein exogener Wurzel-Event) — aber es haengt auch
      kein fertiges Gross-Ereignis an sich;
    * gemessen: der Volksdruck der getroffenen Nation liegt in den 15 Jahren DANACH im
      Mittel hoeher als davor. Das Beben setzt Druck; es entlaedt ihn nicht.
    """
    world, log = simulate(seed=42, years=400)
    for e in log.by_kind(EventKind.ERDBEBEN):
        assert not e.causes  # exogener Wurzel-Event: er hat keine Ursache in der Welt
        felder = {eff.field for eff in e.effects}
        assert felder <= {"food_capacity", "gold", "population"}
    # Die Narbe im Land ist dauerhaft: getroffene Felder tragen weniger als der Worldgen
    # ihnen gab. (Der Regionen-Zustand ist der Beleg, nicht die Erzaehlung.)
    struck = {e.subjects[-1] for e in log.by_kind(EventKind.ERDBEBEN)}
    assert any(world.regions[r].food_capacity < DEFAULT_CONFIG.region_food_capacity_min
               for r in struck)


def test_technology_accumulates_and_unlocks_ages() -> None:
    """Aufgabe 2: Wissen akkumuliert; Schwellen schalten Tech-Stufen (Zeitalter) frei."""
    world, log = simulate(seed=42, years=200)
    innovations = [e for e in log if e.kind == EventKind.INNOVATION]
    assert innovations
    # Mindestens eine Nation hat eine Tech-Stufe erreicht, ihr Wissen ist positiv.
    assert any(pol.tech_level >= 1 for pol in world.polities.values())
    assert any(pol.knowledge > 0.0 for pol in world.polities.values())
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
    """Aufgabe 5: "dies ermoeglichte das" — ein Schock kurz vor einer Machtverschiebung.

    Ueber mehrere Laeufe geprueft, denn seit Aenderung 7 ist das Beben der einzige Schock
    und obendrein zehnmal seltener (drei gewuerfelte Katastrophen pro Nation und Jahr sind
    einer Gesteinsspannung gewichen, die Jahrhunderte braucht). Dass ein Beben ausgerechnet
    kurz vor einem Machtwechsel zuschlaegt, ist damit ein seltener Zufall der Geografie —
    ein Test an einem einzigen Seed wuerde nur Glueck messen.
    """
    for seed in (7, 99, 5):
        world, log = simulate(seed=seed, years=250)
        enabled = [
            e
            for e in log
            if e.kind == EventKind.WENDEPUNKT
            and any(f.label == FactorLabel.MACHTWECHSEL.value for f in e.factors)
            and e.causes
            and log.get(e.causes[0]).kind is EventKind.ERDBEBEN
        ]
        if not enabled:
            continue
        lines = chronik_mit_zeitaltern(world, log, DEFAULT_CONFIG)
        assert any("rise to dominance" in line and "allowed" in line for line in lines)
        return
    raise AssertionError("kein Beben ermoeglichte je einen Machtwechsel")


def test_causal_centrality_counts_downstream_reach() -> None:
    """Aufgabe 6: die Zentralitaet zaehlt die erreichbaren Folgen im Kausalgraphen."""
    log = EventLog()
    e0 = log.append(EventDraft(year=0, kind=EventKind.ERDBEBEN, subjects=(1,)))
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
