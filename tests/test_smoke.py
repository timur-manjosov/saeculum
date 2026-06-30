"""Smoke & Lebendigkeit: der headless Kern erzeugt eine lebende, lesbare Welt."""

from __future__ import annotations

from worldsim.chronicle import chronik
from worldsim.config import DEFAULT_CONFIG
from worldsim.driver import simulate
from worldsim.events import EventKind, EventLog
from worldsim.main import main
from worldsim.models import World


def test_simulate_runs_without_error() -> None:
    world, log = simulate(seed=42, years=100)

    assert isinstance(world, World)
    assert isinstance(log, EventLog)
    # Jahre sind 0-basiert; das zuletzt gesetzte Jahr ist years - 1.
    assert world.year == 99


def test_zero_years_keeps_initial_world() -> None:
    world, log = simulate(seed=1, years=0)

    # Worldgen laeuft, aber ohne Jahre gibt es keine Tick-Events.
    assert world.year == 0
    assert len(world.polities) == DEFAULT_CONFIG.num_nations
    assert len(log) == 0


def test_world_is_alive() -> None:
    """Gruendung jeder Nation, plus Expansion und Wachstum als emergente Folgen."""
    world, log = simulate(seed=42, years=100)

    foundings = [e for e in log if e.kind == EventKind.GRUENDUNG]
    # Genau eine Gruendung je Anfangsnation; durch Fragmentierung (Phase 3) kann
    # die Zahl der Nationen spaeter ueber die Anfangszahl hinauswachsen.
    assert len(foundings) == DEFAULT_CONFIG.num_nations
    assert len(world.polities) >= DEFAULT_CONFIG.num_nations
    assert any(e.kind == EventKind.EXPANSION for e in log)
    assert any(e.kind == EventKind.BEVOELKERUNG_MEILENSTEIN for e in log)


def test_chronicle_is_readable_text() -> None:
    world, log = simulate(seed=42, years=100)
    lines = chronik(world, log, DEFAULT_CONFIG)

    assert lines
    assert all(line.startswith("Year ") for line in lines)
    # Die Wichtigkeits-Schwelle filtert mindestens nichts Unmoegliches.
    assert len(lines) <= len(log)


def test_cli_main_runs(capsys) -> None:
    exit_code = main(["--seed", "42", "--years", "100"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "was founded in" in out
