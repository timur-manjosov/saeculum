"""static — der statische Chronik-Renderer (Default-Modus).

Nimmt die **chronicle-Ausgabe** (strukturierte Narration + Welt-Bilanz) und setzt
sie mit ``rich`` als schoen gegliederte Terminal-Ausgabe: eine ruhige Kopfzeile,
Zeitalter als grosse Abschnitte (Regeln mit Namen), darunter die farbcodierten
Ereigniszeilen, unter Wendepunkten eine eingerueckte, dezente **Warum-Kette** samt
dominanter Faktoren, und am Ende eine kompakte Welt-Bilanz als Panel.

Strikt **read-only** ueber Welt und Log; kein RNG, keine Simulationslogik. Optik
aus einer Quelle: Glyphen/Akzente aus ``visual``, Farbtoene aus der Rosé-Pine-Moon-
``palette``. Teilt alle Bausteine mit der Live-Ansicht (``components``).
"""

from __future__ import annotations

from rich.console import Console
from rich.text import Text

from worldsim.chronicle import (
    chronik_strukturiert,
    dominante_faktoren,
    erzaehle,
    weltbilanz,
)
from worldsim.config import Config
from worldsim.events import EventKind, EventLog
from worldsim.models import World
from worldsim.presentation.components import (
    bilanz_tafel,
    ereignis_text,
    faktoren_text,
    kausal_zeile,
    zeitalter_regel,
)
from worldsim.presentation.palette import ROSE_PINE_MOON as P

__all__ = ["render_chronik"]


def _masthead(seed: int, span: int, cfg: Config) -> Text:
    """Die Kopfzeile: Titel plus die Reproduktions-Kennung (Save = Seed)."""
    head = Text()
    head.append("History Machine", style=f"bold {P.text}")
    head.append(" — seed ", style=P.muted)
    head.append(str(seed), style=f"bold {P.foam}")
    head.append(f", {span} years", style=P.muted)
    head.append(f"   ·   config v{cfg.config_version}", style=P.overlay)
    return head


def _wendepunkt_details(world: World, log: EventLog, event_id: int, console: Console) -> None:
    """Die dezente Begruendung eines Wendepunkts: dominante Faktoren + Warum-Kette.

    Eingerueckt unter das Ereignis; macht den Kausalgraphen genau dort sichtbar,
    wo Geschichte kippt — ohne die Chronik zu ueberladen.
    """
    event = log.get(event_id)
    faktoren = dominante_faktoren(event)
    if faktoren:
        console.print(faktoren_text(faktoren))
    for cause_id in sorted(event.causes):
        console.print(kausal_zeile(erzaehle(world, log, log.get(cause_id))))


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

    console.print(_masthead(seed, span, cfg))

    for age in chronik_strukturiert(world, log, cfg):
        console.print()
        console.print(zeitalter_regel(age.name, age.start_year))
        for eintrag in age.eintraege:
            console.print(ereignis_text(eintrag.kind, eintrag.text))
            if eintrag.kind == EventKind.WENDEPUNKT:
                _wendepunkt_details(world, log, eintrag.event_id, console)

    console.print()
    console.print(bilanz_tafel(weltbilanz(world, log)))
