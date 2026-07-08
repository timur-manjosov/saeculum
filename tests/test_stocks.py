"""Aenderung 1: das Ressourcen-Modell — drei handelbare Bestaende.

Nationen halten ``Stocks(getreide, eisen, gold)`` statt abstrakter Werte.
Getreide uebernimmt die Nahrungsdynamik (treibt Wachstum bzw. Hunger), Gold den
Schatz, Eisen entsteht aus einfacher Foerderung. Legitimitaet ist kein Bestand
mehr (sie wird abgeleitet). Diese Tests sichern die neuen Invarianten:
Bestaende >= 0, alle drei werden produziert, und die Getreide-Bilanz treibt
Wachstum und Mangel wie zuvor.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from worldsim.config import Config
from worldsim.driver import simulate
from worldsim.events import EventKind
from worldsim.models import Polity, Stocks
from worldsim.systems import bevoelkerung


def test_stocks_is_frozen_pure_data() -> None:
    """``Stocks`` ist reiner, unveraenderlicher Wert (fortgeschrieben per replace)."""
    s = Stocks()
    assert (s.getreide, s.eisen, s.gold) == (0.0, 0.0, 0.0)
    with pytest.raises(FrozenInstanceError):
        s.gold = 5.0  # type: ignore[misc]


def test_legitimacy_is_not_a_stored_polity_resource() -> None:
    """Legitimitaet wird abgeleitet — es gibt kein ``Polity.legitimacy``-Feld mehr."""
    assert not hasattr(Polity(id=0), "legitimacy")


@pytest.mark.parametrize("seed", [1, 42, 1234])
def test_all_three_stocks_stay_nonnegative(seed: int) -> None:
    """Ueber viele Ticks bleibt jeder der drei Bestaende >= 0."""
    for k in (20, 50, 90):
        world, _ = simulate(seed=seed, years=k)
        for pol in world.polities.values():
            assert pol.stocks.getreide >= 0.0
            assert pol.stocks.eisen >= 0.0
            assert pol.stocks.gold >= 0.0


def test_iron_and_gold_are_produced() -> None:
    """Einfache Eisen-/Gold-Foerderung fuellt die Bestaende (jede Region traegt bei)."""
    world, _ = simulate(seed=42, years=40)
    assert any(pol.stocks.eisen > 0.0 for pol in world.polities.values())
    assert any(pol.stocks.gold > 0.0 for pol in world.polities.values())


def test_grain_surplus_drives_growth() -> None:
    """Reichliches Getreide traegt Wachstum: Bevoelkerungs-Meilensteine feuern."""
    fertile = Config(
        region_food_capacity_min=40.0,
        region_food_capacity_max=60.0,
        harvest_variance=0.05,
    )
    world, log = simulate(seed=42, years=100, cfg=fertile)
    assert any(e.kind == EventKind.BEVOELKERUNG_MEILENSTEIN for e in log)
    # Bevoelkerung ist ueber den Anfangsstand hinaus gewachsen.
    assert max(bevoelkerung(p) for p in world.polities.values()) > fertile.initial_population


def test_grain_shortage_drives_famine() -> None:
    """Getreidemangel treibt Hunger: HUNGERSNOT-Events kosten Bevoelkerung."""
    barren = Config(
        region_food_capacity_min=5.0,
        region_food_capacity_max=8.0,
        harvest_variance=0.9,
        initial_getreide=0.0,
    )
    _, log = simulate(seed=5, years=120, cfg=barren)
    famines = [e for e in log if e.kind == EventKind.HUNGERSNOT]
    assert famines
    # Jede Hungersnot ist eine echte Getreide-Bilanz-Folge: sie senkt Bevoelkerung.
    assert all(
        any(
            eff.field == "population" and int(eff.after) < int(eff.before)  # type: ignore[arg-type]
            for eff in e.effects
        )
        for e in famines
    )
