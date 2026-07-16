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
    # Schritt 2: die Tragfaehigkeit kommt aus der Geografie — der Regler dafuer ist
    # ``fertility_capacity_scale`` (skaliert das ganze Land). Ein hoher Wert macht eine
    # fruchtbare Welt.
    fertile = Config(fertility_capacity_scale=6.0)
    world, log = simulate(seed=42, years=100, cfg=fertile)
    assert any(e.kind == EventKind.BEVOELKERUNG_MEILENSTEIN for e in log)
    # Bevoelkerung ist ueber den Anfangsstand hinaus gewachsen.
    assert max(bevoelkerung(p) for p in world.polities.values()) > fertile.initial_population


def test_grain_shortage_drives_famine() -> None:
    """Getreidemangel treibt Hunger: HUNGERSNOT-Events kosten Bevoelkerung.

    Aenderung 7: der Mangel wird nicht mehr gewuerfelt (die Ernteschwankung ist fort).
    Karges Land traegt die Anfangsbevoelkerung schlicht nicht — Malthus, kein Wetter.

    Karg heisst dabei auch ohne ``capital_min_capacity``. Der Boden (Schritt 2) sichert der
    Wiege ausdruecklich zu, dass sie die Anfangsbevoelkerung ernaehren KANN — er ist damit
    die woertliche Verneinung dessen, was hier behauptet wird, und liess diesen Test seine
    eigene Zusage nie pruefen: mit Boden hungerte die karge Welt erst ab Jahr 20 bis 94,
    naemlich sobald ein Krieg einer Nation Land abnahm. Gemessen wurde also Hunger aus
    GEBIETSVERLUST, und der haengt an der Kriegshaeufigkeit — entsprechend fiel der Test
    aus, als eine Zwischeneichung von Schritt 3 sie senkte. Ohne Boden traegt das Land die
    200 Koepfe schlicht nicht: jeder Seed hungert ab Jahr 0, ganz ohne Krieg.
    """
    barren = Config(
        fertility_capacity_scale=0.2, initial_getreide=0.0, capital_min_capacity=0.0
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
