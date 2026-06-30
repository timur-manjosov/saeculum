"""models — Kern-Datenmodelle als reine Daten (dataclasses).

Keine Logik in den Modellen. Verhalten lebt in ``systems`` (reine Funktionen).
Die Entitaeten folgen ``docs/architektur-welt-simulation.md`` §4:
Region / Settlement / Polity / Figure, zusammengehalten von ``World``.

``World`` enthaelt **keinen** RNG und **keinen** EventLog — beide haelt und
durchreicht der Driver. Phase 1 nutzt aktiv ``Region`` (Feld) und ``Polity``
(Nation); ``Settlement``/``Figure`` bleiben Geruest fuer spaetere Phasen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "AccessionMode",
    "EntityId",
    "Figure",
    "NationTraits",
    "Polity",
    "Region",
    "Ruler",
    "Settlement",
    "Stockpile",
    "Traits",
    "World",
]

# Stabiler, deterministisch vom ``World.next_id``-Zaehler vergebener Wert.
EntityId = int


@dataclass(frozen=True)
class Traits:
    """Behavioral wirksame Eigenschaften einer Figur (4-6, Phase 0: Defaults).

    Reserviert fuer Figuren (Phase 3). Nationen tragen ``NationTraits``.
    """

    ehrgeiz: float = 0.0
    vorsicht: float = 0.0
    grausamkeit: float = 0.0
    tradition: float = 0.0
    pragmatismus: float = 0.0


@dataclass(frozen=True)
class NationTraits:
    """Behavioral wirksame Charakterzuege einer Nation (Werte 0..1).

    Deterministisch aus dem Seed gezogen. ``fear`` ist bewusst KEIN Trait,
    sondern ein pro Tick berechneter Zustand (siehe ``Polity.fear``), den
    ``caution`` moduliert. Jeder Trait stellt in mindestens zwei Systemen ein
    Gewicht (``innovation`` ist bis zur Tech-Phase ruhend).
    """

    aggression: float = 0.0
    expansion: float = 0.0
    innovation: float = 0.0
    honor: float = 0.0
    diplomacy: float = 0.0
    caution: float = 0.0


class AccessionMode(StrEnum):
    """Wie ein Herrscher an die Macht kam — bestimmt die Anfangs-Legitimitaet."""

    INHERITED = "inherited"
    ELECTED = "elected"
    USURPED = "usurped"


@dataclass
class Ruler:
    """Ein Herrscher als **duenne Trait-Ueberlagerung** ueber einer Nation (Phase 3).

    Bewusst kein RPG-Charakter: keine Skills, kein Inventar, keine
    Einzelbeziehungen. Nur (a) ``trait_deltas`` — Modifikatoren auf eine Teilmenge
    der ``NationTraits``, die die effektiven Traits der Nation verschieben; (b)
    Lebensspanne/Alter fuer den Generationswechsel; (c) Machtantritt + Legitimitaet.

    Herrscher tragen eine eigene ``EntityId`` und bleiben nach dem Tod im Register
    (``alive=False``), damit die Chronik sie weiterhin namentlich nennen kann.
    """

    id: EntityId
    name: str = ""
    # Modifikatoren auf die Basis-Traits (innovation ruht ⇒ Delta stets 0).
    trait_deltas: NationTraits = field(default_factory=NationTraits)
    age: int = 0
    lifespan: int = 60
    accession: AccessionMode = AccessionMode.INHERITED
    legitimacy: float = 0.0
    alive: bool = True
    # Phase-5-Flag: grosser Trait-Sprung beim Machtwechsel ⇒ potenzieller Wendepunkt.
    turning_point: bool = False


@dataclass
class Stockpile:
    """Lagerbestaende einer Siedlung. 3-6 behavioral unterschiedliche Typen."""

    nahrung: float = 0.0
    wohlstand: float = 0.0
    wissen: float = 0.0


@dataclass
class Region:
    """Geographie als Verhaltenstraeger ("Feld"). Keine Tile-Mikrosimulation.

    Knoten im abstrakten Adjazenzgraphen; ``nachbarn`` sind die Grenzkanten.
    ``owner`` ist die beanspruchende Polity (``None`` = freies Feld).
    """

    id: EntityId
    name: str = ""
    food_capacity: float = 0.0
    # Adjazenz/Distanz fuer Handel & Krieg = Grenzen.
    nachbarn: tuple[EntityId, ...] = ()
    owner: EntityId | None = None


@dataclass
class Settlement:
    """Eine Siedlung in einer Region, Mitglied einer Polity."""

    id: EntityId
    region: EntityId | None = None
    polity: EntityId | None = None
    population: int = 0
    stockpiles: Stockpile = field(default_factory=Stockpile)
    unrest: float = 0.0


@dataclass
class Polity:
    """Herrschaftsverband ("Nation"), Knoten-Eigner im Territorialgraphen.

    Phase-1-Vereinfachung: Demografie und Lager liegen auf Nations-Ebene
    (``population``, ``stockpiles``), nicht auf Siedlungs-Ebene. Die
    Settlement-Schicht (und ``members``/``leader``) bleibt fuer spaetere Phasen
    reserviert.
    """

    id: EntityId
    name: str = ""
    capital: EntityId | None = None
    # Beanspruchte Regionen (Felder) = das Territorium der Nation.
    territory: tuple[EntityId, ...] = ()
    founded_year: int = 0
    population: int = 0
    # Hoechststand der Bevoelkerung: damit jeder Meilenstein nur einmal feuert.
    peak_population: int = 0
    stockpiles: Stockpile = field(default_factory=Stockpile)
    # Transientes Tick-Signal: Nahrungsdefizit nach Verbrauch (>0 ⇒ Hunger).
    # Reine Daten, von consumption gesetzt und von population gelesen.
    food_deficit: float = 0.0

    # --- Phase 2: Charakter, Diplomatie, Konflikt --------------------------
    traits: NationTraits = field(default_factory=NationTraits)
    # Trust pro anderer Nation (iteriertes Spiel, Bereich etwa -1..+1).
    relations: dict[EntityId, float] = field(default_factory=dict)
    # Aktuelle Verbuendete (stabil sortiert).
    allies: tuple[EntityId, ...] = ()
    # Persistenter Groll/Grenzreibung pro anderer Nation (akkumuliert ueber Jahre).
    friction: dict[EntityId, float] = field(default_factory=dict)
    # Transient: pro Tick neu berechnete Furcht vor jeder anderen Nation.
    fear: dict[EntityId, float] = field(default_factory=dict)
    # Jahr des letzten Krieges gegen jede andere Nation (Kriegsmuedigkeit).
    last_war: dict[EntityId, int] = field(default_factory=dict)

    # --- Phase 3: Herrscher ------------------------------------------------
    # Aktueller Herrscher: Verweis (id) in ``World.rulers``. Im laufenden Tick
    # zeigt ``leader`` immer auf einen lebenden Herrscher (Sukzession erfolgt im
    # selben Tick wie der Tod).
    leader: EntityId | None = None

    # --- fuer spaetere Phasen reserviert -----------------------------------
    members: tuple[EntityId, ...] = ()
    legitimacy: float = 0.0


@dataclass
class Figure:
    """Eine notable Figur mit Traits und Zugehoerigkeit."""

    id: EntityId
    name: str = ""
    traits: Traits = field(default_factory=Traits)
    role: str = ""
    affiliation: EntityId | None = None
    age: int = 0
    alive: bool = True


@dataclass
class World:
    """Container und einzige Wurzel des Zustands.

    Reine, serialisierbare Daten (wird aber nie persistiert: Seed = Save).
    Enthaelt bewusst weder RNG noch EventLog.
    """

    year: int = 0
    regions: dict[EntityId, Region] = field(default_factory=dict)
    settlements: dict[EntityId, Settlement] = field(default_factory=dict)
    polities: dict[EntityId, Polity] = field(default_factory=dict)
    figures: dict[EntityId, Figure] = field(default_factory=dict)
    # Herrscher-Register (Phase 3). Tote Herrscher bleiben erhalten, damit die
    # Chronik sie namentlich aufloesen kann; ``alive`` unterscheidet sie.
    rulers: dict[EntityId, Ruler] = field(default_factory=dict)
    # Deterministischer ID-Zaehler.
    next_id: EntityId = 0
