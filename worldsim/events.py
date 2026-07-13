"""events — das kanonische, kausale Ereignis-Modell (Rueckgrat des Projekts).

Schema verbindlich aus ``docs/architektur-history-machine.md`` §3-4. Alle Typen
sind reine, **immutable** Daten (``frozen``, Tuples statt Listen). Das Event
traegt **nur strukturierte Daten** — keinen erzaehlten Text. Sprache entsteht
erst in ``chronicle``/``presentation``.

Kernprinzip: Die ``factors`` SIND die Begruendung. Dieselbe Faktorliste, mit der
eine Wahl berechnet wurde, wird auf dem Event gespeichert.

Systeme bauen **kein** fertiges ``Event`` — sie emittieren einen ``EventDraft``.
Die ``EventId`` vergibt ausschliesslich der ``EventLog`` beim Einhaengen
(monoton, in Emissionsreihenfolge), womit Laeufe mit gleichem
``(seed, years, config_version)`` identische IDs erhalten.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum

from worldsim.models import EntityId

__all__ = [
    "Decision",
    "Effect",
    "Event",
    "EventDraft",
    "EventId",
    "EventKind",
    "EventLog",
    "Factor",
    "FactorLabel",
]

# Vom EventLog in Emissionsreihenfolge vergeben (monoton, ab 0).
EventId = int


class EventKind(StrEnum):
    """Kontrolliertes, kleines Vokabular der Ereignisarten (§8).

    Erweiterbar, aber nicht wuchernd. Neue Arten werden hier zentral ergaenzt.
    """

    # Phase 1 aktiv:
    GRUENDUNG = "GRUENDUNG"
    EXPANSION = "EXPANSION"
    BEVOELKERUNG_MEILENSTEIN = "BEVOELKERUNG_MEILENSTEIN"
    HUNGERSNOT = "HUNGERSNOT"
    # Phase 2 aktiv (Konflikt & Diplomatie):
    GRENZREIBUNG = "GRENZREIBUNG"
    BUENDNIS = "BUENDNIS"
    BUENDNIS_BRUCH = "BUENDNIS_BRUCH"
    KRIEG = "KRIEG"
    SCHLACHT = "SCHLACHT"
    # Phase 3 aktiv (Herrscher):
    TOD_FIGUR = "TOD_FIGUR"
    SUKZESSION = "SUKZESSION"
    ABSPALTUNG = "ABSPALTUNG"
    # Phase 4 aktiv (Identitaet/Glaube):
    KONVERSION = "KONVERSION"
    SCHISMA = "SCHISMA"
    # Phase 5 aktiv (Schocks, Technologie, Wendepunkte). Aenderung 7: von den drei
    # gewuerfelten Schocks bleibt EINER — das Erdbeben, der einzige, der keine soziale
    # Ursache haben KANN. Pest und Duerre sind fort: was sie taten (Bevoelkerung toeten,
    # Vorraete vernichten), tut die Welt jetzt aus sich selbst — Hungersnot aus
    # Uebervoelkerung, Mobilmachung und verlorenem Land.
    ERDBEBEN = "ERDBEBEN"
    INNOVATION = "INNOVATION"
    WENDEPUNKT = "WENDEPUNKT"
    # Aenderung 6 aktiv (Entladungen des Spannungszustands). Die dominante
    # Komponente der Spannung waehlt die Art: Volksdruck ⇒ AUFSTAND, Elitendruck
    # ⇒ PUTSCH oder ABSPALTUNG (oben), Fiskaldruck ⇒ BANKROTT, extrem/zusammen-
    # gesetzt ⇒ KOLLAPS. Der Aussendruck entlaedt sich nach aussen und braucht
    # keine eigene Art: sein Ereignis ist der KRIEG (oben).
    AUFSTAND = "AUFSTAND"
    PUTSCH = "PUTSCH"
    BANKROTT = "BANKROTT"
    KOLLAPS = "KOLLAPS"
    # Fuer spaetere Phasen reserviert:
    WERK = "WERK"
    MIGRATION = "MIGRATION"
    GEBURT_FIGUR = "GEBURT_FIGUR"


class FactorLabel(StrEnum):
    """Zentrales, kontrolliertes Vokabular der Faktor-Labels (§8).

    Faktoren werden nie ad hoc im System erfunden, sondern hier zentral
    gefuehrt, damit Warum-Ketten und Statistiken ueber Laeufe konsistent sind.
    """

    # Begruendungs-Faktoren (warum eine Aenderung geschah):
    WELTGENERIERUNG = "Weltgenerierung"
    NAHRUNGSUEBERSCHUSS = "Nahrungsueberschuss"
    WOHLSTAND = "Wohlstand"
    BEVOELKERUNGSWACHSTUM = "Bevoelkerungswachstum"
    NAHRUNGSDEFIZIT = "Nahrungsdefizit"
    # Phase 2: Expansion, Diplomatie und Krieg.
    EXPANSIONSDRANG = "Expansionsdrang"
    MILITAERVORTEIL = "Militaervorteil"
    AGGRESSION = "Aggression"
    GRENZREIBUNG = "Grenzreibung"
    RESSOURCENDRUCK = "Ressourcendruck"
    ZIEL_SCHWAECHE = "Schwaeche des Ziels"
    MISSTRAUEN = "Misstrauen"
    FURCHT = "Furcht"
    VORSICHT = "Vorsicht"
    VERTRAUEN = "Vertrauen"
    GEMEINSAMER_FEIND = "Gemeinsamer Feind"
    DIPLOMATIE = "Diplomatie"
    EHRE = "Ehre"
    ZUFALL = "Zufall"
    # Phase 3: Herrscher, Sukzession, Fragmentierung.
    ALTER = "Alter"
    LEGITIMITAET = "Legitimitaet"
    ERBFOLGE = "Erbfolge"
    THRONSTREIT = "Thronstreit"
    UEBERDEHNUNG = "Ueberdehnung"
    PERSOENLICHE_RIVALITAET = "Persoenliche Rivalitaet"
    # Phase 4: Identitaet, Affinitaet, Konversion, Schisma.
    GLAUBENSAFFINITAET = "Glaubensaffinitaet"
    GLAUBENSGRABEN = "Glaubensgraben"
    DOMINANZ = "Dominanz"
    GLAUBENSTREUE = "Glaubenstreue"
    GLAUBENSGROESSE = "Glaubensgroesse"
    GLAUBENSEIFER = "Glaubenseifer"
    # Aenderung 4: utility-basierte Zielwahl (Faktoren des Zielmenues).
    BEHARRUNG = "Beharrung"
    VOLKSGROLL = "Volksgroll"
    EISENBEDARF = "Eisenbedarf"
    BEUTE = "Beute"
    # Aenderung 5: Handel und Abhaengigkeit (Krieg aus Handelsverflechtung).
    HANDELSABHAENGIGKEIT = "Handelsabhaengigkeit"
    # Aenderung 6: die vier Komponenten des Spannungszustands. Ihre Summe IST die
    # Spannung, ihre groesste waehlt die Art der Entladung — die Faktorliste einer
    # Entladung ist exakt diese Rechnung (Strukturell-Demografische Theorie).
    VOLKSDRUCK = "Volksdruck"
    ELITENDRUCK = "Elitendruck"
    FISKALDRUCK = "Fiskaldruck"
    AUSSENDRUCK = "Aussendruck"
    # Phase 5: Schocks, Technologie, Wendepunkte.
    ERDBEBEN = "Erdbeben"
    # Aenderung 7: die Ursache des Bebens. Auch der letzte exogene Schock wird nicht
    # mehr gewuerfelt — er ist die Entladung einer Spannung, die sich ueber Jahrhunderte
    # im Gestein aufbaut. Der Zufall sitzt in der Geologie (Worldgen), nicht im Jahr.
    ERDSPANNUNG = "Erdspannung"
    FORSCHUNG = "Forschung"
    MACHTWECHSEL = "Machtwechsel"
    GLAUBENSWANDEL = "Glaubenswandel"
    BUENDNISZERFALL = "Buendniszerfall"
    GEBIETSKOLLAPS = "Gebietskollaps"
    # Wichtigkeits-Faktoren (warum ein Event erzaehlenswert ist, §6 Rekursion):
    NEUE_NATION = "Neue Nation"
    GEBIETSGEWINN = "Gebietsgewinn"
    BEVOELKERUNGSGROESSE = "Bevoelkerungsgroesse"
    VERLUST_AN_LEBEN = "Verlust an Leben"
    KRIEGSAUSBRUCH = "Kriegsausbruch"
    GEBIETSWECHSEL = "Gebietswechsel"
    BUENDNISWANDEL = "Buendniswandel"
    HERRSCHERTOD = "Herrschertod"
    THRONFOLGE = "Thronfolge"
    FRAGMENTIERUNG = "Fragmentierung"
    BEKEHRUNG = "Bekehrung"
    GLAUBENSSPALTUNG = "Glaubensspaltung"
    INNERE_KRISE = "Innere Krise"
    KATASTROPHE = "Katastrophe"
    TECHNOLOGISCHER_DURCHBRUCH = "Technologischer Durchbruch"
    WENDEPUNKT = "Wendepunkt"
    ZENTRALITAET = "Kausale Zentralitaet"


@dataclass(frozen=True)
class Factor:
    """Ein benannter Beitrag zu einer Entscheidung/Magnitude.

    Vorzeichen = Richtung, Betrag = Beitrag. Die Summe der ``weight`` ueber alle
    Faktoren ergibt den Entscheidungs-Score. ``label`` stammt aus dem zentralen
    Vokabular (§8).
    """

    label: str
    weight: float


@dataclass(frozen=True)
class Effect:
    """Strukturiertes Zustandsdelta: ermoeglicht „was hat sich geaendert"."""

    entity: EntityId
    field: str
    before: object
    after: object


@dataclass(frozen=True)
class EventDraft:
    """Von einem System emittiert — wie ``Event``, aber ohne ``id``.

    ``causes`` duerfen nur **bereits existierende, fruehere** EventIds nennen.
    """

    year: int
    kind: EventKind
    subjects: tuple[EntityId, ...] = ()
    factors: tuple[Factor, ...] = ()
    causes: tuple[EventId, ...] = ()
    effects: tuple[Effect, ...] = ()


@dataclass(frozen=True)
class Event:
    """Ein eingehaengtes, unveraenderliches Ereignis mit stabiler ``id``."""

    id: EventId
    year: int
    kind: EventKind
    subjects: tuple[EntityId, ...] = ()
    factors: tuple[Factor, ...] = ()
    causes: tuple[EventId, ...] = ()
    effects: tuple[Effect, ...] = ()


class EventLog:
    """Append-only, in-memory, geordneter Ereignis-Log = der Kausalgraph.

    Die einzige veraenderliche Struktur im Kern, und sie waechst nur per
    ``append``/``extend``. Deterministisch aufgebaute Indizes nach ``subject``,
    ``kind`` und ``year`` ermoeglichen reine Abfragen (siehe ``chronicle``).
    """

    __slots__ = ("_by_kind", "_by_subject", "_by_year", "_events")

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._by_subject: dict[EntityId, list[EventId]] = {}
        self._by_kind: dict[EventKind, list[EventId]] = {}
        self._by_year: dict[int, list[EventId]] = {}

    def append(self, draft: EventDraft) -> EventId:
        """Haenge einen Draft ein, vergib die monotone ``id``, gib sie zurueck.

        Validiert die Kausal-Invariante: ``causes`` muessen real und **frueher**
        sein (keine haengenden, keine Vorwaertsreferenzen).
        """
        event_id: EventId = len(self._events)
        for cause in draft.causes:
            if not 0 <= cause < event_id:
                raise ValueError(
                    f"causes muessen frueher/existierend sein: {cause} "
                    f"unzulaessig fuer Event {event_id}"
                )

        event = Event(
            id=event_id,
            year=draft.year,
            kind=draft.kind,
            subjects=draft.subjects,
            factors=draft.factors,
            causes=draft.causes,
            effects=draft.effects,
        )
        self._events.append(event)

        # Indizes deterministisch fortschreiben.
        for subject in event.subjects:
            self._by_subject.setdefault(subject, []).append(event_id)
        self._by_kind.setdefault(event.kind, []).append(event_id)
        self._by_year.setdefault(event.year, []).append(event_id)
        return event_id

    def extend(self, drafts: list[EventDraft]) -> list[EventId]:
        """Haenge mehrere Drafts in Reihenfolge ein."""
        return [self.append(draft) for draft in drafts]

    # --- reine Abfragen (read-only) ----------------------------------------

    def get(self, event_id: EventId) -> Event:
        return self._events[event_id]

    def by_subject(self, subject: EntityId) -> tuple[Event, ...]:
        return tuple(self._events[i] for i in self._by_subject.get(subject, ()))

    def by_kind(self, kind: EventKind) -> tuple[Event, ...]:
        return tuple(self._events[i] for i in self._by_kind.get(kind, ()))

    def by_year(self, year: int) -> tuple[Event, ...]:
        return tuple(self._events[i] for i in self._by_year.get(year, ()))

    def __iter__(self) -> Iterator[Event]:
        """Iteration in Emissionsreihenfolge."""
        return iter(self._events)

    def __len__(self) -> int:
        return len(self._events)


@dataclass
class Decision:
    """Akkumuliert benannte ``(label, gewicht)``-Beitraege fuer EINE Entscheidung.

    Das verbindliche Muster fuer **jede** KI-Entscheidung (§2, welt-sim §5):
    Beitraege werden gesammelt, ihre Summe gebildet und gegen eine Schwelle
    entschieden. Die exakt gesammelten ``factors``/``causes`` werden **unveraendert**
    an das resultierende Event gehaengt — die Faktoren SIND die Begruendung, es
    gibt keine zweite, nachtraegliche Erklaerung.

    Beitraege werden in **Aufrufreihenfolge** akkumuliert (Float-Reproduzierbarkeit).
    Ein Faktor mit Gewicht 0 wird verworfen (er hat das Ergebnis nicht beeinflusst,
    darf also nicht in der Begruendung stehen); seine Ursachen werden dann auch
    nicht zitiert. Ursachen werden beim Export dedupliziert und stabil sortiert.
    """

    factors: list[Factor] = field(default_factory=list)
    causes: list[EventId] = field(default_factory=list)

    def add(
        self, label: str, weight: float, *, causes: Iterable[EventId] = ()
    ) -> None:
        """Trage einen benannten Beitrag bei; zitiere optional ausloesende Events."""
        if weight == 0.0:
            return
        self.factors.append(Factor(str(label), float(weight)))
        self.causes.extend(causes)

    @property
    def score(self) -> float:
        """Summe der Beitraege in Aufrufreihenfolge (definierte Akkumulation)."""
        total = 0.0
        for factor in self.factors:
            total += factor.weight
        return total

    def passes(self, threshold: float) -> bool:
        """Entscheide: liegt die Faktorsumme auf/ueber der Schwelle?"""
        return self.score >= threshold

    def as_factors(self) -> tuple[Factor, ...]:
        """Die gesammelte Faktorliste fuer das Event-Feld ``factors``."""
        return tuple(self.factors)

    def as_causes(self) -> tuple[EventId, ...]:
        """Die zitierten Ursachen, dedupliziert und stabil sortiert."""
        return tuple(sorted(set(self.causes)))
