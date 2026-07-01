"""main — schmale CLI ueber dem headless Kern.

Konsumiert ausschliesslich Chronicle-Ausgaben; steuert den Verlauf nicht
(Beobachtung ist der Primaermodus). Erst ab dieser Schicht waeren externe
Abhaengigkeiten erlaubt — hier genuegt die Standardbib.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from worldsim.chronicle import chronik, erklaere
from worldsim.config import DEFAULT_CONFIG
from worldsim.driver import simulate
from worldsim.events import EventKind

__all__ = ["main"]


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="worldsim",
        description="History Machine — headless Welt-Simulation (Phase 4).",
    )
    parser.add_argument("--seed", type=int, default=0, help="Master-Seed (Save = Seed).")
    parser.add_argument("--years", type=int, default=200, help="Zu simulierende Jahre.")
    parser.add_argument(
        "--explain",
        type=int,
        default=0,
        metavar="N",
        help="Zeige die Faktoren-Aufschluesselung der ersten N Kriegs-Events.",
    )
    parser.add_argument(
        "--explain-split",
        action="store_true",
        help="Zeige die Faktoren-Aufschluesselung der ersten Fragmentierung (Abspaltung).",
    )
    parser.add_argument(
        "--explain-schism",
        action="store_true",
        help="Zeige das erste Schisma, das ein Buendnis zerbrach, samt Folge-Events.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Einstiegspunkt der CLI. Simuliert, druckt die Chronik (mit Gruenden)."""
    args = _parse_args(argv)
    cfg = DEFAULT_CONFIG
    world, log = simulate(seed=args.seed, years=args.years)

    lines = chronik(world, log, cfg)
    for line in lines:
        print(line)

    successions = sum(1 for e in log if e.kind == EventKind.SUKZESSION)
    fragmentations = sum(1 for e in log if e.kind == EventKind.ABSPALTUNG)
    conversions = sum(1 for e in log if e.kind == EventKind.KONVERSION)
    schismata = sum(1 for e in log if e.kind == EventKind.SCHISMA)
    print(
        f"--- {args.years} years, seed={args.seed}: "
        f"{len(world.polities)} nations, {len(world.rulers)} rulers, "
        f"{len(world.identities)} faiths, {successions} successions, "
        f"{fragmentations} fragmentations, {conversions} conversions, "
        f"{schismata} schisms, {len(log)} events, {len(lines)} in chronicle"
    )

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
        # Das erste Schisma, das mindestens ein Buendnis zerbrach, samt Bruch-Events.
        broken_by = {
            e.causes[0]: e
            for e in log
            if e.kind == EventKind.BUENDNIS_BRUCH and e.causes
        }
        schisms = [
            e
            for e in log
            if e.kind == EventKind.SCHISMA and e.id in broken_by
        ]
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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
