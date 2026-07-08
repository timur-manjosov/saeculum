"""render — die Zeitraffer-Ansicht (Replay) samt Beobachtungs-Steuerung.

Baut auf ``rich``. Konsumiert **read-only** ``World`` + ``EventLog`` und die
zentrale ``event_to_visual``-Abbildung — Replay teilt den ``ViewState``-Reducer
und die Optik mit der Live-Ansicht. **Keine** Simulationslogik, **keine**
Re-Simulation: Replay spielt nur den gespeicherten Log ab. (Die Jahr-fuer-Jahr
*treibende* Live-Ansicht liegt in ``watch``.)

Auf einem echten Terminal animiert ``rich.Live`` mit Tempo-/Pause-/Schritt-/
Beenden-Steuerung. Ohne Terminal (Pipe, Tests) werden stattdessen einige
Schnappschuss-Frames als Text gedruckt — schnell und ohne Schlafphasen. Die
Pacing-Bausteine (``Steuerung``, Tastenpumpe, Schnappschuss-Jahre) teilt Replay
mit ``watch``.
"""

from __future__ import annotations

import select
import sys
import time
from collections import deque
from dataclasses import dataclass

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.table import Table
from rich.text import Text

from worldsim.chronicle import epochen, erzaehle
from worldsim.config import Config
from worldsim.events import Event, EventKind, EventLog
from worldsim.models import World
from worldsim.presentation.components import balken, feed_tafel, zeitalter_regel
from worldsim.presentation.palette import ROSE_PINE_MOON as P
from worldsim.presentation.visual import ViewState
from worldsim.presentation.worldmap import render_map
from worldsim.systems import bevoelkerung

__all__ = ["Steuerung", "replay"]

_FEED = 9  # Zeilen im Ereignis-Feed
_TOP = 6  # angezeigte Top-Nationen


@dataclass
class Steuerung:
    """Beobachtungs-Steuerung: Tempo, Pause, Einzelschritt, Beenden (Aufgabe 8)."""

    speed: float = 1.0
    paused: bool = False
    step: bool = False
    quit: bool = False

    def taste(self, key: str) -> None:
        """Verarbeite eine Steuertaste (Leertaste=Pause, n=Schritt, +/-=Tempo, q=Ende)."""
        if key in (" ", "p"):
            self.paused = not self.paused
        elif key in ("n", "\x1b"):  # n oder Pfeil (grob): ein Schritt
            self.step = True
            self.paused = False
        elif key in ("+", "="):
            self.speed = min(self.speed * 1.5, 64.0)
        elif key == "-":
            self.speed = max(self.speed / 1.5, 0.1)
        elif key in ("q", "\x03"):
            self.quit = True


def _events_by_year(log: EventLog) -> dict[int, list[Event]]:
    grouped: dict[int, list[Event]] = {}
    for event in log:
        grouped.setdefault(event.year, []).append(event)
    return grouped


def _age_at(ages: list[tuple[int, str]], year: int) -> tuple[str, bool]:
    """Der bis ``year`` geltende Zeitalter-Name und ob ``year`` ein Zeitalter eroeffnet.

    ``ages`` sind die ``(Startjahr, Name)``-Grenzen aus ``chronicle.epochen`` — rein
    aus dem Log, ohne Re-Simulation. Am Startjahr eines Zeitalters zeigt der Replay
    ein Banner (``boundary``); dazwischen traegt die Kopfzeile den laufenden Namen.
    """
    name = ages[0][1] if ages else "—"
    boundary = False
    for start, aname in ages:
        if start <= year:
            name = aname
        if start == year:
            boundary = True
    return name, boundary


def _top_table(world: World, view: ViewState) -> Table:
    """Rangtabelle der maechtigsten Nationen aus dem rekonstruierten Besitz."""
    counts = view.territory_counts()
    ranked = sorted(counts.items(), key=lambda kv: (kv[1], -kv[0]), reverse=True)[:_TOP]
    max_land = max((c for _, c in ranked), default=1)
    table = Table(box=None, pad_edge=False, expand=False, header_style=P.subtle)
    table.add_column("nation", style=f"bold {P.text}")
    table.add_column("size")
    table.add_column("land", justify="right", style=P.subtle)
    table.add_column("people", justify="right", style=P.subtle)
    table.add_column("creed", style=P.iris)
    for pid, count in ranked:
        pol = world.polities.get(pid)
        name = pol.name if pol else f"#{pid}"
        pop = view.population.get(pid, bevoelkerung(pol) if pol else 0)
        faith_id = view.faith.get(pid, pol.identity_id if pol else None)
        faith = world.identities.get(faith_id) if faith_id else None
        table.add_row(
            name,
            balken(count, max_land, color=P.pine),
            f"{count}",
            f"{pop:,}",
            faith.name if faith else "—",
        )
    return table


def _frame(
    world: World,
    view: ViewState,
    feed: deque[tuple[EventKind, str]],
    *,
    seed: int,
    year: int,
    max_year: int,
    title: str,
    ctrl: Steuerung,
    show_map: bool,
    ages: list[tuple[int, str]],
) -> RenderableType:
    """Setze einen vollstaendigen Frame zusammen (Kopf, Banner, Karte, Nationen, Feed)."""
    status = "‖ paused" if ctrl.paused else f"▶ {ctrl.speed:.1f}×"  # noqa: RUF001
    age_name, boundary = _age_at(ages, year)
    header = Text.assemble(
        (f" {title} ", f"bold {P.base} on {P.iris}"),
        ("  year ", P.muted),
        (f"{year:>4}/{max_year}", f"bold {P.text}"),
        ("    ", ""),
        (status, P.gold),
        (f"    nations {len(view.territory_counts())}", P.pine),
        ("    ", ""),
        (age_name, P.foam),
    )
    body: list[RenderableType] = [header]
    # Zeitalter-Wechsel: im Eroeffnungsjahr ein Banner quer ueber den Frame.
    if boundary:
        body.append(zeitalter_regel(age_name, year))
    if show_map:
        body.append(render_map(world, seed=seed, owners=dict(view.owner)))
    body.append(_top_table(world, view))
    body.append(feed_tafel(feed))
    return Group(*body)


def _raw_key(timeout: float) -> str | None:
    """Nicht-blockierend genau eine Taste lesen (nur auf echtem TTY), sonst ``None``."""
    if not sys.stdin.isatty():
        if timeout > 0:
            time.sleep(timeout)
        return None
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if ready:
        return sys.stdin.read(1)
    return None


def _pump(ctrl: Steuerung, delay: float) -> None:
    """Warte ``delay`` Sekunden und verarbeite Steuertasten; blockiere bei Pause."""
    key = _raw_key(delay)
    if key is not None:
        ctrl.taste(key)
    while ctrl.paused and not ctrl.step and not ctrl.quit:
        key = _raw_key(0.05)
        if key is not None:
            ctrl.taste(key)


def _play(
    world: World,
    log: EventLog,
    *,
    seed: int,
    title: str,
    base_delay: float,
    interactive: bool,
    show_map: bool,
    console: Console | None,
    snapshot_frames: int,
) -> None:
    """Gemeinsamer Kern von Live und Replay: den Log Jahr fuer Jahr abspielen."""
    console = console or Console()
    view = ViewState()
    feed: deque[tuple[EventKind, str]] = deque(maxlen=_FEED)
    by_year = _events_by_year(log)
    max_year = max(by_year, default=0)
    ages = epochen(world, log)  # Zeitalter-Grenzen (rein aus dem Log, kein Re-Sim)
    ctrl = Steuerung(speed=1.0)

    def advance(year: int) -> None:
        view.year = year
        for event in by_year.get(year, ()):
            view.apply(event)
            feed.append((event.kind, erzaehle(world, log, event)))

    if not console.is_terminal:
        # Kein TTY (Pipe/Test): ein paar Schnappschuss-Frames statt Animation —
        # schnell, ohne Schlafphasen, deterministisch.
        marks = _snapshot_years(max_year, snapshot_frames)
        for year in range(max_year + 1):
            advance(year)
            if year in marks:
                console.print(
                    _frame(
                        world, view, feed, seed=seed, year=year, max_year=max_year,
                        title=title, ctrl=ctrl, show_map=show_map, ages=ages,
                    )
                )
        return

    with Live(console=console, refresh_per_second=30, transient=False) as live:
        year = 0
        while year <= max_year and not ctrl.quit:
            advance(year)
            live.update(
                _frame(
                    world, view, feed, seed=seed, year=year, max_year=max_year,
                    title=title, ctrl=ctrl, show_map=show_map, ages=ages,
                )
            )
            if interactive:
                _pump(ctrl, base_delay / ctrl.speed)
                if ctrl.step:
                    ctrl.step = False
                    ctrl.paused = True
            else:
                time.sleep(base_delay / ctrl.speed)
            year += 1


def _snapshot_years(max_year: int, count: int) -> set[int]:
    """Gleichverteilte Jahre fuer die Text-Schnappschuesse (inkl. Endjahr)."""
    if max_year <= 0 or count <= 1:
        return {max_year}
    step = max_year / (count - 1)
    return {min(max_year, round(i * step)) for i in range(count)} | {max_year}


def replay(
    world: World,
    log: EventLog,
    cfg: Config,
    *,
    seed: int = 0,
    speed: float = 1.0,
    show_map: bool = True,
    console: Console | None = None,
) -> None:
    """Replay: die ganze Geschichte im Zeitraffer aus dem Log (Aufgabe 4).

    **Keine** Re-Simulation — nur den gespeicherten Event-Log visuell abspielen,
    mit Tempo-/Pause-/Schritt-/Beenden-Steuerung auf einem echten Terminal.
    """
    _ = cfg  # read-only Signatur-Konsistenz; die Ansicht braucht keine Config
    _play(
        world, log, seed=seed, title="REPLAY",
        base_delay=0.04 / max(speed, 0.01), interactive=True,
        show_map=show_map, console=console, snapshot_frames=6,
    )
