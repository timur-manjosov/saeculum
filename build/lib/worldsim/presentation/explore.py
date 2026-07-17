"""explore — interaktive Erkundung des Kausalgraphen (``--mode explore``).

Nach einem Lauf laesst sich der Graph **read-only** durchwandern (§5/§7): eine
Entitaet waehlen und ihren Lebenslauf lesen (``chronicle.lebenslauf``), ein
Ereignis waehlen und seine Warum-Kette sehen (``chronicle.warum``, jede Zeile mit
ihren dominanten Faktoren ``label: gewicht`` annotiert), und von einer Ursache
weiter in **deren** Ursachen hineinzoomen.

Alles ist reine **Ableitung** aus dem ``EventLog`` — kein RNG, keine Mutation,
keine neuen Fakten: die Erkundung zeigt nur, was der Graph bereits traegt. Optik
(Glyphen/Akzente) stammt aus der zentralen ``stil_fuer``-/Palette-Quelle (V2),
sodass Chronik, Watch, Replay und Explore dieselbe visuelle Sprache sprechen.

Schlank mit ``rich``: eine Eingabeaufforderung nimmt ``ID``/``Name`` und rendert
die Kette bzw. Biographie. Ohne TTY (Pipe/Test) laeuft stattdessen eine kurze,
deterministische Beispiel-Sitzung ab. Voll klickbare Navigation (``textual``)
waere eine moegliche Ausbaustufe — hier bewusst **nicht** gebaut.
"""

from __future__ import annotations

from collections.abc import Sequence

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text
from rich.tree import Tree

from worldsim.chronicle import (
    dominante_faktoren,
    erzaehle,
    folgen,
    lebenslauf,
)
from worldsim.config import Config
from worldsim.events import Event, EventId, EventLog
from worldsim.models import EntityId, World
from worldsim.presentation.components import ereignis_text, faktoren_inline
from worldsim.presentation.palette import ROSE_PINE_MOON as P
from worldsim.presentation.query import finde_kollaps, warum_entitaet

__all__ = ["explore"]

_MAX_DEPTH = 4  # Tiefe des gezeigten Ursachenbaums (Zoom erreicht den Rest)
_TOP = 8  # Polities im Uebersichts-/Startmenue


# --- Namensaufloesung (nur lesen, nie erfinden) ------------------------------

def _entity_name(world: World, eid: EntityId) -> str:
    """Der Anzeigename einer Entitaet (Polity/Glaube/Herrscher/Region) oder ``entity#id``."""
    if eid in world.polities:
        return world.polities[eid].name
    if eid in world.identities:
        return world.identities[eid].name
    if eid in world.rulers:
        return world.rulers[eid].name
    if eid in world.regions:
        return world.regions[eid].name
    return f"entity#{eid}"


def _resolve_entity(world: World, token: str) -> EntityId | None:
    """Loese ``ID`` oder ``Name`` zu einer Entitaets-id auf (stabil, deterministisch).

    Zahlen sind direkt ids; Namen werden gegen Polities, Glauben, Herrscher und
    Regionen gematcht (exakt vor Praefix, jeweils stabil sortiert). Reines Nachschlagen.
    """
    token = token.strip()
    if not token:
        return None
    if token.lstrip("#").isdigit():
        return int(token.lstrip("#"))
    low = token.lower()
    tables = (world.polities, world.identities, world.rulers, world.regions)
    for exact in (True, False):
        for table in tables:
            for eid in sorted(table):
                name = _entity_name(world, eid).lower()
                if (name == low) if exact else name.startswith(low):
                    return eid
    return None


def _valid_event(log: EventLog, eid: int) -> bool:
    return 0 <= eid < len(log)


# --- Renderer (Optik aus V2: stil_fuer via ereignis_text) --------------------

def _event_line(world: World, log: EventLog, event: Event) -> Text:
    """Eine Ereigniszeile fuer den Baum: ``#id  glyphe Year N: … · faktor: gewicht``."""
    line = Text(f"#{event.id} ", style=P.overlay)  # id sichtbar ⇒ direkt anzoombar
    line.append_text(ereignis_text(event.kind, erzaehle(world, log, event)))
    fac = dominante_faktoren(event)
    if fac:
        line.append("    ")
        line.append_text(faktoren_inline(fac))
    return line


def _why_tree(world: World, log: EventLog, root_id: EventId) -> Tree:
    """Der Ursachenbaum ab ``root_id``: rueckwaerts entlang ``causes``, faktor-annotiert.

    Folgt ausschliesslich **fruehere** Ursachen (der Graph ist zyklenfrei), stabil
    sortiert und dedupliziert — dieselbe Traversierung wie ``chronicle.warum``, nur
    als navigierbarer ``rich``-Baum statt Textliste.
    """
    root = log.get(root_id)
    tree = Tree(_event_line(world, log, root), guide_style=P.overlay)
    seen: set[EventId] = {root_id}

    def add(parent: Tree, eid: EventId, depth: int) -> None:
        event = log.get(eid)
        node = parent.add(_event_line(world, log, event))
        seen.add(eid)
        if depth < _MAX_DEPTH:
            for cause in sorted(event.causes):
                if cause not in seen:
                    add(node, cause, depth + 1)

    for cause in sorted(root.causes):
        if cause not in seen:
            add(tree, cause, 1)
    if not root.causes:
        tree.add(Text("(a root event — no recorded cause)", style=P.muted))
    return tree


def _life_panel(world: World, log: EventLog, entity: EntityId) -> Panel:
    """Der Lebenslauf einer Entitaet: alle Events mit ihr im Subjekt, chronologisch."""
    events = lebenslauf(log, entity)
    body = Text()
    for i, event in enumerate(events):
        if i:
            body.append("\n")
        body.append_text(ereignis_text(event.kind, erzaehle(world, log, event)))
    if not events:
        body.append("(no recorded events for this entity)", style=P.muted)
    title = Text.assemble(
        (f"life of {_entity_name(world, entity)}", f"bold {P.text}"),
        (f"   ·   {len(events)} events", P.muted),
    )
    return Panel(body, title=title, title_align="left", border_style=P.muted, padding=(1, 2))


def _hint(text: str) -> Text:
    return Text(f"  {text}", style=P.muted)


def _intro(world: World, seed: int) -> Panel:
    """Startkarte: die groessten Polities als Einstiegspunkte plus die Befehle."""
    body = Text()
    body.append("pick an entity or an event, read its causes, zoom in.\n\n", style=P.subtle)
    body.append("polities", style=f"bold {P.text}")
    body.append("\n")
    ranked = sorted(
        world.polities.values(), key=lambda p: (len(p.territory), -p.id), reverse=True
    )[:_TOP]
    for p in ranked:
        body.append(f"  #{p.id:<3} ", style=P.overlay)
        body.append(f"{p.name:<12}", style=f"bold {P.pine}")
        body.append(f"  {len(p.territory)} regions\n", style=P.muted)
    body.append("\ncommands\n", style=f"bold {P.text}")
    for cmd, desc in (
        ("why <id|name>", "why did this polity suffer? — its collapse, traced"),
        ("who <id|name>", "the life/history of an entity (biography)"),
        ("event <id>", "the causal tree of one event"),
        ("<id> / into <id>", "zoom into a cause (drill deeper)"),
        ("then <id>", "consequences of an event (forward edge)"),
        ("back", "return to the previous focus"),
        ("help · quit", "this help · leave"),
    ):
        body.append(f"  {cmd:<18}", style=P.foam)
        body.append(f"{desc}\n", style=P.muted)
    return Panel(
        body,
        title=Text.assemble((" EXPLORE ", f"bold {P.base} on {P.iris}"),
                            (f"   seed {seed}", P.muted)),
        title_align="left", border_style=P.muted, padding=(1, 2),
    )


# --- die Erkundungs-Sitzung (Fokus-Stack fuer den Zoom) ----------------------

class _Explorer:
    """Read-only Sitzungszustand: der aktuelle Fokus und ein Stack fuer ``back``."""

    def __init__(self, world: World, log: EventLog, console: Console, *, seed: int = 0) -> None:
        self.world = world
        self.log = log
        self.console = console
        self.seed = seed  # nur zur Anzeige: welche Welt man gerade befragt
        self.focus: EventId | None = None
        self.stack: list[EventId] = []

    # -- Ausgaben ------------------------------------------------------------
    def _show_focus(self, header: RenderableType | None = None) -> None:
        assert self.focus is not None
        parts: list[RenderableType] = []
        if header is not None:
            parts.append(header)
        parts.append(_why_tree(self.world, self.log, self.focus))
        parts.append(_hint("type an id (or 'into <id>') to zoom · 'back' to return"))
        self.console.print(Group(*parts))

    def _focus_event(self, eid: EventId, *, header: RenderableType | None = None) -> None:
        if not _valid_event(self.log, eid):
            self.console.print(_hint(f"no event #{eid} in this log."))
            return
        if self.focus is not None and self.focus != eid:
            self.stack.append(self.focus)
        self.focus = eid
        self._show_focus(header)

    # -- Befehle -------------------------------------------------------------
    def why(self, arg: str) -> None:
        """„Warum ist <Entitaet> zerfallen?" — ihren Rueckschlag finden und ab da tracen."""
        entity = _resolve_entity(self.world, arg)
        if entity is None:
            self.console.print(_hint(f"unknown entity: {arg!r}"))
            return
        eid = finde_kollaps(self.log, entity)
        name = _entity_name(self.world, entity)
        if eid is None:
            # warum_entitaet liefert die ruhige Ein-Zeilen-Antwort (kein Rueckschlag).
            for line in warum_entitaet(self.world, self.log, entity):
                self.console.print(Text(line, style=P.subtle))
            return
        header = Text.assemble(
            ("why did ", P.muted), (name, f"bold {P.text}"), (" suffer?", P.muted),
        )
        self._focus_event(eid, header=header)

    def who(self, arg: str) -> None:
        entity = _resolve_entity(self.world, arg)
        if entity is None:
            self.console.print(_hint(f"unknown entity: {arg!r}"))
            return
        self.console.print(_life_panel(self.world, self.log, entity))

    def event(self, arg: str) -> None:
        token = arg.strip().lstrip("#")
        if not token.isdigit():
            self.console.print(_hint(f"need an event id, got {arg!r}"))
            return
        self._focus_event(int(token))

    def then(self, arg: str) -> None:
        """Vorwaertskante: die Ereignisse, die dieses als Ursache fuehren (``folgen``)."""
        token = arg.strip().lstrip("#")
        if not token.isdigit() or not _valid_event(self.log, int(token)):
            self.console.print(_hint(f"need a valid event id, got {arg!r}"))
            return
        outgoing = folgen(self.log, int(token))
        if not outgoing:
            self.console.print(_hint(f"#{token} led to nothing recorded."))
            return
        lines: list[RenderableType] = [
            Text.assemble(("consequences of ", P.muted), (f"#{token}", f"bold {P.text}")),
        ]
        lines.extend(_event_line(self.world, self.log, e) for e in outgoing)
        self.console.print(Group(*lines))

    def back(self) -> None:
        if not self.stack:
            self.console.print(_hint("nothing to go back to."))
            return
        self.focus = self.stack.pop()
        self._show_focus()

    def handle(self, raw: str) -> bool:
        """Fuehre einen Befehl aus; ``True`` beendet die Sitzung."""
        raw = raw.strip()
        if not raw:
            return False
        verb, _, arg = raw.partition(" ")
        verb = verb.lower()
        if verb in ("quit", "q", "exit"):
            return True
        if verb in ("help", "?", "h"):
            self.console.print(_intro(self.world, self.seed))
        elif verb in ("why",):
            self.why(arg)
        elif verb in ("who", "life"):
            self.who(arg)
        elif verb in ("event", "e", "into", "zoom", "z"):  # ein Event fokussieren/anzoomen
            self.event(arg)
        elif verb in ("then", "next", "folgen"):
            self.then(arg)
        elif verb in ("back", "b"):
            self.back()
        elif verb.lstrip("#").isdigit():  # bare id ⇒ zoom into that event
            self.event(raw)
        else:
            self.console.print(_hint(f"unknown command: {raw!r} — try 'help'."))
        return False


def _demo_script(world: World, log: EventLog) -> list[str]:
    """Eine kurze, deterministische Beispiel-Sitzung fuer den Headless-/Pipe-Modus.

    Waehlt die groesste Polity mit einem verzeichneten Rueckschlag, verfolgt ihren
    Kollaps, zoomt in dessen erste Ursache und liest zuletzt ihre Biographie — genau
    der Ablauf „Warum ist Polity X zerfallen?" samt Hineinzoomen.
    """
    ranked = sorted(
        world.polities.values(), key=lambda p: (len(p.territory), -p.id), reverse=True
    )
    target = next((p for p in ranked if finde_kollaps(log, p.id) is not None), None)
    if target is None:
        return ["who 1"] if world.polities else ["help"]
    script = [f"why {target.name}"]
    collapse = finde_kollaps(log, target.id)
    if collapse is not None:
        causes = sorted(log.get(collapse).causes)
        if causes:
            script.append(f"into {causes[0]}")  # in die erste Ursache hineinzoomen
    script.append(f"who {target.name}")
    return script


def explore(
    world: World,
    log: EventLog,
    cfg: Config,
    *,
    seed: int = 0,
    console: Console | None = None,
    commands: Sequence[str] | None = None,
) -> None:
    """Interaktive Erkundung des Kausalgraphen — read-only, rein ableitend (§5/§7).

    Mit TTY: eine Eingabeaufforderung nimmt ``ID``/``Name`` und rendert Biographie
    oder Warum-Baum; von einer Ursache laesst sich weiter hineinzoomen. Ohne TTY
    (oder wenn ``commands`` gesetzt sind) laeuft eine feste Befehlsfolge ab —
    deterministisch und testbar. ``cfg`` bleibt aus Signatur-Konsistenz erhalten.
    """
    _ = cfg  # die Erkundung leitet alles aus dem Log ab; keine Config noetig
    console = console or Console()
    explorer = _Explorer(world, log, console, seed=seed)
    console.print(_intro(world, seed))

    script = commands if commands is not None else (
        None if console.is_terminal else _demo_script(world, log)
    )
    if script is not None:  # nicht-interaktiv: die Beispiel-Sitzung abspielen
        for raw in script:
            console.print(Text(f"› {raw}", style=f"bold {P.foam}"))  # Prompt-Echo  # noqa: RUF001
            if explorer.handle(raw):
                break
        return

    while True:  # pragma: no cover - interaktive Schleife (nur echtes TTY)
        try:
            raw = Prompt.ask(Text("›", style=f"bold {P.foam}"), console=console)  # noqa: RUF001
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if explorer.handle(raw):
            break
