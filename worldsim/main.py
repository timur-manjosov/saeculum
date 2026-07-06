"""main — schmale CLI ueber dem headless Kern.

Drei Betriebsarten (``--mode``): ``headless`` druckt die teilbare Text-Chronik
(nur Stdlib — der Kern bleibt abhaengigkeitsfrei), ``watch`` zeigt das
Live-Dashboard, ``replay`` spielt die ganze Geschichte im Zeitraffer ab. Die
Praesentations-Modi liegen in der ``presentation``-Schicht und ziehen ihre
Runtime-Abhaengigkeiten (``rich``/``numpy``/``opensimplex``) **erst bei Gebrauch**
nach (lazy import). So laeuft die Chronik weiterhin ohne installierte Extras.

Save = Seed: jeder Lauf ist durch ``(seed, years, config_version)`` vollstaendig
bestimmt; der Kopf jeder Ausgabe nennt diese Kennung, damit sich eine Welt durch
blosses Teilen des Seeds reproduzieren laesst.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from worldsim.chronicle import chronik_mit_zeitaltern, erklaere
from worldsim.config import DEFAULT_CONFIG, Config
from worldsim.driver import simulate
from worldsim.events import EventKind, EventLog
from worldsim.models import World

__all__ = ["main"]


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="worldsim",
        description=(
            "History Machine — eine Welt, die ihre eigene Geschichte schreibt. "
            "Simuliert deterministisch aus einem Seed und erzaehlt die kausale Chronik."
        ),
    )
    parser.add_argument("--seed", type=int, default=0, help="Master-Seed (Save = Seed).")
    parser.add_argument("--years", type=int, default=200, help="Zu simulierende Jahre.")
    parser.add_argument(
        "--mode",
        choices=("headless", "watch", "replay"),
        default="headless",
        help="headless: Text-Chronik (Default) · watch: Live-Dashboard · replay: Zeitraffer.",
    )
    # --- ergaenzende Ansichten (zusaetzlich zum Modus) --------------------
    extras = parser.add_argument_group("additional views")
    extras.add_argument(
        "--stats", action="store_true", help="End-of-Run-Statistik (Sparklines) drucken."
    )
    extras.add_argument(
        "--map", action="store_true", help="Prozedurale Biom-/Territorien-Karte anzeigen."
    )
    extras.add_argument(
        "--why",
        type=int,
        default=None,
        metavar="ENTITY",
        help="'Warum?'-Kette zum Rueckschlag einer Nation (Entitaets-id).",
    )
    extras.add_argument(
        "--why-event",
        type=int,
        default=None,
        metavar="EVENT",
        help="'Warum?'-Kette zu einem konkreten Event (Event-id).",
    )
    extras.add_argument(
        "--speed", type=float, default=6.0, help="Replay-Tempo (Jahre pro Sekunde grob)."
    )
    extras.add_argument(
        "--fps", type=float, default=6.0, help="Live-Bildrate (Jahre pro Sekunde)."
    )
    extras.add_argument(
        "--no-map",
        dest="show_map",
        action="store_false",
        help="Karte in watch/replay ausblenden (schnellere Ansicht).",
    )
    # --- Faktoren-Aufschluesselungen (Erklaerbarkeit) ---------------------
    explain = parser.add_argument_group("factor breakdowns")
    explain.add_argument(
        "--explain",
        type=int,
        default=0,
        metavar="N",
        help="Faktoren-Aufschluesselung der ersten N Kriegs-Events.",
    )
    explain.add_argument(
        "--explain-split",
        action="store_true",
        help="Faktoren-Aufschluesselung der ersten Fragmentierung (Abspaltung).",
    )
    explain.add_argument(
        "--explain-schism",
        action="store_true",
        help="Das erste Schisma, das ein Buendnis zerbrach, samt Folge-Events.",
    )
    parser.set_defaults(show_map=True)
    return parser.parse_args(argv)


def _counts(log: EventLog) -> dict[str, int]:
    """Zaehle die erzaehlenswerten Ereignisarten fuer die Kopf-/Fusszeile."""
    shocks = (EventKind.PEST, EventKind.ERDBEBEN, EventKind.DUERRE)
    return {
        "successions": sum(1 for e in log if e.kind == EventKind.SUKZESSION),
        "fragmentations": sum(1 for e in log if e.kind == EventKind.ABSPALTUNG),
        "conversions": sum(1 for e in log if e.kind == EventKind.KONVERSION),
        "schisms": sum(1 for e in log if e.kind == EventKind.SCHISMA),
        "disasters": sum(1 for e in log if e.kind in shocks),
        "turning_points": sum(1 for e in log if e.kind == EventKind.WENDEPUNKT),
    }


def _banner(args: argparse.Namespace, cfg: Config) -> str:
    """Kopfzeile mit der Lauf-Identitaet (Save = Seed) — zum Teilen der Welt."""
    return (
        f"History Machine — seed {args.seed}, {args.years} years "
        f"(config v{cfg.config_version})"
    )


def _share_footer(args: argparse.Namespace, world: World, log: EventLog, cfg: Config) -> str:
    """Fusszeile: Kennzahlen plus der exakte Befehl, um die Welt zu reproduzieren."""
    c = _counts(log)
    return (
        "-" * 60 + "\n"
        f"seed {args.seed} · {args.years} years · config v{cfg.config_version} · "
        f"{len(world.polities)} nations · {len(world.identities)} faiths · "
        f"{c['disasters']} disasters · {c['turning_points']} turning points · "
        f"{len(log)} events\n"
        f"share this world:  worldsim --seed {args.seed} --years {args.years}"
    )


def _print_chronicle(world: World, log: EventLog, cfg: Config) -> None:
    for line in chronik_mit_zeitaltern(world, log, cfg):
        print(line)


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


def _run_extras(args: argparse.Namespace, world: World, log: EventLog, cfg: Config) -> None:
    """Ergaenzende Ansichten (Statistik, Karte, Warum-Ketten) — lazy importiert."""
    if not (args.stats or args.map or args.why is not None or args.why_event is not None):
        return
    from rich.console import Console

    from worldsim.presentation import (
        render_map,
        warum_entitaet,
        warum_event,
        zusammenfassung_zeilen,
    )

    console = Console()
    if args.stats:
        print()
        for line in zusammenfassung_zeilen(world, log, cfg, args.years):
            print(line)
    if args.map:
        console.print(render_map(world, seed=args.seed))
    if args.why is not None:
        console.print("\n[bold]why-chain for entity[/]")
        for line in warum_entitaet(world, log, args.why):
            print(line)
    if args.why_event is not None:
        console.print("\n[bold]why-chain for event[/]")
        for line in warum_event(world, log, args.why_event):
            print(line)


def main(argv: Sequence[str] | None = None) -> int:
    """Einstiegspunkt der CLI. Simuliert und zeigt Chronik, Live-Ansicht oder Replay."""
    args = _parse_args(argv)
    cfg = DEFAULT_CONFIG
    world, log = simulate(seed=args.seed, years=args.years)

    if args.mode == "headless":
        print(_banner(args, cfg))
        print()
        _print_chronicle(world, log, cfg)
        _print_explanations(world, log, args)
        _run_extras(args, world, log, cfg)
        print(_share_footer(args, world, log, cfg))
        return 0

    # Praesentations-Modi (rich): das Dashboard/Replay traegt den Seed im Kopf.
    from worldsim.presentation import live_dashboard, replay

    if args.mode == "watch":
        live_dashboard(world, log, cfg, seed=args.seed, fps=args.fps, show_map=args.show_map)
    else:  # replay
        replay(world, log, cfg, seed=args.seed, speed=args.speed, show_map=args.show_map)
    _run_extras(args, world, log, cfg)
    print(_share_footer(args, world, log, cfg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
