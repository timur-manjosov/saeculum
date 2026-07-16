"""Aenderung 6: der Spannungszustand und seine Entladung.

Innere Umbrueche (Aufstand, Putsch, Buergerkrieg, Abspaltung, Kollaps) entstehen aus
akkumuliertem Druck, der sich an Schwellen entlaedt — nicht aus Zufalls-Triggern. Die
Spannung ist eine Summe VIER benannter Druecke (Volk/Elite/Fiskus/Aussen); die
dominante Komponente waehlt die Art der Entladung; jede Entladung ENTLASTET ihren
eigenen Druck und saet einen anderen, damit das System durch die Krisentypen rotiert
statt in einen Fixpunkt zu laufen.

Diese Tests sichern die Zusagen der Aufgabe: Determinismus, dass die Spannung die
korrekte Faktorsumme IST, und dass eine Entladung ihre dominante Komponente
nachweisbar senkt — plus die Abschluss-Signatur: endogene Krisen, Zyklen statt flacher
Linie, keine sofortige Explosion.
"""

from __future__ import annotations

from dataclasses import replace
from statistics import median

import pytest
from worldsim.chronicle import erzaehle
from worldsim.config import DEFAULT_CONFIG, Config
from worldsim.driver import SYSTEMS, simulate, worldgen
from worldsim.events import Decision, Event, EventKind, EventLog, FactorLabel
from worldsim.models import (
    AccessionMode,
    NationTraits,
    Polity,
    Region,
    Stocks,
    Stratum,
    StratumKind,
    Tension,
    World,
)
from worldsim.rng import Rng
from worldsim.systems import (
    _aussendruck,
    _dominant,
    _elitendruck,
    _fiskaldruck,
    _tension_parts,
    _tension_total,
    _volksgroll,
    bevoelkerung,
    consumption,
    spannung,
    tension,
)

DISCHARGES = (
    EventKind.AUFSTAND,
    EventKind.PUTSCH,
    EventKind.BANKROTT,
    EventKind.KOLLAPS,
)
# Feste Ids der synthetischen Welten: Regionen 0..k, Nation ab 10.
X = 10


def _strata(
    workers: float = 300.0,
    soldiers: float = 40.0,
    elite: float = 60.0,
    grievance: float = 0.0,
    elite_wealth: float = 0.5,
) -> tuple[Stratum, ...]:
    """Kanonische Schichtung (Reihenfolge Arbeiter/Soldat/Elite ist bindend)."""
    lower = 1.0 - elite_wealth
    return (
        Stratum(StratumKind.ARBEITER, size=workers, grievance=grievance,
                wealth_share=lower * 0.7),
        Stratum(StratumKind.SOLDAT, size=soldiers, grievance=grievance,
                wealth_share=lower * 0.3),
        Stratum(StratumKind.ELITE, size=elite, wealth_share=elite_wealth),
    )


def _world(regions: int = 3) -> World:
    """Eine Ein-Nations-Welt mit ``regions`` Feldern (alle benachbart, alle in Besitz)."""
    regs = {
        i: Region(
            id=i,
            food_capacity=15.0,
            nachbarn=tuple(j for j in range(regions) if j != i),
            owner=X,
        )
        for i in range(regions)
    }
    pol = Polity(
        id=X,
        name="Testland",
        capital=0,
        territory=tuple(range(regions)),
        strata=_strata(),
        stocks=Stocks(getreide=50.0, eisen=50.0, gold=200.0),
        traits=NationTraits(),
    )
    return World(year=50, regions=regs, polities={X: pol})


def _elite_crisis(regions: int) -> World:
    """Eine Welt, in der der ELITENDRUCK dominiert — und nur er.

    Weit mehr Anwaerter als Aemter (``elite_posts_per_region``), aber ein PRALLER
    Schatz: sonst risse die leere Kasse den Fiskaldruck mit hoch und der wuerde die
    Dominanz an sich reissen (eine Elite ohne Gold ist eben AUCH eine Finanzkrise).
    """
    cfg = DEFAULT_CONFIG
    world = _world(regions)
    posts = regions * cfg.elite_posts_per_region
    world.polities[X].strata = _strata(elite=4.0 * posts, grievance=1.0)
    world.polities[X].stocks = Stocks(getreide=50.0, eisen=50.0, gold=60_000.0)
    return world


def _run_tension(world: World, cfg: Config, seed: int = 0) -> EventLog:
    """Fuehre isoliert nur das ``tension``-System aus."""
    log = EventLog()
    tension(world, Rng(seed).stream("tension:0"), cfg, log)
    return log


def _pressures(world: World, cfg: Config) -> tuple[float, float, float, float]:
    """Die vier ROHdruecke (0..1) einer Ein-Nations-Welt."""
    pol = world.polities[X]
    return (
        _volksgroll(pol, cfg),
        _elitendruck(world, pol, cfg),
        _fiskaldruck(world, pol, cfg),
        _aussendruck(world, pol, cfg),
    )


# === 1. Die Spannung IST die Summe benannter Faktoren =======================


def test_spannung_is_exactly_the_weighted_sum_of_the_four_pressures() -> None:
    """Jeder Faktor ist Gewicht x Rohdruck, und der Score ist ihre Summe.

    Das Kernprinzip: die Faktoren SIND die Rechnung — keine zweite, danebenstehende
    Erklaerung. Also muss die Faktorliste Zahl fuer Zahl reproduzierbar sein.
    """
    cfg = DEFAULT_CONFIG
    world = _world()
    world.polities[X].strata = _strata(grievance=3.0)
    world.polities[X].food_deficit = 4.0

    # Auch eine fiskalisch geklemmte Nation pruefen, damit ALLE vier Faktoren
    # wenigstens einmal mit ihrem Gewicht nachgerechnet werden.
    stressed = _world(regions=1)
    stressed.polities[X].strata = _strata(soldiers=2000.0, grievance=3.0)
    stressed.polities[X].stocks = Stocks(gold=0.0)
    stressed.polities[X].food_deficit = 10.0

    for probe in (world, stressed):
        pol = probe.polities[X]
        decision = spannung(probe, pol, cfg, EventLog())
        weights = {f.label: f.weight for f in decision.factors}
        volk, elite, fiskal, aussen = _pressures(probe, cfg)
        expected = {
            FactorLabel.VOLKSDRUCK: cfg.tension_volk_weight * volk,
            FactorLabel.ELITENDRUCK: cfg.tension_elite_weight * elite,
            FactorLabel.FISKALDRUCK: cfg.tension_fiskal_weight * fiskal,
            FactorLabel.AUSSENDRUCK: cfg.tension_aussen_weight * aussen,
        }
        for label, value in expected.items():
            # Ein Druck von 0 faellt aus der Begruendung (er hat nichts erklaert, §2).
            assert (label in weights) == (value != 0.0)
            if value != 0.0:
                assert weights[label] == pytest.approx(value)
        # Der Score IST die Summe der Faktoren — keine zweite Rechnung.
        assert decision.score == pytest.approx(sum(expected.values()))


def test_a_pressure_of_zero_is_absent_from_the_reasoning() -> None:
    """Ein Faktor, der nichts beitrug, darf nicht in der Begruendung stehen (§2)."""
    world = _world()  # kein Groll, kein Defizit, reicher Schatz, keine Nachbarn
    decision = spannung(world, world.polities[X], DEFAULT_CONFIG, EventLog())
    assert not any(f.label == FactorLabel.AUSSENDRUCK for f in decision.factors)
    assert all(f.weight != 0.0 for f in decision.factors)


def test_tension_is_stored_on_the_nation_as_pure_data() -> None:
    """Die vier Gewichte landen als reine Daten auf der Nation (fuer Zielwahl/Ansicht)."""
    cfg = DEFAULT_CONFIG
    world = _world()
    world.polities[X].strata = _strata(grievance=2.0)
    _run_tension(world, cfg)
    t = world.polities[X].tension
    decision = spannung(world, world.polities[X], cfg, EventLog())
    assert _tension_total(t) == pytest.approx(decision.score)


# === 2. Keine Entladung unter der Schwelle ==================================


def test_no_discharge_below_the_threshold() -> None:
    """Unter der Schwelle baut sich Druck nur AUF — nichts bricht."""
    world = _world()
    world.polities[X].strata = _strata(grievance=1.0)
    log = _run_tension(world, DEFAULT_CONFIG)
    assert _tension_total(world.polities[X].tension) < DEFAULT_CONFIG.tension_threshold
    assert [e for e in log] == []


def test_pressure_builds_for_decades_before_the_first_crisis() -> None:
    """Keine sofortige Explosion: die Welt laeuft erst jahrzehntelang ruhig."""
    _, log = simulate(seed=7, years=400)
    first = min(e.year for e in log if e.kind in DISCHARGES)
    assert first > 20


# === 3. Die dominante Komponente waehlt die Art =============================


def test_volksdruck_dominant_yields_an_uprising() -> None:
    """Volksdruck dominiert ⇒ AUFSTAND."""
    world = _world()
    world.polities[X].strata = _strata(grievance=DEFAULT_CONFIG.grievance_cap)
    log = _run_tension(world, DEFAULT_CONFIG)
    assert _dominant(world.polities[X].tension) == FactorLabel.VOLKSDRUCK
    assert [e.kind for e in log] == [EventKind.AUFSTAND]


def test_elitendruck_dominant_splits_a_divisible_realm() -> None:
    """Elitendruck dominiert und das Reich ist teilbar ⇒ ABSPALTUNG (die Elite geht)."""
    cfg = DEFAULT_CONFIG
    world = _elite_crisis(regions=4)
    log = _run_tension(world, cfg)
    assert _dominant(world.polities[X].tension) == FactorLabel.ELITENDRUCK
    assert [e.kind for e in log] == [EventKind.ABSPALTUNG]
    assert len(world.polities) == 2  # die Nation hat sich geteilt


def test_elitendruck_dominant_in_an_indivisible_realm_yields_a_coup() -> None:
    """Elitendruck dominiert, aber das Reich ist unteilbar ⇒ PUTSCH."""
    cfg = DEFAULT_CONFIG
    world = _elite_crisis(regions=1)  # unter collapse_min_territory ⇒ unteilbar
    log = _run_tension(world, cfg)
    assert _dominant(world.polities[X].tension) == FactorLabel.ELITENDRUCK
    assert [e.kind for e in log] == [EventKind.PUTSCH]
    assert len(world.polities) == 1  # nichts gespalten — die Elite frass sich selbst


def test_fiskaldruck_dominant_yields_bankruptcy() -> None:
    """Fiskaldruck dominiert ⇒ BANKROTT."""
    cfg = DEFAULT_CONFIG
    world = _world(regions=1)
    # Riesiges Heer, leere Kasse, Hungersnot: die Pflichten sprengen die Mittel.
    world.polities[X].strata = _strata(workers=100.0, soldiers=3000.0, elite=1.0)
    world.polities[X].stocks = Stocks(getreide=0.0, eisen=0.0, gold=0.0)
    world.polities[X].food_deficit = 30.0
    log = _run_tension(world, cfg)
    assert _dominant(world.polities[X].tension) == FactorLabel.FISKALDRUCK
    assert [e.kind for e in log] == [EventKind.BANKROTT]


def test_composite_extreme_crisis_yields_collapse_into_successor_states() -> None:
    """Mehrere Druecke zugleich, extrem hoch ⇒ KOLLAPS in Nachfolgestaaten.

    Ein EINZELNER Druck, so hoch er auch steht, entlaedt sich in seiner eigenen Art;
    erst wenn das Reich an mehreren Fronten zugleich reisst, faellt es auseinander.
    """
    cfg = DEFAULT_CONFIG
    world = _world(regions=4)
    world.polities[X].strata = _strata(
        workers=200.0, soldiers=800.0, elite=3000.0, grievance=cfg.grievance_cap
    )
    world.polities[X].stocks = Stocks(getreide=0.0, eisen=0.0, gold=0.0)
    world.polities[X].food_deficit = 20.0

    log = _run_tension(world, cfg)
    assert [e.kind for e in log] == [EventKind.KOLLAPS]
    kollaps = log.get(0)
    successors = kollaps.subjects[1:]
    assert successors  # es gibt Nachfolgestaaten
    assert len(world.polities) == 1 + len(successors)
    for pid in successors:
        assert world.polities[pid].territory  # jeder Nachfolger haelt Land


# === 4. Jede Entladung ENTLASTET ihren eigenen Druck ========================


def _relief_case(kind: EventKind) -> tuple[World, Config, str]:
    """Baue eine Welt, die sich als ``kind`` entlaedt; gib sie mit ihrem Druck-Feld."""
    cfg = DEFAULT_CONFIG
    if kind is EventKind.AUFSTAND:
        world = _world()
        world.polities[X].strata = _strata(grievance=cfg.grievance_cap)
        return world, cfg, "volk"
    if kind is EventKind.PUTSCH:
        return _elite_crisis(regions=1), cfg, "elite"
    if kind is EventKind.ABSPALTUNG:
        return _elite_crisis(regions=4), cfg, "elite"
    # BANKROTT: ein bankrotter Staat sieht so aus, wie ihn die Simulation wirklich
    # hervorbringt — die Rechnung traegt der HOF (hier ~53%) und die Nothilfe (~39%),
    # der Sold ist der kleinste Posten (~8%). Diese Mischung ist gemessen, nicht
    # geraten, und sie ist der Kern der Probe: eine Testwelt aus lauter Soldaten
    # bestuende sie auch dann, wenn die Entladung am falschen Hebel zieht.
    world = _world(regions=2)
    world.polities[X].strata = _strata(workers=600.0, soldiers=40.0, elite=300.0)
    world.polities[X].stocks = Stocks(gold=0.0)
    world.polities[X].food_deficit = 5.0
    return world, cfg, "fiskal"


@pytest.mark.parametrize(
    "kind",
    [EventKind.AUFSTAND, EventKind.PUTSCH, EventKind.ABSPALTUNG, EventKind.BANKROTT],
)
def test_a_discharge_lowers_its_own_dominant_pressure(kind: EventKind) -> None:
    """DIE Kernzusage (Aufgabe 3): jede Entladung entlastet ihren eigenen Druck.

    Ohne sie liefe das System in einen Fixpunkt — der Druck bliebe stehen und die
    Nation braeche jedes Jahr aufs Neue. Erst die Entlastung macht aus dem Aufbau
    einen ZYKLUS.
    """
    world, cfg, field = _relief_case(kind)
    before = spannung(world, world.polities[X], cfg, EventLog())
    log = _run_tension(world, cfg)
    assert [e.kind for e in log] == [kind]

    after = spannung(world, world.polities[X], cfg, EventLog())
    dominant = _dominant(_as_tension(before, cfg))
    assert dominant == {
        "volk": FactorLabel.VOLKSDRUCK,
        "elite": FactorLabel.ELITENDRUCK,
        "fiskal": FactorLabel.FISKALDRUCK,
    }[field]
    assert _weight(after, dominant) < _weight(before, dominant)


def _tension_history(
    seed: int, years: int, cfg: Config
) -> tuple[dict[tuple[int, int], Tension], EventLog]:
    """Fahre den echten Tick-Loop und halte die Spannung JEDER Nation in JEDEM Jahr fest."""
    master = Rng(seed)
    log = EventLog()
    world = worldgen(master, cfg)
    track: dict[tuple[int, int], Tension] = {}
    for year in range(years):
        world = replace(world, year=year)
        for sid, system in SYSTEMS:
            world = system(world, master.stream(f"{sid}:{year}"), cfg, log)
        for pid, pol in world.polities.items():
            track[(pid, year)] = pol.tension
    return track, log


def test_every_discharge_relieves_its_own_pressure_in_the_full_simulation() -> None:
    """Dieselbe Zusage wie oben — aber in der GEWACHSENEN Welt. Das ist der Test, der zaehlt.

    Eine gebaute Welt beweist nur, dass der Hebel greift, den sie selbst hingestellt hat.
    Der Bankrott bestand die gebaute Probe und entlastete in der laufenden Simulation
    trotzdem so gut wie nichts: dort besteht die Rechnung des Staates zur Haelfte aus dem
    HOF und nur zu einem Zwoelftel aus dem Sold — eine Entladung, die bloss Soldaten
    entliess, senkte sie um wenige Prozent. Was in gebauten Welten stimmt, muss in
    gewachsenen erst gelten.

    Gemessen wird darum als Verteilung, nicht als Einzelfall: die Entlastung ist eine
    KRAFT, keine Garantie. Sie wirkt gegen eine Welt, die weiterlaeuft — im Jahr des
    Bankrotts kann eine frische Hungersnot die Nothilfe (und damit die Pflichten) schneller
    heben, als die Entlassungen sie senken. Verlangt ist beides: ein spuerbar negativer
    Median UND eine klare Mehrheit, denn eine Muenze waere bei der Haelfte.
    """
    cfg = DEFAULT_CONFIG
    relief: dict[EventKind, list[float]] = {}
    for seed in (42, 7, 1234, 99):
        track, log = _tension_history(seed, years=400, cfg=cfg)
        for e in log:
            if e.kind not in DISCHARGES or not e.subjects:
                continue
            pid = e.subjects[0]
            before, after = track.get((pid, e.year)), track.get((pid, e.year + 1))
            if before is None or after is None:
                continue  # die Nation ueberlebte ihr eigenes Krisenjahr nicht
            dominant = _dominant(before)
            relief.setdefault(e.kind, []).append(
                _tension_parts(after)[dominant] - _tension_parts(before)[dominant]
            )

    for kind in (EventKind.AUFSTAND, EventKind.PUTSCH, EventKind.BANKROTT):
        deltas = relief[kind]
        assert len(deltas) >= 20  # genug Faelle, um von einer Verteilung zu reden
        assert median(deltas) < -0.2  # sie nimmt IHREN Druck, und zwar spuerbar
        assert sum(d < 0.0 for d in deltas) / len(deltas) > 0.6  # und nicht bloss zufaellig


def _weight(decision: Decision, label: str) -> float:
    return next((f.weight for f in decision.factors if f.label == label), 0.0)


def _as_tension(decision: Decision, cfg: Config) -> Tension:
    return Tension(
        volk=_weight(decision, FactorLabel.VOLKSDRUCK),
        elite=_weight(decision, FactorLabel.ELITENDRUCK),
        fiskal=_weight(decision, FactorLabel.FISKALDRUCK),
        aussen=_weight(decision, FactorLabel.AUSSENDRUCK),
    )


def test_the_uprising_redistributes_wealth_and_plunders_the_treasury() -> None:
    """Der Aufstand entlaedt den Groll UND senkt die Ungleichheit, die ihn naehrt.

    Die Umverteilung ist die zweite, laenger wirkende Haelfte der Entlastung: sie
    daempft die Quelle des Grolls, nicht nur seinen Stand. Und sie hat ihren Preis —
    der gepluenderte Schatz saet den naechsten (fiskalischen) Druck.
    """
    cfg = DEFAULT_CONFIG
    world = _world()
    world.polities[X].strata = _strata(grievance=cfg.grievance_cap)
    pol = world.polities[X]
    elite_wealth_before = next(s.wealth_share for s in pol.strata if s.kind == StratumKind.ELITE)
    gold_before = pol.stocks.gold

    _run_tension(world, cfg)

    elite_wealth_after = next(s.wealth_share for s in pol.strata if s.kind == StratumKind.ELITE)
    assert elite_wealth_after < elite_wealth_before  # umverteilt
    assert pol.stocks.gold < gold_before  # Schatz gepluendert ⇒ Fiskaldruck
    assert sum(s.wealth_share for s in pol.strata) == pytest.approx(1.0)  # Invariante
    assert all(s.grievance < cfg.grievance_cap for s in pol.strata)


def test_the_coup_purges_the_elite_and_installs_a_usurper() -> None:
    """Der Putsch purgiert die Elite (Entlastung) und setzt einen Usurpator ein.

    Der Usurpator traegt schwache Legitimitaet — daran kann die bestehende
    Sukzessionskrise das Reich spalten (der Buergerkrieg des Konzepts, ohne eine
    Zeile neuer Mechanik).
    """
    cfg = DEFAULT_CONFIG
    world = _elite_crisis(regions=1)
    ruler = _install_ruler(world, cfg)

    elite_before = next(s.size for s in world.polities[X].strata if s.kind == StratumKind.ELITE)
    log = _run_tension(world, cfg)

    elite_after = next(s.size for s in world.polities[X].strata if s.kind == StratumKind.ELITE)
    assert elite_after < elite_before
    assert not world.rulers[ruler].alive  # der Herrscher wurde gestuerzt
    kinds = [e.kind for e in log]
    assert kinds[0] == EventKind.PUTSCH
    assert EventKind.TOD_FIGUR in kinds and EventKind.SUKZESSION in kinds
    assert world.polities[X].leader != ruler


def test_the_bankruptcy_disbands_the_army_and_levies_the_people() -> None:
    """Der Bankrott senkt die Pflichten (Entlastung) und hebt den Volksgroll (Saat)."""
    cfg = DEFAULT_CONFIG
    world = _world(regions=1)
    world.polities[X].strata = _strata(workers=100.0, soldiers=3000.0, elite=1.0, grievance=1.0)
    world.polities[X].stocks = Stocks(gold=0.0)
    world.polities[X].food_deficit = 30.0
    pol = world.polities[X]
    pop_before = bevoelkerung(pol)
    soldiers_before = next(s.size for s in pol.strata if s.kind == StratumKind.SOLDAT)
    groll_before = _volksgroll(pol, cfg)

    _run_tension(world, cfg)

    soldiers_after = next(s.size for s in pol.strata if s.kind == StratumKind.SOLDAT)
    assert soldiers_after < soldiers_before  # entlassen
    assert bevoelkerung(pol) == pop_before  # sie sterben nicht, sie werden Arbeiter
    assert _volksgroll(pol, cfg) > groll_before  # Zwangsabgaben ⇒ Volksdruck


def _install_ruler(world: World, cfg: Config) -> int:
    from worldsim.systems import forge_ruler

    ruler = forge_ruler(
        900, Rng(1).stream("r"), cfg, mode=AccessionMode.INHERITED, name="Testrex"
    )
    world.rulers[ruler.id] = ruler
    world.polities[X].leader = ruler.id
    world.next_id = 901
    return ruler.id


# === 5. Die Sperre macht aus dem Auf und Ab einen Zyklus ====================


def test_a_shaken_society_is_refractory_for_years() -> None:
    """Nach einer Entladung bricht dieselbe Nation nicht schon im naechsten Jahr erneut."""
    cfg = DEFAULT_CONFIG
    world = _world()
    world.polities[X].strata = _strata(grievance=cfg.grievance_cap)
    assert [e.kind for e in _run_tension(world, cfg)] == [EventKind.AUFSTAND]

    # Druck sofort wieder auf Anschlag — die Sperre haelt trotzdem.
    world.polities[X].strata = _strata(grievance=cfg.grievance_cap)
    world = replace(world, year=world.year + 1)
    assert [e for e in _run_tension(world, cfg)] == []

    # Nach Ablauf der Sperre bricht es erneut.
    world = replace(world, year=world.year + cfg.crisis_cooldown_years)
    assert [e.kind for e in _run_tension(world, cfg)] == [EventKind.AUFSTAND]


# === 6. Der Aussendruck entlaedt sich nach AUSSEN (Krieg) ===================


def test_outward_pressure_does_not_break_the_nation_inwardly() -> None:
    """Aussendruck dominiert ⇒ KEINE innere Entladung; der Krieg ist sein Ventil.

    Es gibt nur EINEN Kriegspfad in der Simulation: die Spannung liefert das Motiv als
    benannten Faktor, die Zielwahl (Aenderung 4) waehlt das Ziel und vollzieht ihn.
    """
    cfg = DEFAULT_CONFIG
    world = _world()
    pol = world.polities[X]
    # Aussendruck kuenstlich dominant setzen (die Lage selbst hat keine Nachbarn).
    pol.tension = Tension(volk=0.4, aussen=cfg.tension_threshold)
    log = EventLog()
    # tension() rechnet die Spannung neu — darum direkt die Entladung pruefen:
    from worldsim.systems import _entlade

    _entlade(world, pol, spannung(world, pol, cfg, log), Rng(0).stream("t"), cfg, log)
    assert [e for e in log] == []  # nichts brach nach innen
    assert pol.last_crisis == -10_000  # und die Sperre blieb unverbraucht


def _pressure_wars(log: EventLog) -> list[Event]:
    """Alle Kriege, die den Aussendruck als benannten Antrieb tragen."""
    return [
        e
        for e in log.by_kind(EventKind.KRIEG)
        if any(f.label == FactorLabel.AUSSENDRUCK for f in e.factors)
    ]


def test_a_crisis_of_outward_pressure_drives_a_war_in_the_full_simulation() -> None:
    """Im echten Lauf traegt mancher KRIEG den Aussendruck als benannten Antrieb.

    Damit ist die Entladung des Aussendrucks nachweisbar der Krieg — und der Kausalgraph
    sagt es selbst, ohne dass jemand es nachtraeglich behauptet.

    Geprueft ueber MEHRERE Laeufe, denn dieser Krieg ist selten: er braucht mehr als ein
    Motiv. Er braucht ein erreichbares Ziel, das kein Verbuendeter ist, ein Heer, das
    nicht eben erst gekaempft hat (Kriegsmuedigkeit — sie deckt die meisten Krisenjahre
    ab, gerade WEIL die Nation sich schon entladen hat), und eine Nation, die nicht
    verhungert (die zieht sich zurueck, Aenderung 4). Wo der Krieg unmoeglich ist, wirbt
    die eingekreiste Nation um Verbuendete — auch das nimmt ihr Druck. Ein Test an einem
    einzigen Seed wuerde hier nur Glueck messen.
    """
    for seed in (5, 11, 99):
        world, log = simulate(seed=seed, years=150)
        wars = _pressure_wars(log)
        if not wars:
            continue
        assert max(
            f.weight for e in wars for f in e.factors if f.label == FactorLabel.AUSSENDRUCK
        ) > 0.5
        assert "mounting crisis" in erzaehle(world, log, wars[0])
        return
    raise AssertionError("kein einziger Krieg trug den Aussendruck als Antrieb")


def test_the_war_relieves_the_outward_pressure_that_drove_it() -> None:
    """Konzept §3.3, nun fuer die Entladung nach AUSSEN: auch der Krieg entlastet SEINEN Druck.

    Das ist nicht selbstverstaendlich, sondern der Punkt: der Angriff macht Feinde (favor
    bricht ein), er koennte die Einkreisung also gerade VERSCHAERFEN. Er tut es nicht —
    das eroberte Land bricht die riskante Abhaengigkeit, und die wiegt schwerer. Ohne
    diesen Nachweis waere der Aussendruck der eine Druck, der nur steigen kann.

    Wie bei den inneren Entladungen (siehe ``test_every_discharge_relieves...``) ist die
    Entlastung eine KRAFT, keine Garantie: seit die Nachbarschaft geografisch ist (Schritt
    2), traegt mancher Aussendruck-Krieg die EINKREISUNG als Motiv, und ein einziger
    eroberter Nachbar loest sie nicht immer binnen zwanzig Jahren. Verlangt ist darum das
    Verteilungsbild — ein spuerbar negativer Median UND eine klare Mehrheit —, nicht der
    Einzelfall. (Gemessen: ueber die Aussendruck-Kriege mehrerer Laeufe entlasten rund 70 %.)
    """
    cfg = DEFAULT_CONFIG
    deltas: list[float] = []
    for seed in (5, 13, 17, 24, 25, 38):
        master = Rng(seed)
        log = EventLog()
        world = worldgen(master, cfg)
        track: dict[tuple[int, int], float] = {}
        for year in range(300):
            world = replace(world, year=year)
            for sid, system in SYSTEMS:
                world = system(world, master.stream(f"{sid}:{year}"), cfg, log)
            for pid, pol in world.polities.items():
                track[(pid, year)] = pol.tension.aussen
        for war in _pressure_wars(log):
            attacker = war.subjects[0]
            after = [
                track[(attacker, y)]
                for y in range(war.year + 1, war.year + 21)
                if (attacker, y) in track
            ]
            if len(after) < 20:  # der Angreifer ueberlebte die Frist nicht
                continue
            deltas.append(sum(after) / len(after) - track[(attacker, war.year)])

    assert len(deltas) > 20  # genug Aussendruck-Kriege fuer eine Verteilung
    assert sum(d < 0 for d in deltas) / len(deltas) > 0.6  # die klare Mehrheit entlastet
    assert sorted(deltas)[len(deltas) // 2] < 0  # ... und der Median ist spuerbar negativ


# === 7. Der Kriegsgewinner-Adel: der Sieg saet die naechste Krise ===========


def test_a_won_war_promotes_war_winners_into_the_elite() -> None:
    """Konzept §3.3: der Sieg schafft Gewinner-Eliten, die als naechstes ueberproduzieren.

    Das ist der einzige Kanal, der den Elite-Anteil HEBT (alle uebrigen senken ihn) —
    ohne ihn bliebe er auf ewig bei seinem Anfangswert und der Elitendruck eine flache
    Linie.
    """
    world, _ = simulate(seed=7, years=300)
    shares = {
        pid: next(s.size for s in p.strata if s.kind == StratumKind.ELITE) / bevoelkerung(p)
        for pid, p in world.polities.items()
        if bevoelkerung(p) > 0
    }
    start = DEFAULT_CONFIG.initial_elite_fraction
    assert any(v > start + 0.02 for v in shares.values())  # irgendwo wuchs der Adel
    assert len(set(round(v, 4) for v in shares.values())) > 1  # er ist nicht konstant


# === 8. Der Staat zahlt: Gold ist ein Bestand MIT Abfluss ===================


def test_the_treasury_pays_its_obligations_and_can_run_dry() -> None:
    """``consumption`` zahlt Sold, Hof und Nothilfe — sonst waere der Fiskaldruck tot."""
    cfg = DEFAULT_CONFIG
    world = _world(regions=1)
    world.polities[X].stocks = Stocks(getreide=1000.0, gold=100.0)
    before = world.polities[X].stocks.gold
    consumption(world, Rng(0).stream("c"), cfg, EventLog())
    assert world.polities[X].stocks.gold < before  # der Staat hat gezahlt

    poor = _world(regions=1)
    poor.polities[X].strata = _strata(soldiers=5000.0)
    poor.polities[X].stocks = Stocks(getreide=1000.0, gold=5.0)
    consumption(poor, Rng(0).stream("c"), cfg, EventLog())
    assert poor.polities[X].stocks.gold == 0.0  # er kann nicht mehr zahlen, als er hat
    assert _fiskaldruck(poor, poor.polities[X], cfg) > 0.0


# === 9. Determinismus ======================================================


@pytest.mark.parametrize("seed", [7, 42])
def test_determinism_of_tension_and_discharges(seed: int) -> None:
    """Gleicher Seed ⇒ identische Spannung UND identische Entladungen (inkl. EventIds)."""
    wa, la = simulate(seed=seed, years=200)
    wb, lb = simulate(seed=seed, years=200)
    assert {pid: p.tension for pid, p in wa.polities.items()} == {
        pid: p.tension for pid, p in wb.polities.items()
    }
    trace_a = [(e.id, e.kind, e.year, e.subjects, e.factors) for e in la if e.kind in DISCHARGES]
    trace_b = [(e.id, e.kind, e.year, e.subjects, e.factors) for e in lb if e.kind in DISCHARGES]
    assert trace_a == trace_b
    assert trace_a  # der Test darf nicht leer bestehen


def test_discharges_do_not_depend_on_dict_insertion_order() -> None:
    """Der Entscheidungspfad iteriert stabil sortiert — nie ueber Einfuegereihenfolge."""
    cfg = DEFAULT_CONFIG
    forward = _elite_crisis(regions=4)
    # Dieselbe Welt, aber die Regionen in umgekehrter Einfuegereihenfolge.
    reversed_world = _elite_crisis(regions=4)
    reversed_world.regions = dict(reversed(list(reversed_world.regions.items())))

    a = [(e.kind, e.subjects, e.factors) for e in _run_tension(forward, cfg)]
    b = [(e.kind, e.subjects, e.factors) for e in _run_tension(reversed_world, cfg)]
    assert a == b


# === 10. Die Abschluss-Signatur: endogene Krisen, Zyklen, kein Fixpunkt =====


def test_internal_crises_arise_endogenously_in_the_full_simulation() -> None:
    """Alle Arten der Entladung entstehen im Lauf — aus Druck, nicht aus Zufall."""
    kinds = set()
    for seed in (7, 8, 9):
        _, log = simulate(seed=seed, years=400)
        kinds |= {e.kind for e in log if e.kind in DISCHARGES}
    assert kinds == set(DISCHARGES)  # Aufstand, Putsch, Bankrott UND Kollaps


def test_famine_breeds_uprisings() -> None:
    """Die erste Schleife des Konzepts (§4): Getreidemangel ⇒ Volksgroll ⇒ Aufstand.

    Der alte Hebel dieses Tests ist mit Aenderung 7 fort (die Ernteschwankung wurde
    gewuerfelt, also musste sie weg). An seine Stelle treten zwei Nachweise, und der
    zweite ist der eigentliche:

    * **im Kausalgraphen**: der Volksdruck zitiert die Hungersnoete, die ihn naehrten
      (``_TENSION_CAUSE``), und ein Aufstand traegt die Faktorliste des Volksdrucks. Ein
      grosser Teil der Aufstaende nennt seinen Hunger also beim Namen.
    * **kontrafaktisch**: nimmt man den Hunger als Groll-Treiber heraus, brechen deutlich
      weniger Aufstaende aus. Er TRAEGT sie, er begleitet sie nicht nur — und das ist die
      Zusage, die zaehlt, denn der Groll hat einen zweiten Treiber (die Ungleichheit),
      hinter dem sich ein toter Hunger-Kanal bequem verstecken koennte. Genau das war er
      nach dem Wegfall der Ernteschwankung eine Zeitlang: die Rate musste an das neue,
      chronisch-flache Hunger-Signal angepasst werden (siehe ``grievance_hunger_rate``).
    """
    named = total = 0
    for seed in (7, 42, 1234):
        _, log = simulate(seed=seed, years=250)
        for e in log.by_kind(EventKind.AUFSTAND):
            total += 1
            if any(log.get(c).kind is EventKind.HUNGERSNOT for c in e.causes):
                named += 1
    satt = sum(
        len(simulate(seed=s, years=250, cfg=Config(grievance_hunger_rate=0.0))[1]
            .by_kind(EventKind.AUFSTAND))
        for s in (7, 42, 1234)
    )
    assert total >= 20
    assert named / total > 0.3  # ein grosser Teil nennt seinen Hunger als Ursache
    assert total > satt * 1.3  # und ohne den Hunger-Treiber bricht deutlich weniger aus


def test_the_tension_of_a_nation_cycles_it_neither_flatlines_nor_explodes() -> None:
    """Die Ziel-Signatur (Konzept §3.4): Aufbau, Krise, Entlastung — ein ZYKLUS.

    Geprueft an der Spannungs-Bahn einer langlebigen Nation:
      * keine flache Linie — die Bahn hat echte Spannweite,
      * keine sofortige Explosion — sie steht die meiste Zeit UNTER der Schwelle,
      * und sie kehrt nach jeder Krise wieder darunter zurueck (die Entlastung wirkt,
        nicht bloss die Sperre).
    """
    cfg = DEFAULT_CONFIG
    master = Rng(42)
    log = EventLog()
    world = worldgen(master, cfg)
    track: dict[int, list[float]] = {}
    for year in range(400):
        world = replace(world, year=year)
        for sid, system in SYSTEMS:
            world = system(world, master.stream(f"{sid}:{year}"), cfg, log)
        for pid, pol in world.polities.items():
            track.setdefault(pid, []).append(_tension_total(pol.tension))

    fired = {e.subjects[0] for e in log if e.kind in DISCHARGES and e.subjects}
    pid = max(track, key=lambda p: (p in fired, len(track[p])))
    series = track[pid]

    assert max(series) - min(series) > 1.5  # keine flache Linie
    over = sum(1 for v in series if v >= cfg.tension_threshold) / len(series)
    assert over < 0.25  # keine Dauerkrise (die Krise ist die Ausnahme)
    assert max(series) >= cfg.tension_threshold  # aber sie erreicht sie auch


def test_the_system_rotates_through_crisis_types() -> None:
    """Kein Fixpunkt: dieselbe Nation durchlaeuft VERSCHIEDENE Krisenarten.

    Genau das leistet "jede Entladung entlastet ihren eigenen Druck, saet aber einen
    anderen" — ohne es liefe jede Nation immer wieder in dieselbe Krise.
    """
    seen: dict[int, set[EventKind]] = {}
    for seed in (7, 42, 1234):
        _, log = simulate(seed=seed, years=400)
        for e in log:
            if e.kind in DISCHARGES and e.subjects:
                seen.setdefault((seed, e.subjects[0]), set()).add(e.kind)  # type: ignore[arg-type]
    assert any(len(kinds) >= 2 for kinds in seen.values())


# === 11. Die Chronik erzaehlt die inneren Umbrueche =========================


def test_the_chronicle_narrates_every_kind_of_internal_crisis() -> None:
    """Sprache entsteht nur in der Chronik — aus kind + subjects + effects + factors."""
    world, log = simulate(seed=8, years=400)
    said = {
        e.kind: erzaehle(world, log, e)
        for e in log
        if e.kind in DISCHARGES
    }
    assert "uprising" in said[EventKind.AUFSTAND]
    assert "overthrew" in said[EventKind.PUTSCH]
    assert "bankrupt" in said[EventKind.BANKROTT]
    assert "collapsed" in said[EventKind.KOLLAPS]
    assert "successor state" in said[EventKind.KOLLAPS]


def test_a_discharge_carries_the_tension_factors_as_its_reasoning() -> None:
    """Die Faktorliste der Entladung IST die Spannungs-Rechnung (§2, keine zweite Quelle)."""
    _, log = simulate(seed=7, years=400)
    tension_labels = {
        FactorLabel.VOLKSDRUCK,
        FactorLabel.ELITENDRUCK,
        FactorLabel.FISKALDRUCK,
        FactorLabel.AUSSENDRUCK,
    }
    events = [e for e in log if e.kind in DISCHARGES]
    assert events
    for event in events:
        labels = {f.label for f in event.factors}
        assert labels  # nie ohne Begruendung
        assert labels <= tension_labels  # und ausschliesslich die Spannungs-Faktoren
        # Die dominante Komponente traegt die Entladung.
        assert max(event.factors, key=lambda f: f.weight).label in tension_labels
