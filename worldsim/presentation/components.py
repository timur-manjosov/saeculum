"""components — gemeinsame rich-Bausteine fuer statische und Live-Ansicht.

Damit ``static`` (die schoen gesetzte Gesamt-Chronik) und ``watch`` (das
Live-Dashboard) **dieselben** Bausteine benutzen, liegen hier die geteilten
Renderables: die stilisierte Ereigniszeile, die (eingerueckte, dezente) Warum-
Notiz mit ihren dominanten Faktoren, die Zeitalter-Ueberschrift und die
Welt-Bilanztafel.

Zwei Quellen speisen die Optik — beide **zentral**:
- die Glyphen/Akzente je Ereignisart aus ``visual.stil_fuer`` (kontrolliertes
  Vokabular),
- die Farbtoene aus ``palette.ROSE_PINE_MOON`` (Rosé Pine Moon).
So traegt Farbe Bedeutung, nicht Dekoration. Read-only: die Bausteine rendern
Chronicle-Daten, sie berechnen keine Geschichte.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence

from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from worldsim.chronicle import Weltbilanz
from worldsim.events import EventKind
from worldsim.presentation.palette import ROSE_PINE_MOON as P
from worldsim.presentation.visual import stil_fuer

__all__ = [
    "bilanz_tafel",
    "ereignis_text",
    "faktoren_text",
    "feed_tafel",
    "kausal_zeile",
    "zeitalter_regel",
]


def ereignis_text(kind: EventKind, text: str) -> Text:
    """Eine erzaehlte Chronik-Zeile: farbige Glyphe + gedimmtes Jahr + Narration.

    Glyphe und Akzent stammen aus der gemeinsamen Optik-Tabelle (``stil_fuer``);
    das fuehrende ``Year N:`` wird gedimmt, damit die Aussage traegt. Ereignisse
    mit ``flash`` (Katastrophe, Wendepunkt) werden **fett** gesetzt — der hellste,
    schwerste Moment der Zeile.
    """
    color, glyph, flash = stil_fuer(kind)
    body_style = "bold" if flash else None
    line = Text()
    line.append(f"{glyph} ", style=f"bold {color}" if flash else color)
    prefix, sep, rest = text.partition(": ")
    if sep:
        line.append(prefix + sep + " ", style=P.muted)  # "Year N:" gedimmt
        line.append(rest, style=body_style)
    else:  # pragma: no cover - jede Narration beginnt mit "Year N: "
        line.append(text, style=body_style)
    return line


def faktoren_text(faktoren: Sequence[tuple[str, float]]) -> Text:
    """Die dominanten Faktoren eines Ereignisses, eingerueckt und subtil: ``label: gewicht``.

    Macht die Begruendung sichtbar (die Faktoren SIND die Begruendung), ohne die
    Zeile zu ueberladen: Label gedimmt, Gewicht als leises Fettgewicht.
    """
    line = Text("      ")  # Einrueckung unter das Ereignis
    for i, (label, weight) in enumerate(faktoren):
        if i:
            line.append("   ·   ", style=P.overlay)
        line.append(f"{label}: ", style=P.muted)
        line.append(f"{weight:+.1f}", style=f"bold {P.subtle}")
    return line


def kausal_zeile(text: str) -> Text:
    """Eine eingerueckte, dezente Ursachenzeile einer Warum-Kette (``↳ …``)."""
    line = Text("      ↳ ", style=P.muted)
    line.append(text, style=P.subtle)
    return line


def feed_tafel(feed: deque[tuple[EventKind, str]], *, title: str = "recent events") -> Panel:
    """Das Panel der juengsten Ereignisse — eine Zeile je Event, geteilte Optik.

    Derselbe Baustein traegt den streamenden Feed der Live-Ansicht (``watch``) und
    das Ereignis-Panel des Zeitraffers (``replay``): gleiche Glyphen, gleiche
    Akzente (``ereignis_text``), gleiche Rahmenfarbe aus der Palette.
    """
    text = Text()
    for i, (kind, line) in enumerate(feed):
        if i:
            text.append("\n")
        text.append_text(ereignis_text(kind, line))
    if not feed:
        text.append("…", style=P.muted)
    return Panel(text, title=title, title_align="left", border_style=P.muted)


def zeitalter_regel(name: str, start_year: int) -> Rule:
    """Eine Zeitalter-Ueberschrift: heller Name auf gedaempfter Linie (grosser Abschnitt)."""
    title = Text()
    title.append(name, style=f"bold {P.text}")
    title.append(f"   ·   from year {start_year}", style=P.muted)
    return Rule(title, style=P.muted, characters="─")


def bilanz_tafel(bilanz: Weltbilanz) -> Panel:
    """Die kompakte Welt-Zusammenfassung am Ende (Ueberlebende, groesste Macht, Figuren)."""
    grid = Table.grid(padding=(0, 3))
    grid.add_column(style=P.subtle, justify="right")  # Etiketten
    grid.add_column()  # Werte

    grid.add_row(
        "survived",
        Text.assemble(
            (str(bilanz.nationen), f"bold {P.text}"), (" nations   ", P.muted),
            (str(bilanz.glauben), f"bold {P.text}"), (" faiths   ", P.muted),
            (str(bilanz.zeitalter), f"bold {P.text}"), (" ages", P.muted),
        ),
    )
    grid.add_row(
        "greatest realm",
        Text.assemble(
            (bilanz.groesste_nation, f"bold {P.pine}"),
            (f"   {bilanz.groesstes_territorium} regions · "
             f"{bilanz.groesste_bevoelkerung} people", P.muted),
        ),
    )
    grid.add_row("dominant creed", Text(bilanz.groesster_glaube, style=f"bold {P.iris}"))
    grid.add_row(
        "history",
        Text.assemble(
            (str(bilanz.wendepunkte), f"bold {P.text}"), (" turning points   ", P.muted),
            (str(bilanz.katastrophen), f"bold {P.rose}"), (" disasters   ", P.muted),
            (str(bilanz.ereignisse), f"bold {P.text}"), (" events", P.muted),
        ),
    )

    if bilanz.figuren:
        figures = Text()
        for i, fig in enumerate(bilanz.figuren):
            if i:
                figures.append("\n")
            figures.append("♔ ", style=P.iris)
            figures.append(f"{fig.ruler} of {fig.nation}", style=f"bold {P.text}")
            figures.append(f"   — crowned in year {fig.year}", style=P.muted)
        grid.add_row("formative figures", figures)

    return Panel(
        grid,
        title=Text("the world at the end", style=f"bold {P.text}"),
        title_align="left",
        border_style=P.muted,
        padding=(1, 2),
        expand=False,
    )
