"""watch — die Jahr-fuer-Jahr *treibende* Live-Ansicht (Beobachtung als Primaermodus).

Anders als ``replay`` (das einen fertigen Log abspielt) **treibt** ``watch`` die
Simulation inkrementell: nach jedem Jahr wird der neue Weltzustand samt der in
diesem Jahr entstandenen Ereignisse gerendert. Beobachtung ist der Primaermodus —
es gibt Pause/Weiter und Tempo, aber **keine** Verlaufssteuerung (kein Zuruecklaufen).

Der Kern bleibt **unveraendert**: ``weltlauf`` spiegelt exakt die Tick-Schleife von
``driver.simulate`` — dieselben benannten Sub-Stroeme, dieselbe Systemreihenfolge —
nutzt dafuer aber nur die **oeffentlichen** Kern-Primitive (``Rng``, ``worldgen``,
``SYSTEMS``). Damit ist der Lauf byte-identisch zu ``simulate`` (ein Test haelt
beide deckungsgleich), und die Praesentation bleibt read-only ueber den Kern.

Auf einem echten Terminal animiert ``rich.Live``; ohne TTY (Pipe, Tests) werden
einige Schnappschuss-Frames gedruckt — schnell, ohne Schlafphasen. Pacing-Bausteine
(``Steuerung``, Tastenpumpe, Schnappschuss-Jahre) und das Ereignis-Panel
(``feed_tafel``) teilt ``watch`` mit ``replay`` bzw. dem statischen Renderer.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator
from dataclasses import replace

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from worldsim.chronicle import erzaehle
from worldsim.config import DEFAULT_CONFIG, Config
from worldsim.driver import SYSTEMS, worldgen
from worldsim.events import EventKind, EventLog
from worldsim.models import World
from worldsim.presentation.components import feed_tafel
from worldsim.presentation.palette import ROSE_PINE_MOON as P
from worldsim.presentation.render import Steuerung, _pump, _snapshot_years
from worldsim.presentation.worldmap import render_map
from worldsim.rng import Rng

__all__ = ["watch", "weltlauf"]

_FEED = 10  # Zeilen im streamenden Ereignis-Feed
_TOP = 7  # angezeigte Top-Polities
_BAR_WIDTH = 9  # Breite der kompakten Balken


def weltlauf(
    seed: int, years: int, cfg: Config = DEFAULT_CONFIG
) -> Iterator[tuple[World, EventLog]]:
    """Treibe die Simulation Jahr fuer Jahr; gib nach jedem Jahr ``(Welt, Log)`` frei.

    Spiegelt die Tick-Schleife von ``driver.simulate`` exakt, arbeitet aber
    inkrementell (statt in einem Rutsch). ``log`` ist dasselbe wachsende Objekt in
    jedem Schritt; die in Jahr *y* entstandenen Ereignisse liest der Renderer per
    ``log.by_year(y)``. Der Kern wird nicht angefasst — nur seine oeffentlichen
    Primitive angetrieben (Save = Seed bleibt gewahrt).
    """
    master = Rng(seed)
    log = EventLog()
    world = worldgen(master, cfg)
    for year in range(years):
        world = replace(world, year=year)
        for sid, system in SYSTEMS:
            # Pro System und Jahr ein eigener, benannter Sub-Strom — identisch zu
            # ``simulate`` (Schema ``f"{system_id}:{year}"``).
            stream = master.stream(f"{sid}:{year}")
            world = system(world, stream, cfg, log)
        yield world, log


def _bar(value: float, maximum: float, *, color: str) -> Text:
    """Ein kompakter Balken (gefuellte/leere Bloecke) fuer einen Kennwert."""
    frac = 0.0 if maximum <= 0 else max(0.0, min(1.0, value / maximum))
    filled = round(frac * _BAR_WIDTH)
    bar = Text()
    bar.append("█" * filled, style=color)
    bar.append("░" * (_BAR_WIDTH - filled), style=P.overlay)
    return bar


def _polity_tafel(world: World) -> Table:
    """Die staerksten Polities: Groesse/Legitimitaet/Wohlstand als kompakte Balken."""
    alle = world.polities.values()
    ranked = sorted(
        alle, key=lambda p: (len(p.territory), p.population, -p.id), reverse=True
    )[:_TOP]
    max_land = max((len(p.territory) for p in alle), default=1)
    max_wealth = max((p.stockpiles.wohlstand for p in alle), default=1.0)

    table = Table(box=None, pad_edge=False, expand=False, header_style=P.subtle)
    table.add_column("polity", style=f"bold {P.text}")
    table.add_column("size")
    table.add_column("legitimacy")
    table.add_column("wealth")
    table.add_column("people", justify="right", style=P.subtle)
    table.add_column("creed", style=P.iris)
    for p in ranked:
        rlr = world.rulers.get(p.leader) if p.leader is not None else None
        legit = rlr.legitimacy if rlr else 0.0
        faith = world.identities.get(p.identity_id) if p.identity_id is not None else None
        table.add_row(
            p.name,
            _bar(len(p.territory), max_land, color=P.pine),
            _bar(legit, 1.0, color=P.iris),
            _bar(p.stockpiles.wohlstand, max_wealth, color=P.gold),
            f"{p.population:,}",
            faith.name if faith else "—",
        )
    return table


def _header(world: World, *, year: int, max_year: int, paused: bool, tempo: float) -> Text:
    """Die Kopfzeile: Modus-Badge, Jahr, Status/Tempo und Kennzahlen."""
    people = sum(p.population for p in world.polities.values())
    status = "‖ paused" if paused else f"▶ {tempo:.0f}/s"
    return Text.assemble(
        (" WATCH ", f"bold {P.base} on {P.iris}"),
        ("  year ", P.muted),
        (f"{year:>4}/{max_year}", f"bold {P.text}"),
        ("    ", ""),
        (status, P.gold),
        (f"    polities {len(world.polities)}", P.pine),
        (f"    people {people:,}", P.foam),
    )


def _frame(
    world: World,
    feed: deque[tuple[EventKind, str]],
    *,
    seed: int,
    year: int,
    max_year: int,
    paused: bool,
    tempo: float,
    show_map: bool,
) -> RenderableType:
    """Setze einen vollstaendigen Frame zusammen (Kopf, Karte, Top-Polities, Feed)."""
    body: list[RenderableType] = [
        _header(world, year=year, max_year=max_year, paused=paused, tempo=tempo)
    ]
    if show_map:
        # Die Karte liest den **aktuellen** Besitzstand ⇒ Grenzen wandern Jahr fuer Jahr.
        body.append(render_map(world, seed=seed))
    body.append(
        Panel(
            _polity_tafel(world),
            title="strongest polities",
            title_align="left",
            border_style=P.muted,
        )
    )
    body.append(feed_tafel(feed))
    return Group(*body)


def watch(
    seed: int,
    years: int,
    cfg: Config = DEFAULT_CONFIG,
    *,
    speed: float = 8.0,
    show_map: bool = True,
    console: Console | None = None,
) -> tuple[World, EventLog]:
    """Live-Ansicht: treibe die Welt Jahr fuer Jahr und rendere jeden neuen Zustand.

    ``speed`` sind Jahre pro Sekunde (per ``+``/``-`` zur Laufzeit anpassbar;
    Leertaste pausiert). ``show_map`` blendet die Terrain-/Territorienkarte ein, auf
    der die Grenzen mit den Expansionen wandern. Gibt am Ende ``(World, EventLog)``
    des vollstaendigen Laufs zurueck — damit Fusszeile und Zusatzansichten auf
    demselben Stand aufsetzen. Ohne TTY werden Schnappschuss-Frames gedruckt.
    """
    console = console or Console()
    feed: deque[tuple[EventKind, str]] = deque(maxlen=_FEED)
    max_year = max(years - 1, 0)
    final: tuple[World, EventLog] | None = None

    def ingest(world: World, log: EventLog) -> None:
        nonlocal final
        for event in log.by_year(world.year):
            feed.append((event.kind, erzaehle(world, log, event)))
        final = (world, log)

    def frame(world: World, *, year: int, paused: bool, tempo: float) -> RenderableType:
        return _frame(world, feed, seed=seed, year=year, max_year=max_year,
                      paused=paused, tempo=tempo, show_map=show_map)

    if not console.is_terminal:
        # Kein TTY (Pipe/Test): gleichverteilte Schnappschuss-Frames statt Animation.
        marks = _snapshot_years(max_year, 5)
        for world, log in weltlauf(seed, years, cfg):
            ingest(world, log)
            if world.year in marks:
                console.print(frame(world, year=world.year, paused=False, tempo=speed))
        if final is None:  # years == 0: nur die Anfangswelt zeigen
            world = worldgen(Rng(seed), cfg)
            final = (world, EventLog())
            console.print(frame(world, year=0, paused=False, tempo=speed))
        return final

    ctrl = Steuerung(speed=1.0)
    base_delay = 1.0 / max(speed, 0.1)
    with Live(console=console, refresh_per_second=30, transient=False) as live:
        for world, log in weltlauf(seed, years, cfg):
            if ctrl.quit:
                break
            ingest(world, log)
            live.update(
                frame(world, year=world.year, paused=ctrl.paused, tempo=speed * ctrl.speed)
            )
            _pump(ctrl, base_delay / ctrl.speed)

    if final is None:  # years == 0
        final = (worldgen(Rng(seed), cfg), EventLog())
    return final
