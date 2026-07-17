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

import contextlib
import os
import select
import sys
import time
from collections import deque
from collections.abc import Generator
from dataclasses import dataclass

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.table import Table
from rich.text import Text

from worldsim.chronicle import epochen, erzaehle
from worldsim.config import Config
from worldsim.events import Event, EventKind, EventLog
from worldsim.models import World
from worldsim.presentation.components import (
    balken,
    feed_tafel,
    tasten_zeile,
    zeitalter_regel,
)
from worldsim.presentation.palette import ROSE_PINE_MOON as P
from worldsim.presentation.visual import ViewState
from worldsim.presentation.worldmap import MAP_VIEWS, POLITICAL_VIEW, render_map
from worldsim.systems import bevoelkerung

__all__ = ["Steuerung", "replay"]

_FEED = 9  # Zeilen im Ereignis-Feed
_TOP = 6  # angezeigte Top-Nationen


@dataclass
class Steuerung:
    """Beobachtungs-Steuerung: Tempo, Pause, Einzelschritt, Kartenansicht, Beenden.

    Reine Beobachter-Zustaende — nichts hiervon beruehrt die Simulation. Die Kartenansicht
    (``m``) gehoert genau deshalb hierher: welche der beiden Ansichten man sieht, ist eine
    Frage an den Betrachter, nicht an die Welt.
    """

    speed: float = 1.0
    paused: bool = False
    step: bool = False
    quit: bool = False
    view: str = POLITICAL_VIEW

    def taste(self, key: str) -> None:
        """Verarbeite eine Steuertaste (Leertaste=Pause, n=Schritt, +/-=Tempo, m=Karte, q=Ende)."""
        if key in (" ", "p"):
            self.paused = not self.paused
        elif key in ("n", "\x1b"):  # n oder Pfeil (grob): ein Schritt
            self.step = True
            self.paused = False
        elif key in ("+", "="):
            self.speed = min(self.speed * 1.5, 64.0)
        elif key == "-":
            self.speed = max(self.speed / 1.5, 0.1)
        elif key == "m":
            # Zwischen der politischen und der Terrain-Ansicht umschalten: jede ist fuer
            # ihren Zweck aufgeraeumt, keine muss beides koennen.
            self.view = MAP_VIEWS[(MAP_VIEWS.index(self.view) + 1) % len(MAP_VIEWS)]
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
    tempo: float,
    show_map: bool,
    ages: list[tuple[int, str]],
) -> RenderableType:
    """Setze einen vollstaendigen Frame zusammen (Kopf, Banner, Karte, Nationen, Feed, Tasten).

    ``tempo`` ist das **wirksame** Tempo in Jahren pro Sekunde (Grundtempo mal
    Steuerungs-Faktor) — dieselbe Einheit, die die CLI mit ``--speed`` setzt und die
    die Live-Ansicht anzeigt: eine Zahl, eine Bedeutung.
    """
    status = "‖ paused" if ctrl.paused else f"▶ {tempo:.0f}/s"
    age_name, boundary = _age_at(ages, year)
    header = Text.assemble(
        (f" {title} ", f"bold {P.base} on {P.iris}"),
        ("  seed ", P.muted),
        (str(seed), f"bold {P.foam}"),
        ("    year ", P.muted),
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
        body.append(render_map(world, seed=seed, owners=dict(view.owner), view=ctrl.view))
    body.append(_top_table(world, view))
    body.append(feed_tafel(feed))
    body.append(tasten_zeile())
    return Group(*body)


@contextlib.contextmanager
def _tastenmodus() -> Generator[None]:
    """Das Terminal fuer die Dauer der Ansicht auf einzelne Tastendruecke stellen (cbreak).

    Ohne das liefert der Zeilenmodus des Terminals eine Taste erst nach ``Enter`` —
    die angezeigte Tastenleiste waere ein Versprechen, das die Ansicht nicht haelt.
    ``cbreak`` laesst ``Ctrl-C`` bewusst ein Signal bleiben. Der alte Zustand wird
    **immer** zurueckgegeben, auch wenn der Lauf mit einer Ausnahme endet.
    """
    try:
        import termios
        import tty
    except ImportError:  # pragma: no cover - kein POSIX-Terminal (z.B. Windows)
        yield
        return
    if not sys.stdin.isatty():  # Pipe/Test: es gibt nichts umzuschalten
        yield
        return
    fd = sys.stdin.fileno()
    vorher = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, vorher)


def _raw_key(timeout: float) -> str | None:
    """Nicht-blockierend genau eine Taste lesen (nur auf echtem TTY), sonst ``None``."""
    if not sys.stdin.isatty():
        if timeout > 0:
            time.sleep(timeout)
        return None
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if not ready:
        return None
    # Direkt am Deskriptor lesen: der gepufferte Textstrom wuerde auf eine volle Zeile
    # warten wollen — die Steuerung hoert aber auf den einzelnen Tastendruck.
    return os.read(sys.stdin.fileno(), 1).decode("utf-8", "replace") or None


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
    speed: float,
    interactive: bool,
    show_map: bool,
    kartenblick: str,
    console: Console | None,
    snapshot_frames: int,
) -> None:
    """Gemeinsamer Kern von Live und Replay: den Log Jahr fuer Jahr abspielen.

    ``speed`` sind Jahre pro Sekunde — dieselbe Einheit wie in ``watch``; die
    ``Steuerung`` skaliert sie zur Laufzeit (``+``/``-``).
    """
    console = console or Console()
    view = ViewState()
    feed: deque[tuple[EventKind, str]] = deque(maxlen=_FEED)
    by_year = _events_by_year(log)
    max_year = max(by_year, default=0)
    ages = epochen(world, log)  # Zeitalter-Grenzen (rein aus dem Log, kein Re-Sim)
    ctrl = Steuerung(speed=1.0, view=kartenblick)
    base_delay = 1.0 / max(speed, 0.1)

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
                        title=title, ctrl=ctrl, tempo=speed, show_map=show_map, ages=ages,
                    )
                )
        return

    with _tastenmodus(), Live(console=console, refresh_per_second=30, transient=False) as live:
        year = 0
        while year <= max_year and not ctrl.quit:
            advance(year)
            live.update(
                _frame(
                    world, view, feed, seed=seed, year=year, max_year=max_year,
                    title=title, ctrl=ctrl, tempo=speed * ctrl.speed, show_map=show_map,
                    ages=ages,
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
    speed: float = 25.0,
    show_map: bool = True,
    view: str = POLITICAL_VIEW,
    console: Console | None = None,
) -> None:
    """Replay: die ganze Geschichte im Zeitraffer aus dem Log (Aufgabe 4).

    **Keine** Re-Simulation — nur den gespeicherten Event-Log visuell abspielen,
    mit Tempo-/Pause-/Schritt-/Beenden-Steuerung auf einem echten Terminal.
    ``speed`` sind Jahre pro Sekunde (wie in ``watch``, nur raffender voreingestellt),
    ``view`` waehlt die Anfangsansicht der Karte (zur Laufzeit per ``m`` umschaltbar).
    """
    _ = cfg  # read-only Signatur-Konsistenz; die Ansicht braucht keine Config
    _play(
        world, log, seed=seed, title="REPLAY", speed=speed, interactive=True,
        show_map=show_map, kartenblick=view, console=console, snapshot_frames=6,
    )
