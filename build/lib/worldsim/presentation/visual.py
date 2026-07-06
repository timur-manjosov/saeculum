"""visual — die zentrale Ereignis→Visuell-Abbildung (Aufgabe 3).

Eine **einzige** reine Funktion bildet ein ``Event`` auf seinen visuellen Effekt
ab (``event_to_visual``). Sie treibt **beides**: das Live-Rendering *und* das
Replay — dieselbe Abbildung, dieselbe visuelle Historie. Damit ist ein Replay per
Konstruktion konsistent mit der Live-Ansicht.

Diese Datei ist bewusst **abhaengigkeitsfrei** (nur Stdlib + Kern-``events``):
sie ist reine Ableitung aus dem Log, in Tests ohne ``rich`` pruefbar. Farben und
Glyphen sind reine Daten (Strings), die die Renderer interpretieren.

Ausserdem lebt hier der ``ViewState``-Reducer: er rekonstruiert den beobachtbaren
Weltzustand (Gebietsbesitz, Bevoelkerung, Glaube) **allein aus dem Event-Log**,
indem er die ``effects`` in Emissionsreihenfolge anwendet. Kein Zugriff auf die
Simulation, keine Re-Simulation — reines Nachspielen des Logs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from worldsim.events import Event, EventKind, EventLog
from worldsim.models import EntityId

__all__ = [
    "ViewState",
    "VisualEffect",
    "VisualKind",
    "event_to_visual",
    "stil_fuer",
    "visuelle_historie",
]


class VisualKind(StrEnum):
    """Die visuelle Kategorie eines Ereignisses (steuert Farbe/Glyphe/Blitz)."""

    STADT = "STADT"  # Stadt/Nation gesetzt
    GRENZE = "GRENZE"  # Grenze verschiebt sich (Expansion/Eroberung)
    KRIEG = "KRIEG"  # Krieg (rot)
    SCHLACHT = "SCHLACHT"  # Schlacht
    BUENDNIS = "BUENDNIS"  # Handels-/Buendnislinie gezogen
    BRUCH = "BRUCH"  # Linie zerreisst
    KATASTROPHE = "KATASTROPHE"  # Katastrophe blitzt
    HUNGER = "HUNGER"  # Hungersnot
    GLAUBE = "GLAUBE"  # Konversion/Schisma
    FORSCHUNG = "FORSCHUNG"  # Innovation
    WENDEPUNKT = "WENDEPUNKT"  # Wendepunkt
    HERRSCHER = "HERRSCHER"  # Tod/Sukzession
    WACHSTUM = "WACHSTUM"  # Bevoelkerungs-Meilenstein
    SPANNUNG = "SPANNUNG"  # Grenzreibung
    NEUTRAL = "NEUTRAL"  # Rest


@dataclass(frozen=True)
class VisualEffect:
    """Der visuelle Effekt genau eines Events — reine Daten (keine Pixel).

    ``color``/``glyph`` sind ``rich``-kompatible Strings, die die Renderer deuten.
    ``regions`` nennt die betroffenen Felder (fuer die Karte); ``flash`` markiert
    ein aufblitzendes Ereignis (Katastrophe/Wendepunkt).
    """

    event_id: int
    year: int
    kind: VisualKind
    subjects: tuple[EntityId, ...]
    regions: tuple[EntityId, ...]
    color: str
    glyph: str
    flash: bool = False


# Zentrale Tabelle: visuelle Kategorie ⇒ (Farbe, Glyphe, Blitz). Ein Ort, an dem
# das Aussehen aller Ereignisarten festgelegt ist.
_STYLE: dict[VisualKind, tuple[str, str, bool]] = {
    VisualKind.STADT: ("bright_green", "⌂", False),
    VisualKind.GRENZE: ("green", "▸", False),
    VisualKind.KRIEG: ("bright_red", "⚔", False),
    VisualKind.SCHLACHT: ("red", "×", False),  # noqa: RUF001
    VisualKind.BUENDNIS: ("cyan", "═", False),
    VisualKind.BRUCH: ("bright_magenta", "╫", False),
    VisualKind.KATASTROPHE: ("bright_yellow", "✷", True),
    VisualKind.HUNGER: ("yellow", "◦", False),
    VisualKind.GLAUBE: ("blue", "†", False),
    VisualKind.FORSCHUNG: ("bright_cyan", "✦", False),
    VisualKind.WENDEPUNKT: ("bright_white", "★", True),
    VisualKind.HERRSCHER: ("magenta", "♔", False),
    VisualKind.WACHSTUM: ("green", "↑", False),
    VisualKind.SPANNUNG: ("yellow", "≁", False),
    VisualKind.NEUTRAL: ("white", "·", False),
}

_KIND_TO_VISUAL: dict[EventKind, VisualKind] = {
    EventKind.GRUENDUNG: VisualKind.STADT,
    EventKind.EXPANSION: VisualKind.GRENZE,
    EventKind.SCHLACHT: VisualKind.SCHLACHT,
    EventKind.KRIEG: VisualKind.KRIEG,
    EventKind.BUENDNIS: VisualKind.BUENDNIS,
    EventKind.BUENDNIS_BRUCH: VisualKind.BRUCH,
    EventKind.PEST: VisualKind.KATASTROPHE,
    EventKind.ERDBEBEN: VisualKind.KATASTROPHE,
    EventKind.DUERRE: VisualKind.KATASTROPHE,
    EventKind.HUNGERSNOT: VisualKind.HUNGER,
    EventKind.KONVERSION: VisualKind.GLAUBE,
    EventKind.SCHISMA: VisualKind.GLAUBE,
    EventKind.INNOVATION: VisualKind.FORSCHUNG,
    EventKind.WENDEPUNKT: VisualKind.WENDEPUNKT,
    EventKind.TOD_FIGUR: VisualKind.HERRSCHER,
    EventKind.SUKZESSION: VisualKind.HERRSCHER,
    EventKind.ABSPALTUNG: VisualKind.GRENZE,
    EventKind.BEVOELKERUNG_MEILENSTEIN: VisualKind.WACHSTUM,
    EventKind.GRENZREIBUNG: VisualKind.SPANNUNG,
}


def _regions_of(event: Event) -> tuple[EntityId, ...]:
    """Die von einem Event betroffenen Felder — aus den ``effects`` gelesen.

    ``capital``: ``entity`` ist die Nation, ``after`` das Feld. ``owner``:
    ``entity`` ist das Feld. So kennt die Karte die neu gesetzten/gewechselten
    Territorien ohne Zugriff auf den Weltzustand.
    """
    regions: list[EntityId] = []
    for eff in event.effects:
        if eff.field == "capital" and isinstance(eff.after, int):
            regions.append(eff.after)
        elif eff.field == "owner":
            regions.append(eff.entity)
    return tuple(regions)


def stil_fuer(kind: EventKind) -> tuple[str, str, bool]:
    """Der visuelle Stil ``(farbe, glyphe, blitz)`` einer Ereignisart.

    Die gemeinsame Optik-Quelle: der statische Chronik-Renderer und die
    Live-/Replay-Ansicht leiten ihre Glyphen und Farben aus **derselben** Tabelle
    ab — allein aus ``kind``, ohne ein volles Event zu brauchen.
    """
    return _STYLE[_KIND_TO_VISUAL.get(kind, VisualKind.NEUTRAL)]


def event_to_visual(event: Event) -> VisualEffect:
    """Bilde ein Event auf seinen visuellen Effekt ab — die zentrale Abbildung.

    Rein und deterministisch (Funktion allein des Events). Treibt Live UND Replay,
    wodurch beide dieselbe visuelle Historie erzeugen.
    """
    kind = _KIND_TO_VISUAL.get(event.kind, VisualKind.NEUTRAL)
    color, glyph, flash = _STYLE[kind]
    return VisualEffect(
        event_id=event.id,
        year=event.year,
        kind=kind,
        subjects=event.subjects,
        regions=_regions_of(event),
        color=color,
        glyph=glyph,
        flash=flash,
    )


def visuelle_historie(log: EventLog) -> tuple[VisualEffect, ...]:
    """Die vollstaendige visuelle Historie: jedes Event als ``VisualEffect``.

    In Emissionsreihenfolge (= chronologisch, stabil). Genau diese Sequenz spielen
    sowohl Live-Ansicht als auch Replay ab — sie ist die eine Quelle der Optik.
    """
    return tuple(event_to_visual(event) for event in log)


@dataclass
class ViewState:
    """Aus dem Log rekonstruierter, beobachtbarer Weltzustand (read-only Ableitung).

    Wird durch ``apply`` je Event fortgeschrieben — ausschliesslich aus den
    ``effects``, also **ohne** Re-Simulation. Nach dem Abspielen des ganzen Logs
    stimmt ``owner`` exakt mit dem Endzustand der Welt ueberein (verifiziert): das
    Replay reproduziert die territoriale Historie konsistent.
    """

    year: int = 0
    # Feld → besitzende Nation (der territoriale Kern der Karte).
    owner: dict[EntityId, EntityId] = field(default_factory=dict)
    # Nation → zuletzt aus dem Log bekannte Bevoelkerung (Snapshots aus effects).
    population: dict[EntityId, int] = field(default_factory=dict)
    # Nation → aktuelle Identitaet/Glaube (aus Konversions-/Gruendungs-effects).
    faith: dict[EntityId, EntityId] = field(default_factory=dict)
    # Gegruendete/abgespaltene Nationen in Erscheinungsreihenfolge.
    nations: list[EntityId] = field(default_factory=list)

    def territory_counts(self) -> dict[EntityId, int]:
        """Gebietsgroesse je Nation (= Macht-Proxy) aus dem Besitz abgeleitet."""
        counts: dict[EntityId, int] = {}
        for pid in self.owner.values():
            counts[pid] = counts.get(pid, 0) + 1
        return counts

    def apply(self, event: Event) -> None:
        """Schreibe den beobachtbaren Zustand um genau ein Event fort."""
        self.year = event.year
        if event.kind == EventKind.GRUENDUNG and event.subjects:
            self.nations.append(event.subjects[0])
        if event.kind == EventKind.ABSPALTUNG and len(event.subjects) > 1:
            self.nations.append(event.subjects[1])
        for eff in event.effects:
            if eff.field == "capital" and isinstance(eff.after, int):
                self.owner[eff.after] = eff.entity
            elif eff.field == "owner":
                self.owner[eff.entity] = eff.after  # type: ignore[assignment]
            elif eff.field == "population" and isinstance(eff.after, int):
                self.population[eff.entity] = eff.after
            elif eff.field == "identity_id" and isinstance(eff.after, int):
                self.faith[eff.entity] = eff.after
