"""CLI: der Nullstart ist der schoene Modus, die Flags sind ueberall dieselben.

Geprueft wird die **Bedienung**, nicht die Simulation: welcher Unterbefehl ohne
Argumente greift (und wovon das abhaengt), dass jeder Lauf seinen Seed und seine
Reproduktions-Zeile nennt, dass gleiche Flags ueberall gleich heissen — und dass
ein Vertipper eine Hilfe bekommt statt eines Tracebacks.
"""

from __future__ import annotations

import pytest
from worldsim.main import (
    COMMANDS,
    DEFAULT_YEARS,
    VIEWS,
    _build_parser,
    _default_command,
    _normalize,
    main,
)

# --- Aufgabe 1: der blanke Aufruf ist die Live-Ansicht ------------------------

def test_bare_call_watches_on_a_terminal(monkeypatch) -> None:
    """Am Terminal ist der Standard die Live-Ansicht — der Standard IST der schoene Modus."""
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)

    assert _default_command() == "watch"
    assert _normalize([]) == ["watch"]
    # Flags ohne Unterbefehl gehoeren dem Standard: 'saeculum -s 42' ist 'watch -s 42'.
    assert _normalize(["-s", "42"]) == ["watch", "-s", "42"]


def test_bare_call_exports_when_piped(monkeypatch) -> None:
    """Ohne TTY (Pipe/Redirect) faellt der blanke Aufruf auf den Text-Export zurueck.

    Damit bleibt ``saeculum > datei.txt`` sinnvoll: dort will niemand ein Dashboard.
    """
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)

    assert _default_command() == "export"
    assert _normalize([]) == ["export"]
    assert _normalize(["--years", "10"]) == ["export", "--years", "10"]


def test_named_command_survives_normalisation(monkeypatch) -> None:
    """Ein genannter Unterbefehl gewinnt immer — auch am Terminal."""
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)

    for command in COMMANDS:
        assert _normalize([command, "-s", "1"]) == [command, "-s", "1"]
    # Auch ein vertipptes Wort laeuft in den Parser (er schlaegt dann etwas vor).
    assert _normalize(["wach"]) == ["wach"]
    # --help gehoert dem Ueberblick, nicht dem Standardbefehl.
    assert _normalize(["--help"]) == ["--help"]


def test_bare_call_writes_a_readable_chronicle(capsys) -> None:
    """Der blanke Aufruf in einer Pipe (wie hier) erzeugt die lesbare Chronik."""
    exit_code = main([])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "History Machine" in out
    assert "was founded in" in out
    assert f"{DEFAULT_YEARS} years" in out  # gute Default-Laenge, ohne Zutun


# --- Aufgabe 3: konsistente Flags ---------------------------------------------

def test_seed_and_years_are_spelled_the_same_everywhere() -> None:
    """-s/--seed und -y/--years gelten in JEDEM Unterbefehl, mit denselben Defaults."""
    parser = _build_parser()

    for command in COMMANDS:
        args = parser.parse_args([command, "-s", "5", "-y", "7"])
        assert (args.seed, args.years) == (5, 7)
        assert parser.parse_args([command, "--seed", "5", "--years", "7"]) == args
        # Ohne Angabe: zufaelliger Seed (spaet gewaehlt) und die Default-Laenge.
        leer = parser.parse_args([command])
        assert leer.seed is None
        assert leer.years == DEFAULT_YEARS


def test_speed_means_years_per_second_in_both_live_views() -> None:
    """--speed hat in watch und replay denselben Namen UND dieselbe Einheit."""
    parser = _build_parser()

    for command in ("watch", "replay"):
        assert parser.parse_args([command, "--speed", "12"]).speed == 12.0
    # Nur die Voreinstellung unterscheidet sich: der Zeitraffer darf raffen.
    assert parser.parse_args(["replay"]).speed > parser.parse_args(["watch"]).speed


def test_view_flag_offers_the_same_two_map_views() -> None:
    """--view heisst ueberall gleich und kennt genau die Ansichten der Karte."""
    from worldsim.presentation import MAP_VIEWS

    # Die CLI fuehrt die Ansichten als Literal (damit sie rich nicht beim Start laedt);
    # dieser Test haelt das Literal an der Karte fest — eine Quelle der Wahrheit.
    assert VIEWS == MAP_VIEWS

    parser = _build_parser()
    for command in ("watch", "replay", "export"):
        assert parser.parse_args([command, "--view", "terrain"]).view == "terrain"
        assert parser.parse_args([command]).view == "political"


# --- Aufgabe 4: Seed als Welt --------------------------------------------------

def test_every_run_names_its_seed_and_how_to_repeat_it(capsys, monkeypatch) -> None:
    """Ohne --seed waehlt die CLI eine Welt — und sagt, wie man sie wiederbekommt."""
    monkeypatch.setattr("worldsim.main._random_seed", lambda: 4711)

    exit_code = main(["export", "-y", "20"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "seed 4711" in out
    # Die Zeile ist kopierbar und vollstaendig: Befehl, Seed, Laenge.
    assert "reproduce this world:  saeculum export --seed 4711 --years 20" in out


def test_a_reproduction_line_reproduces_the_world(capsys) -> None:
    """Die versprochene Zeile haelt: derselbe Aufruf ⇒ dieselbe Chronik (Save = Seed)."""
    main(["export", "--seed", "4711", "--years", "20"])
    erst = capsys.readouterr().out

    main(["export", "--seed", "4711", "--years", "20"])
    assert capsys.readouterr().out == erst


# --- Aufgabe 6: freundliche Fehler ---------------------------------------------

def _fehler(argv: list[str], capsys) -> str:
    with pytest.raises(SystemExit) as exit_info:
        main(argv)
    assert exit_info.value.code == 2  # Argumentfehler, kein Absturz
    return capsys.readouterr().err


def test_a_mistyped_command_gets_a_suggestion(capsys) -> None:
    err = _fehler(["wach", "-s", "1"], capsys)

    assert "Meintest du:  watch" in err
    assert "Hilfe:  saeculum --help" in err
    assert "Traceback" not in err


def test_a_mistyped_view_gets_a_suggestion(capsys) -> None:
    """Derselbe Griff hilft auch bei einem Wert, nicht nur bei einem Befehl."""
    err = _fehler(["watch", "--view", "politcal"], capsys)

    assert "Meintest du:  political" in err
    assert "Traceback" not in err


def test_a_mistyped_flag_gets_a_suggestion(capsys) -> None:
    """Ein vertipptes Flag findet sein Vorbild — auch quer ueber die Unterbefehle."""
    assert "Meintest du:  --seed" in _fehler(["watch", "--seedd", "5"], capsys)
    assert "Meintest du:  --years" in _fehler(["export", "--yers", "20"], capsys)


def test_a_wild_guess_gets_no_wrong_suggestion(capsys) -> None:
    """Kein Vorschlag ist besser als ein falscher — dann traegt die Hilfe.

    ``--tempo`` ist kein Vertipper von ``--speed``, sondern ein anderes Wort; wer
    hier ``--map`` vorschlaegt, schickt den Benutzer in die Irre.
    """
    err = _fehler(["watch", "--tempo", "5"], capsys)

    assert "Meintest du" not in err
    assert "Hilfe:  saeculum --help" in err
    assert "Meintest du" not in _fehler(["xyzzy"], capsys)


def test_bad_numbers_explain_themselves(capsys) -> None:
    """Eine unbrauchbare Zahl erklaert sich und schlaegt etwas Brauchbares vor."""
    assert "ist keine ganze Zahl" in _fehler(["export", "--years", "viele"], capsys)
    assert "rueckwaerts" in _fehler(["export", "--years", "-5"], capsys)
    assert "Jahre pro Sekunde" in _fehler(["watch", "--speed", "schnell"], capsys)
    assert "ausserhalb" in _fehler(["watch", "--speed", "9999"], capsys)
    assert "ein Seed ist eine Zahl" in _fehler(["watch", "--seed", "welt"], capsys)


# --- Aufgabe 5: Entdeckbarkeit -------------------------------------------------

def test_help_shows_every_command_and_an_example(capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out

    for command in COMMANDS:
        assert command in out
    assert "Beispiele:" in out
    assert "saeculum export -s 42 > welt.txt" in out


def test_live_help_names_the_interactive_keys(capsys) -> None:
    """Wer 'watch --help' liest, erfaehrt die Tasten, bevor der Lauf startet."""
    with pytest.raises(SystemExit):
        main(["watch", "--help"])
    out = capsys.readouterr().out

    for taste in ("Leertaste", "+/-", "q"):
        assert taste in out
