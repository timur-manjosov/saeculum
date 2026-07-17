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


def test_region_coordinates_are_deterministic() -> None:
    """worldgen verortet jede Region reproduzierbar in [0,1)^2 (Koordinaten-Determinismus)."""
    wa, _ = simulate(seed=42, years=0)
    coords_a = {rid: r.coord for rid, r in wa.regions.items()}
    coords_b = {rid: r.coord for rid, r in simulate(seed=42, years=0)[0].regions.items()}

    assert coords_a == coords_b  # gleicher Seed ⇒ identische Geografie
    assert all(0.0 <= x < 1.0 and 0.0 <= y < 1.0 for x, y in coords_a.values())
    assert len(set(coords_a.values())) > 1  # tatsaechlich gestreut
    # Anderer Seed ⇒ andere Geografie.
    coords_c = {rid: r.coord for rid, r in simulate(seed=99, years=0)[0].regions.items()}
    assert coords_c != coords_a


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
    exit_code = main(["export", "--seed", "42", "--years", "100"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "was founded in" in out


def test_cli_seed_sharing_ux(capsys) -> None:
    """Kopf- und Fusszeile nennen den Seed und den exakten Reproduktions-Befehl."""
    exit_code = main(["export", "--seed", "7", "--years", "60"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "History Machine — seed 7, 60 years" in out
    # Save = Seed: die Welt laesst sich durch Teilen genau dieser Zeile reproduzieren.
    assert "reproduce this world:  saeculum export --seed 7 --years 60" in out


def test_cli_replay_runs_headless(capsys) -> None:
    """Der Unterbefehl replay laeuft ohne TTY als Schnappschuss-Ansicht und endet sauber."""
    exit_code = main(["replay", "-s", "1", "-y", "40", "--no-map"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "REPLAY" in out
    assert "reproduce this world:  saeculum replay --seed 1 --years 40" in out


def test_cli_explore_runs_headless(capsys) -> None:
    """Der Unterbefehl explore laeuft ohne TTY als Beispiel-Sitzung und endet sauber."""
    exit_code = main(["explore", "-s", "42", "-y", "120"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "EXPLORE" in out
    assert "reproduce this world:  saeculum explore --seed 42 --years 120" in out


def test_cli_watch_runs_headless(capsys) -> None:
    """Der Unterbefehl watch treibt die Welt und liefert Fusszeile samt Reproduktion."""
    exit_code = main(["watch", "-s", "3", "-y", "30", "--no-map"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "WATCH" in out
    assert "seed 3" in out  # der Seed steht auch ohne Karte im Kopf
    assert "reproduce this world:  saeculum watch --seed 3 --years 30" in out
