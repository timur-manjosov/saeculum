"""render — die einzige Pixel-erzeugende Schicht: Live-Dashboard, Replay, Steuerung.

Baut auf ``rich``. Konsumiert **read-only** ``World`` + ``EventLog`` und die
zentrale ``event_to_visual``-Abbildung — beide Ansichten (Live und Replay) teilen
denselben ``ViewState``-Reducer und dieselbe Optik. **Keine** Simulationslogik,
**keine** Re-Simulation: Replay spielt nur den gespeicherten Log ab.

Auf einem echten Terminal animiert ``rich.Live`` mit Tempo-/Pause-/Schritt-/
Beenden-Steuerung. Ohne Terminal (Pipe, Tests) werden stattdessen einige
Schnappschuss-Frames als Text gedruckt — schnell und ohne Schlafphasen.
"""

from __future__ import annotations

import select
import sys
import time
from collections import deque
from dataclasses import dataclass

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from worldsim.chronicle import erzaehle
from worldsim.config import Config
from worldsim.events import Event, EventLog
from worldsim.models import World
from worldsim.presentation.visual import ViewState, event_to_visual
from worldsim.presentation.worldmap import render_map

__all__ = ["Steuerung", "live_dashboard", "replay"]

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


def _top_table(world: World, view: ViewState) -> Table:
    """Rangtabelle der maechtigsten Nationen aus dem rekonstruierten Besitz."""
    counts = view.territory_counts()
    ranked = sorted(counts.items(), key=lambda kv: (kv[1], -kv[0]), reverse=True)[:_TOP]
    table = Table(box=None, pad_edge=False, expand=False)
    table.add_column("nation", style="bold")
    table.add_column("land", justify="right")
    table.add_column("pop", justify="right")
    table.add_column("faith")
    for pid, count in ranked:
        pol = world.polities.get(pid)
        name = pol.name if pol else f"#{pid}"
        pop = view.population.get(pid, pol.population if pol else 0)
        faith_id = view.faith.get(pid, pol.identity_id if pol else None)
        faith = world.identities.get(faith_id) if faith_id else None
        table.add_row(name, str(count), str(pop), faith.name if faith else "?")
    return table


def _feed_panel(feed: deque[tuple[str, str, str]]) -> Panel:
    """Das Feed-Panel der juengsten Ereignisse (farbige Glyphe + Narration)."""
    text = Text()
    for color, glyph, line in feed:
        text.append(f"{glyph} ", style=color)
        text.append(line + "\n")
    if not feed:
        text.append("…", style="dim")
    return Panel(text, title="recent events", border_style="grey50")


def _frame(
    world: World,
    view: ViewState,
    feed: deque[tuple[str, str, str]],
    *,
    seed: int,
    year: int,
    max_year: int,
    title: str,
    ctrl: Steuerung,
    show_map: bool,
) -> RenderableType:
    """Setze einen vollstaendigen Frame zusammen (Kopf, Karte, Top-Nationen, Feed)."""
    status = "‖ paused" if ctrl.paused else f"▶ {ctrl.speed:.1f}×"  # noqa: RUF001
    header = Text.assemble(
        (f" {title} ", "bold white on dark_blue"),
        ("  year ", "bold"),
        (f"{year:>4}/{max_year}", "bright_white"),
        ("   ", ""),
        (status, "bright_yellow"),
        (f"   nations {len(view.territory_counts())}", "cyan"),
    )
    body: list[RenderableType] = [header]
    if show_map:
        body.append(render_map(world, seed=seed, owners=dict(view.owner)))
    body.append(_top_table(world, view))
    body.append(_feed_panel(feed))
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
    feed: deque[tuple[str, str, str]] = deque(maxlen=_FEED)
    by_year = _events_by_year(log)
    max_year = max(by_year, default=0)
    ctrl = Steuerung(speed=1.0)

    def advance(year: int) -> None:
        view.year = year
        for event in by_year.get(year, ()):
            view.apply(event)
            vis = event_to_visual(event)
            feed.append((vis.color, vis.glyph, erzaehle(world, log, event)))

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
                        title=title, ctrl=ctrl, show_map=show_map,
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
                    title=title, ctrl=ctrl, show_map=show_map,
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


def live_dashboard(
    world: World,
    log: EventLog,
    cfg: Config,
    *,
    seed: int = 0,
    fps: float = 8.0,
    show_map: bool = True,
    console: Console | None = None,
) -> None:
    """Live-Dashboard: aktuelles Jahr, Top-Nationen, juengste Events (Aufgabe 2).

    Spielt die visuelle Historie im normalen Tempo ab (Beobachtung, keine
    Steuerung). Auf einem TTY animiert es; sonst druckt es Schnappschuss-Frames.
    """
    _ = cfg  # read-only Signatur-Konsistenz; die Ansicht braucht keine Config
    _play(
        world, log, seed=seed, title="LIVE", base_delay=1.0 / max(fps, 0.1),
        interactive=False, show_map=show_map, console=console, snapshot_frames=5,
    )


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
