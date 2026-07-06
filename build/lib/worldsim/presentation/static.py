"""static — der statische Chronik-Renderer (Default-Modus).

Nimmt die **chronicle-Ausgabe** (strukturierte Narration + Welt-Bilanz) und setzt
sie mit ``rich`` als schoen gegliederte Terminal-Ausgabe: Titel, Zeitalter-
Ueberschriften als Trenner, lesbare Ereigniszeilen, am Ende eine kompakte
Welt-Zusammenfassung. Strikt **read-only** ueber Welt und Log; kein RNG, keine
Simulationslogik. Teilt die Ereignis-/Ueberschrift-/Bilanz-Bausteine mit der
Live-Ansicht (``components``).
"""

from __future__ import annotations

from rich.console import Console
from rich.text import Text

from worldsim.chronicle import chronik_strukturiert, weltbilanz
from worldsim.config import Config
from worldsim.events import EventLog
from worldsim.models import World
from worldsim.presentation.components import bilanz_tafel, ereignis_text, zeitalter_regel

__all__ = ["render_chronik"]


def render_chronik(
    world: World,
    log: EventLog,
    cfg: Config,
    *,
    seed: int = 0,
    years: int | None = None,
    console: Console | None = None,
) -> None:
    """Drucke die gesamte Chronik schoen gegliedert (Zeitalter, Eintraege, Bilanz).

    ``seed``/``years`` erscheinen im Titel (Save = Seed: die Welt laesst sich durch
    Teilen des Seeds reproduzieren). Ohne ``console`` wird nach ``stdout`` gerendert
    (auf einer Pipe druckt ``rich`` schlichten Text — die Chronik bleibt lesbar).
    """
    console = console or Console()
    span = world.year + 1 if years is None else years

    console.print(
        Text(f"History Machine — seed {seed}, {span} years", style="bold"),
        Text(f"config v{cfg.config_version}", style="dim"),
        sep="   ",
    )

    for age in chronik_strukturiert(world, log, cfg):
        console.print()
        console.print(zeitalter_regel(age.name, age.start_year))
        for eintrag in age.eintraege:
            console.print(ereignis_text(eintrag.kind, eintrag.text))

    console.print()
    console.print(bilanz_tafel(weltbilanz(world, log)))
