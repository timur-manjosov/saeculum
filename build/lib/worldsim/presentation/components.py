"""components — gemeinsame rich-Bausteine fuer statische und Live-Ansicht.

Damit ``static`` (die schoen gesetzte Gesamt-Chronik) und ``watch`` (das
Live-Dashboard) **dieselben** Bausteine benutzen, liegen hier die geteilten
Renderables: die stilisierte Ereigniszeile, die Zeitalter-Ueberschrift und die
Welt-Bilanztafel. Optik-Quelle ist ausschliesslich ``visual.stil_fuer`` — Farben
werden hier bewusst zurueckhaltend eingesetzt (das finale Theme folgt spaeter).

Read-only: die Bausteine rendern Chronicle-Daten, sie berechnen keine Geschichte.
"""

from __future__ import annotations

from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from worldsim.chronicle import Weltbilanz
from worldsim.events import EventKind
from worldsim.presentation.visual import stil_fuer

__all__ = ["bilanz_tafel", "ereignis_text", "zeitalter_regel"]


def ereignis_text(kind: EventKind, text: str) -> Text:
    """Eine erzaehlte Chronik-Zeile: farbige Glyphe + gedimmtes Jahr + Narration.

    Glyphe und Farbe stammen aus der gemeinsamen Optik-Tabelle (``stil_fuer``);
    das fuehrende ``Year N:`` wird gedimmt, damit die Aussage traegt.
    """
    color, glyph, _flash = stil_fuer(kind)
    line = Text()
    line.append(f"{glyph} ", style=color)
    prefix, sep, rest = text.partition(": ")
    if sep:
        line.append(prefix + sep, style="dim")
        line.append(rest)
    else:  # pragma: no cover - jede Narration beginnt mit "Year N: "
        line.append(text)
    return line


def zeitalter_regel(name: str, start_year: int) -> Rule:
    """Eine Zeitalter-Ueberschrift als Trenner mit Titel."""
    return Rule(f"{name} · from year {start_year}", style="bold", characters="─")


def bilanz_tafel(bilanz: Weltbilanz) -> Panel:
    """Die kompakte Welt-Zusammenfassung am Ende (Ueberlebende, groesste Macht, Figuren)."""
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold")
    grid.add_column()
    grid.add_row(
        "survived",
        f"{bilanz.nationen} nations · {bilanz.glauben} faiths · {bilanz.zeitalter} ages",
    )
    grid.add_row(
        "greatest realm",
        f"{bilanz.groesste_nation} "
        f"({bilanz.groesstes_territorium} regions, {bilanz.groesste_bevoelkerung} people)",
    )
    grid.add_row("dominant creed", bilanz.groesster_glaube)
    grid.add_row(
        "history",
        f"{bilanz.wendepunkte} turning points · {bilanz.katastrophen} disasters · "
        f"{bilanz.ereignisse} events",
    )

    if bilanz.figuren:
        figures = Text()
        for i, fig in enumerate(bilanz.figuren):
            if i:
                figures.append("\n")
            figures.append("· ", style="magenta")
            figures.append(f"{fig.ruler} of {fig.nation}", style="bold")
            figures.append(f" — crowned in year {fig.year}", style="dim")
        grid.add_row("formative figures", figures)

    return Panel(grid, title="the world at the end", border_style="grey50", expand=False)
