"""main — die CLI ueber dem headless Kern.

Der **blanke Aufruf** ``saeculum`` startet die Live-Ansicht (``watch``) auf einer
zufaelligen Welt: der Standard IST der schoene Modus. Alles andere haengt an
Unterbefehlen — ``watch`` (live), ``replay`` (Zeitraffer), ``explore`` (Kausal-
Navigation) und ``export`` (Chronik als Text). Ohne TTY (Pipe/Redirect) faellt der
blanke Aufruf auf ``export`` zurueck, damit ``saeculum > datei.txt`` sinnvoll bleibt.

Alle vier Ansichten liegen in der **read-only** ``presentation``-Schicht und ziehen
ihre Runtime-Abhaengigkeit (``rich``) **erst bei Gebrauch** nach (lazy import); der
headless Kern (``simulate``) bleibt unveraendert und kennt die Darstellung nicht.

Save = Seed: jeder Lauf ist durch ``(seed, years, config_version)`` vollstaendig
bestimmt. Darum nennt **jeder** Lauf seinen Seed und schliesst mit der kopierbaren
Reproduktions-Zeile — eine Welt teilt man, indem man diese Zeile teilt.
"""

from __future__ import annotations

import argparse
import difflib
import re
import secrets
import sys
from collections.abc import Sequence
from typing import NoReturn

from worldsim.chronicle import erklaere
from worldsim.config import DEFAULT_CONFIG, Config
from worldsim.driver import simulate
from worldsim.events import EventKind, EventLog
from worldsim.models import World

__all__ = ["main"]

PROG = "saeculum"
DEFAULT_YEARS = 300
WATCH_SPEED = 10.0  # Jahre/Sekunde: die Welt entsteht vor den Augen
REPLAY_SPEED = 25.0  # Jahre/Sekunde: der Zeitraffer darf raffen

COMMANDS = ("watch", "replay", "explore", "export")
# Spiegelt ``presentation.worldmap.MAP_VIEWS`` — hier als Literal, damit die CLI
# ``rich``/``numpy`` erst beim Ausfuehren laedt (ein Test haelt beide deckungsgleich).
VIEWS = ("political", "terrain")

_DESCRIPTION = (
    "History Machine — eine Welt, die ihre eigene Geschichte schreibt.\n"
    "Ohne Argumente: der Live-Ansicht beim Entstehen zusehen (zufaelliger Seed)."
)

_EPILOG = f"""\
Beispiele:
  {PROG}                            zusehen — zufaellige Welt, Seed am Ende
  {PROG} -s 42 -y 400               dieselbe Welt, laenger zusehen
  {PROG} watch -s 42 --speed 4      langsam und in Ruhe
  {PROG} replay -s 42               die fertige Geschichte im Zeitraffer
  {PROG} explore -s 42              warum ist diese Nation zerfallen?
  {PROG} export -s 42 > welt.txt    die Chronik sichern

Ueberall dieselben Flags: -s/--seed, -y/--years, --speed (Jahre/Sekunde),
--view (political/terrain).   Hilfe zu einem Befehl:  {PROG} <befehl> --help

Save = Seed: (seed, years) bestimmen die Welt vollstaendig — wer den Seed teilt,
teilt die Welt. Jeder Lauf endet mit der Zeile, die ihn reproduziert.
"""


# --- freundliche Argumente ---------------------------------------------------

_INVALID_CHOICE = re.compile(r"invalid choice: '([^']*)'")
_UNRECOGNIZED = re.compile(r"unrecognized arguments: (\S+)")
_QUOTED = re.compile(r"'([^']*)'")
# Wie aehnlich ein Vertipper seinem Vorbild sein muss, damit wir ihn vorschlagen.
# Gemessene Trennlinie: echte Vertipper (--seedd, --yers, wach) liegen bei >= 0.83,
# blosse Fremdwoerter (--tempo, --karte) bei <= 0.67. Ein falscher Vorschlag waere
# schlimmer als keiner — im Zweifel schweigen und auf die Hilfe zeigen.
_SIMILAR = 0.8


def _flags(parser: argparse.ArgumentParser) -> list[str]:
    """Alle Flags, die dieser Parser samt seiner Unterbefehle kennt.

    Ein vertipptes Flag meldet der Ueberblick-Parser, der selbst nur ``--help`` kennt —
    also wird hier einmal durch die Unterbefehle gesehen, damit ``--seedd`` trotzdem
    auf ``--seed`` zeigen kann.
    """
    pool = set(parser._option_string_actions)
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):  # der Unterbefehl-Zweig
            for sub in choices.values():
                if isinstance(sub, argparse.ArgumentParser):
                    pool |= set(sub._option_string_actions)
    return sorted(pool)


def _closest(wort: str, kandidaten: Sequence[str]) -> str | None:
    """Der naechstliegende Kandidat — oder ``None``, wenn keiner nah genug ist."""
    nah = difflib.get_close_matches(wort, kandidaten, n=1, cutoff=_SIMILAR)
    return nah[0] if nah else None


class _Parser(argparse.ArgumentParser):
    """argparse mit freundlicher Fehlerausgabe: Vorschlag und Hilfe-Hinweis, nie ein Traceback."""

    def _suggestion(self, message: str) -> str | None:
        """Das Naechstliegende zu einer Fehlmeldung — ein Befehl, ein Wert oder ein Flag.

        Bei ``invalid choice`` stehen die Kandidaten in der Meldung selbst (``choose
        from 'watch', …``); derselbe Griff hilft so bei einem vertippten Befehl **und**
        bei einem vertippten ``--view``-Wert, ohne die Listen hier zu duplizieren.
        """
        falsch = _INVALID_CHOICE.search(message)
        if falsch is not None:
            kandidaten = _QUOTED.findall(message[falsch.end() :]) or list(COMMANDS)
            return _closest(falsch.group(1), kandidaten)
        unbekannt = _UNRECOGNIZED.search(message)
        if unbekannt is not None:
            return _closest(unbekannt.group(1), _flags(self))
        return None

    def error(self, message: str) -> NoReturn:
        """Melde einen Argumentfehler als kurze, hilfreiche Notiz (Exit-Code 2)."""
        self.print_usage(sys.stderr)
        zeilen = [f"{self.prog}: {message}"]
        nah = self._suggestion(message)
        if nah is not None:
            zeilen.append(f"Meintest du:  {nah}")
        zeilen.append(f"Hilfe:  {self.prog} --help")
        self.exit(2, "\n".join(zeilen) + "\n")


def _seed_value(text: str) -> int:
    """Ein Seed ist eine ganze Zahl — die Identitaet einer Welt."""
    try:
        return int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{text!r} ist keine ganze Zahl — ein Seed ist eine Zahl, z.B. --seed 42"
        ) from None


def _years_value(text: str) -> int:
    """Jahre sind eine nicht-negative ganze Zahl."""
    try:
        jahre = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{text!r} ist keine ganze Zahl — z.B. --years {DEFAULT_YEARS}"
        ) from None
    if jahre < 0:
        raise argparse.ArgumentTypeError(
            f"{jahre} Jahre laufen rueckwaerts — z.B. --years {DEFAULT_YEARS}"
        )
    return jahre


def _speed_value(text: str) -> float:
    """Tempo in Jahren pro Sekunde, echt positiv und in erlebbarer Groessenordnung."""
    try:
        tempo = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{text!r} ist keine Zahl — --speed sind Jahre pro Sekunde, z.B. --speed 8"
        ) from None
    if not 0.1 <= tempo <= 240.0:
        raise argparse.ArgumentTypeError(
            f"{tempo:g} Jahre/Sekunde liegen ausserhalb von 0.1..240 — z.B. --speed 8"
        )
    return tempo


def _entity_value(text: str) -> int:
    """Eine Entitaets-/Event-id, wie sie in der Chronik (``#id``) steht."""
    try:
        return int(text.lstrip("#"))
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"{text!r} ist keine id — ids stehen in der Chronik, z.B. --why 30"
        ) from None


# --- der Parser --------------------------------------------------------------


def _add_view(group: argparse._ArgumentGroup) -> None:
    """``--view``: dieselbe Kartenansicht, gleicher Name, in jedem Unterbefehl."""
    group.add_argument(
        "--view",
        choices=VIEWS,
        default=VIEWS[0],
        help=(
            "Kartenansicht: political (Politik als Flaeche, Terrain angedeutet) oder "
            "terrain (Geografie in voller Farbe, Politik als Umriss). Standard: political."
        ),
    )


def _common_parser() -> _Parser:
    """Die Flags, die **jeder** Unterbefehl teilt (gleiche Namen, gleiche Einheiten)."""
    parent = _Parser(add_help=False)
    welt = parent.add_argument_group("Welt")
    welt.add_argument(
        "-s",
        "--seed",
        type=_seed_value,
        default=None,
        metavar="N",
        help="Seed der Welt (Standard: zufaellig — er wird am Ende angezeigt).",
    )
    welt.add_argument(
        "-y",
        "--years",
        type=_years_value,
        default=DEFAULT_YEARS,
        metavar="N",
        help=f"Zu simulierende Jahre (Standard: {DEFAULT_YEARS}).",
    )
    welt.add_argument(
        "--stats",
        action="store_true",
        help="Am Ende Kennzahlen und Verlaeufe (Sparklines) drucken.",
    )
    return parent


def _add_live_flags(parser: argparse.ArgumentParser, *, speed: float) -> None:
    """Die Flags der bewegten Ansichten (``watch``/``replay``)."""
    ansicht = parser.add_argument_group("Ansicht")
    ansicht.add_argument(
        "--speed",
        type=_speed_value,
        default=speed,
        metavar="N",
        help=(
            f"Tempo in Jahren pro Sekunde (Standard: {speed:g}; "
            "waehrend des Laufs mit +/- aenderbar)."
        ),
    )
    _add_view(ansicht)
    ansicht.add_argument(
        "--no-map",
        dest="show_map",
        action="store_false",
        help="Die Karte ausblenden — ruhigere, schnellere Ansicht.",
    )
    parser.set_defaults(show_map=True)


def _build_parser() -> argparse.ArgumentParser:
    """Baue den Parser: ein Ueberblick, vier Unterbefehle, ueberall dieselben Flags."""
    gemeinsam = _common_parser()
    parser = _Parser(
        prog=PROG,
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    befehle = parser.add_subparsers(dest="command", metavar="<befehl>")

    watch = befehle.add_parser(
        "watch",
        parents=[gemeinsam],
        help="die Welt live entstehen sehen (Standard)",
        description=(
            "Live-Ansicht: die Welt entsteht Jahr fuer Jahr vor den Augen — Karte, "
            "staerkste Nationen und der streamende Ereignis-Feed.\n"
            "Tasten: Leertaste pausiert · n einzelner Schritt · +/- Tempo · m Karte · q Ende."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_live_flags(watch, speed=WATCH_SPEED)

    replay = befehle.add_parser(
        "replay",
        parents=[gemeinsam],
        help="die fertige Geschichte im Zeitraffer",
        description=(
            "Zeitraffer: erst simulieren, dann die Geschichte aus dem Ereignis-Log "
            "abspielen — mit Zeitalter-Bannern an den Wendepunkten.\n"
            "Tasten: Leertaste pausiert · n einzelner Schritt · +/- Tempo · m Karte · q Ende."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _add_live_flags(replay, speed=REPLAY_SPEED)

    befehle.add_parser(
        "explore",
        parents=[gemeinsam],
        help="den Kausalgraphen befragen: warum geschah das?",
        description=(
            "Kausal-Navigation: eine Nation oder ein Ereignis waehlen und den Ursachen "
            "folgen.\n"
            "Befehle: why <id|name> · who <id|name> · event <id> · into <id> · then <id> · "
            "back · help · quit."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    export = befehle.add_parser(
        "export",
        parents=[gemeinsam],
        help="die Chronik als Text (Standard ohne Terminal)",
        description=(
            "Text-Export: die gesamte Chronik nach stdout — gegliedert in Zeitalter, "
            "mit Warum-Notizen unter den Wendepunkten. Der Standard in einer Pipe."
        ),
    )
    karte = export.add_argument_group("Ansicht")
    karte.add_argument("--map", action="store_true", help="Die Weltkarte mitdrucken.")
    _add_view(karte)
    kausal = export.add_argument_group("Kausalitaet")
    kausal.add_argument(
        "--why",
        type=_entity_value,
        default=None,
        metavar="ENTITY",
        help="Die 'Warum?'-Kette zum Rueckschlag einer Nation (Entitaets-id).",
    )
    kausal.add_argument(
        "--why-event",
        type=_entity_value,
        default=None,
        metavar="EVENT",
        help="Die 'Warum?'-Kette zu einem konkreten Ereignis (Event-id).",
    )
    kausal.add_argument(
        "--explain",
        type=_entity_value,
        default=0,
        metavar="N",
        help="Faktoren-Aufschluesselung der ersten N Kriegs-Ereignisse.",
    )
    kausal.add_argument(
        "--explain-split",
        action="store_true",
        help="Faktoren-Aufschluesselung der ersten Fragmentierung (Abspaltung).",
    )
    kausal.add_argument(
        "--explain-schism",
        action="store_true",
        help="Das erste Schisma, das ein Buendnis zerbrach, samt Folge-Ereignissen.",
    )
    return parser


def _default_command() -> str:
    """Ohne Unterbefehl gilt: am Terminal zusehen, in einer Pipe exportieren."""
    return "watch" if sys.stdout.isatty() else "export"


def _normalize(argv: Sequence[str] | None) -> list[str]:
    """Setze den Standard-Unterbefehl vor, wenn keiner genannt ist (``saeculum -s 42``).

    Ein fuehrendes Wort laeuft unveraendert in den Parser — auch ein falsch
    geschriebenes, damit es einen Vorschlag statt einer Fehlmeldung bekommt.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if args and (not args[0].startswith("-") or args[0] in ("-h", "--help")):
        return args
    return [_default_command(), *args]


def _random_seed() -> int:
    """Ein zufaelliger, gut merkbarer Seed — bewusst NICHT aus einem Simulations-RNG.

    Die Wahl der Welt ist keine Simulation: ``secrets`` beruehrt keinen der geseedeten
    Stroeme, und ab dem gewaehlten Seed ist der Lauf wieder vollstaendig determiniert.
    """
    return secrets.randbelow(1_000_000)


# --- Ausgaben ----------------------------------------------------------------


def _repro_line(args: argparse.Namespace) -> str:
    """Die kopierbare Zeile, die genau diese Welt zurueckholt (Save = Seed)."""
    return (
        f"reproduce this world:  {PROG} {args.command} "
        f"--seed {args.seed} --years {args.years}"
    )


def _footer(args: argparse.Namespace, world: World, log: EventLog, cfg: Config) -> str:
    """Fusszeile: Kennzahlen plus der exakte Befehl, um die Welt zu reproduzieren."""
    disasters = sum(1 for e in log if e.kind is EventKind.ERDBEBEN)
    turning_points = sum(1 for e in log if e.kind == EventKind.WENDEPUNKT)
    return (
        "-" * 60 + "\n"
        f"seed {args.seed} · {args.years} years · config v{cfg.config_version} · "
        f"{len(world.polities)} nations · {len(world.identities)} faiths · "
        f"{disasters} disasters · {turning_points} turning points · {len(log)} events\n"
        f"{_repro_line(args)}"
    )


def _print_explanations(world: World, log: EventLog, args: argparse.Namespace) -> None:
    if args.explain > 0:
        wars = [e for e in log if e.kind == EventKind.KRIEG]
        print(f"\n=== war factor breakdown (first {args.explain} of {len(wars)}) ===")
        for event in wars[: args.explain]:
            print()
            for line in erklaere(world, log, event):
                print(line)

    if args.explain_split:
        splits = [e for e in log if e.kind == EventKind.ABSPALTUNG]
        print(f"\n=== fragmentation factor breakdown ({len(splits)} total) ===")
        if splits:
            print()
            for line in erklaere(world, log, splits[0]):
                print(line)

    if args.explain_schism:
        broken_by = {
            e.causes[0]: e for e in log if e.kind == EventKind.BUENDNIS_BRUCH and e.causes
        }
        schisms = [e for e in log if e.kind == EventKind.SCHISMA and e.id in broken_by]
        print(f"\n=== schism that broke an alliance ({len(schisms)} such) ===")
        if schisms:
            schism = schisms[0]
            print()
            for line in erklaere(world, log, schism):
                print(line)
            for event in log:
                if event.kind == EventKind.BUENDNIS_BRUCH and schism.id in event.causes:
                    print()
                    for line in erklaere(world, log, event):
                        print(line)


def _export(args: argparse.Namespace, world: World, log: EventLog, cfg: Config) -> None:
    """Die Chronik als Text, plus die angeforderten Zusatzansichten (Karte, Warum-Ketten)."""
    from rich.console import Console

    from worldsim.presentation import render_chronik, render_map, warum_entitaet, warum_event

    render_chronik(world, log, cfg, seed=args.seed, years=args.years)
    _print_explanations(world, log, args)
    console = Console()
    if args.map:
        console.print(render_map(world, seed=args.seed, view=args.view))
    if args.why is not None:
        console.print("\n[bold]why-chain for entity[/]")
        for line in warum_entitaet(world, log, args.why):
            print(line)
    if args.why_event is not None:
        console.print("\n[bold]why-chain for event[/]")
        for line in warum_event(world, log, args.why_event):
            print(line)


def _print_stats(args: argparse.Namespace, world: World, log: EventLog, cfg: Config) -> None:
    from worldsim.presentation import zusammenfassung_zeilen

    print()
    for line in zusammenfassung_zeilen(world, log, cfg, args.years):
        print(line)


# --- Ausfuehrung -------------------------------------------------------------


def _run(args: argparse.Namespace, cfg: Config) -> tuple[World, EventLog]:
    """Fuehre den gewaehlten Unterbefehl aus und gib den Endstand des Laufs zurueck."""
    from worldsim.presentation import explore, replay, watch

    if args.command == "watch":
        # watch treibt die Simulation selbst Jahr fuer Jahr und liefert den Endstand.
        return watch(
            args.seed,
            args.years,
            cfg,
            speed=args.speed,
            show_map=args.show_map,
            view=args.view,
        )

    world, log = simulate(seed=args.seed, years=args.years)
    if args.command == "replay":
        replay(
            world,
            log,
            cfg,
            seed=args.seed,
            speed=args.speed,
            show_map=args.show_map,
            view=args.view,
        )
    elif args.command == "explore":
        explore(world, log, cfg, seed=args.seed)
    else:
        _export(args, world, log, cfg)
    return world, log


def main(argv: Sequence[str] | None = None) -> int:
    """Einstiegspunkt der CLI: ohne Argumente die Live-Ansicht, sonst der Unterbefehl."""
    args = _build_parser().parse_args(_normalize(argv))
    cfg = DEFAULT_CONFIG
    if args.seed is None:
        args.seed = _random_seed()

    try:  # die Ansicht wird erst hier geladen — der Kern kennt sie nicht
        import worldsim.presentation  # noqa: F401
    except ImportError:  # pragma: no cover - Hinweis, wenn die Extras fehlen
        print(
            "Diese Ansicht braucht die Praesentations-Schicht:\n"
            "  pip install '.[presentation]'",
            file=sys.stderr,
        )
        return 1

    try:
        world, log = _run(args, cfg)
    except KeyboardInterrupt:  # pragma: no cover - nur am echten Terminal
        # Kein Traceback: der Abbruch ist eine Entscheidung, kein Fehler. Der Seed
        # bleibt trotzdem stehen, damit die Welt nicht verloren geht.
        print(f"\n{_repro_line(args)}")
        return 130

    if args.stats:
        _print_stats(args, world, log, cfg)
    print(_footer(args, world, log, cfg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
