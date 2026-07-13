"""Aenderung 2: sozio-oekonomische Schichtung.

Eine Nation hat eine innere Struktur aus drei Schichten (Arbeiter/Soldat/Elite)
statt einer skalaren Bevoelkerung. Diese Tests sichern: die Gesamtbevoelkerung ist
die Summe der Schichtgroessen (kein eigenes Feld), die Wohlstandsanteile bleiben
normiert, und der Groll baut sich nachweisbar bei Getreidemangel auf (die Groesse
allein — die Entladung kommt mit Aenderung 6).
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from worldsim.config import Config
from worldsim.driver import simulate
from worldsim.models import GoalKind, Polity, Stratum, StratumKind
from worldsim.systems import bevoelkerung, initial_strata


def _stratum(pol: Polity, kind: StratumKind) -> Stratum:
    return next(s for s in pol.strata if s.kind == kind)


def _peak_worker_grievance(world) -> float:
    return max(
        _stratum(p, StratumKind.ARBEITER).grievance for p in world.polities.values()
    )


def test_polity_has_no_scalar_population_field() -> None:
    """Bevoelkerung ist abgeleitet — kein ``Polity.population``-Feld mehr."""
    assert not hasattr(Polity(id=0), "population")


def test_population_is_the_sum_of_strata_sizes() -> None:
    """Gesamtbevoelkerung = Summe der Schichtgroessen, ueber die ganze Sim."""
    world, _ = simulate(seed=42, years=80)
    for pol in world.polities.values():
        assert bevoelkerung(pol) == int(sum(s.size for s in pol.strata))
        assert bevoelkerung(pol) > 0


def test_initial_strata_match_configured_composition() -> None:
    """Anfangs-Schichtung: kanonische Reihenfolge, Groessen- und Wohlstandsanteile."""
    cfg = Config()
    strata = initial_strata(cfg)
    assert tuple(s.kind for s in strata) == (
        StratumKind.ARBEITER,
        StratumKind.SOLDAT,
        StratumKind.ELITE,
    )
    assert sum(s.size for s in strata) == pytest.approx(cfg.initial_population)
    assert sum(s.wealth_share for s in strata) == pytest.approx(1.0)
    assert all(s.grievance == 0.0 for s in strata)


@pytest.mark.parametrize("seed", [1, 42, 1234])
def test_wealth_shares_stay_normalized(seed: int) -> None:
    """Die Wohlstandsanteile jeder Nation summieren ueber die Zeit zu ~1."""
    world, _ = simulate(seed=seed, years=90)
    for pol in world.polities.values():
        assert sum(s.wealth_share for s in pol.strata) == pytest.approx(1.0)


def test_determinism_of_strata() -> None:
    """Gleicher Seed ⇒ identische Schichtung (Groessen, Groll, Anteile)."""
    wa, _ = simulate(seed=11, years=100)
    wb, _ = simulate(seed=11, years=100)
    assert {pid: p.strata for pid, p in wa.polities.items()} == {
        pid: p.strata for pid, p in wb.polities.items()
    }


def test_grievance_starts_at_zero_and_accumulates() -> None:
    """Groll ist anfangs 0 und baut sich (aus Ungleichheit) ueber die Jahre auf."""
    w0, _ = simulate(seed=42, years=0)
    assert all(s.grievance == 0.0 for pol in w0.polities.values() for s in pol.strata)
    w1, _ = simulate(seed=42, years=60)
    assert _peak_worker_grievance(w1) > 0.0


def test_scarcity_raises_grievance() -> None:
    """Getreidemangel treibt den Arbeiter-Groll (Aenderung 2) — isoliert vom zweiten Treiber.

    Zwei Stellschrauben sind hier stillgelegt, und beide aus einem gemessenen Grund:

    * die **Entladung** (unerreichbare Schwelle): sonst kappte der Aufstand in der kargen
      Welt genau den Groll, den dieser Test messen will;
    * die **Ungleichheit** (``grievance_inequality_rate=0``): sie ist der zweite Treiber
      des Grolls und laeuft in BEIDEN Welten an den Deckel — der Hunger verschwaende
      unter ihr. Ohne sie misst der Test genau das, was er behauptet: den Hunger.

    Der Mangel selbst wird seit Aenderung 7 nicht mehr gewuerfelt (die Ernteschwankung ist
    fort). Karges Land traegt die Bevoelkerung nicht, die auf ihm sitzt — das ist der
    ganze Mechanismus.
    """
    quiet = Config(tension_threshold=1e9, grievance_inequality_rate=0.0)
    fertile = replace(
        quiet,
        region_food_capacity_min=40.0,
        region_food_capacity_max=60.0,
    )
    barren = replace(
        quiet,
        region_food_capacity_min=2.0,
        region_food_capacity_max=3.0,
        initial_getreide=0.0,
    )
    wf, _ = simulate(seed=7, years=120, cfg=fertile)
    wb, _ = simulate(seed=7, years=120, cfg=barren)
    assert _peak_worker_grievance(wf) == pytest.approx(0.0)  # satt: kein Grund zum Groll
    assert _peak_worker_grievance(wb) > 0.5  # karg: der Hunger allein treibt ihn


def test_soldiers_track_the_target_share() -> None:
    """Rekrutierung haelt den Soldaten-Anteil nahe am Zielwert (homoeostatisch).

    Der Zielwert ist nationsabhaengig: wer UEBERLEBEN verfolgt, schickt seine Soldaten
    aufs Feld zurueck (``retrench_soldier_fraction``, Aenderung 4) — gegen den rohen
    ``target_soldier_fraction`` zu pruefen, hiesse gegen die falsche Zahl zu pruefen.
    Ausgenommen sind Nationen im Nachklang einer Entladung: der Bankrott entlaesst das
    Heer mit ABSICHT (Aenderung 6), die Rekrutierung holt das ueber Jahre wieder auf.
    """
    world, _ = simulate(seed=42, years=120)
    cfg = Config()
    checked = 0
    for pol in world.polities.values():
        total = sum(s.size for s in pol.strata)
        if total <= 0 or world.year - pol.last_crisis < cfg.crisis_cooldown_years:
            continue
        target = cfg.target_soldier_fraction
        if pol.goal is GoalKind.UEBERLEBEN:
            target *= cfg.retrench_soldier_fraction
        assert abs(_stratum(pol, StratumKind.SOLDAT).size / total - target) < 0.04
        checked += 1
    assert checked  # der Test darf nicht leer durchlaufen
