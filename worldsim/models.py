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
    "GoalKind",
    "Identity",
    "NationTraits",
    "Polity",
    "Region",
    "Relation",
    "Ruler",
    "Settlement",
    "Stocks",
    "Stratum",
    "StratumKind",
    "Tension",
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
class Identity:
    """Eine diskrete Identitaets-/Glaubensgemeinschaft (Phase 4).

    Bewusst **EIN** Mechanismus (nicht Religion/Kultur/Ideologie getrennt): eine
    Nation traegt genau eine ``identity_id``. Gleiche Identitaet stiftet Affinitaet
    (Buendnis leichter), verschiedene stiftet Reibung (Krieg leichter). Ein
    Schisma spaltet eine Identitaet in eine neue ``id`` — vorher gleiche Nationen
    haben danach Reibung. ``parent`` verweist auf die Ursprungs-Identitaet.

    Wie Herrscher bleiben Identitaeten dauerhaft im Register, damit die Chronik
    sie namentlich aufloesen kann; der Name ist reines Flavour (das Verhalten
    haengt an der ``id``, nicht am Namen).
    """

    id: EntityId
    name: str = ""
    parent: EntityId | None = None


@dataclass(frozen=True)
class Stocks:
    """Drei konkrete, handelbare Bestaende einer Nation (Stock-and-Flow).

    ``getreide`` ernaehrt die Bevoelkerung (schlecht lagerbar), ``gold`` ist der
    fiskalische Schatz (finanziert Expansion, zahlt spaeter Sold), ``eisen`` deckt
    Waffen/Werkzeuge. Genau drei *behavioral* unterschiedliche Ressourcen statt
    vieler kosmetischer Varianten (Reichtum vor Menge).

    ``frozen``: ein Bestand ist reiner Wert; die Nation als Container bleibt mutabel
    und schreibt ihn per ``dataclasses.replace`` fort — keine In-place-Mutation, aber
    auch keine tiefe Kopie (drei Floats, bei ~10 Nationen ohne Overhead).
    """

    getreide: float = 0.0
    eisen: float = 0.0
    gold: float = 0.0


class StratumKind(StrEnum):
    """Die drei behavioral unterschiedlichen Schichten einer Nation.

    ARBEITER erzeugen Getreide und stellen Rekruten; SOLDAT traegt die abgeleitete
    Schlagkraft; ELITE regiert und haelt einen ueberproportionalen Anteil am
    Wohlstand. Genau drei Schichten (Reichtum vor Menge).
    """

    ARBEITER = "arbeiter"
    SOLDAT = "soldat"
    ELITE = "elite"


@dataclass(frozen=True)
class Stratum:
    """Eine sozio-oekonomische Schicht als reiner, unveraenderlicher Wert.

    ``size`` ist kontinuierlich (Float vermeidet Quantisierungs-Zyklen). ``grievance``
    ist akkumulierter Unmut, der bei Getreidemangel und ungleichem ``wealth_share``
    steigt und sonst langsam zerfaellt (die Groesse baut sich auf — Entladung erst
    spaeter). ``wealth_share`` ist der Anteil am Wohlstand, den die Schicht haelt;
    die Anteile aller Schichten einer Nation summieren zu ~1.
    """

    kind: StratumKind
    size: float = 0.0
    grievance: float = 0.0
    wealth_share: float = 0.0


@dataclass(frozen=True)
class Tension:
    """Der Spannungszustand einer Nation: vier benannte Druecke (Aenderung 6).

    Reiner Wert, je Tick von ``systems.spannung`` neu berechnet — dieselben vier
    Zahlen, die als ``Factor``-Liste an einer Entladung haengen (die Faktoren SIND
    die Begruendung, es gibt keine zweite Rechnung). Bereits **gewichtet**, damit
    ihre Summe der Spannungs-Score und die groesste von ihnen die dominante
    Komponente ist (sie waehlt die Art der Entladung).

    Angelehnt an die Strukturell-Demografische Theorie: Volksdruck (Verelendung),
    Elitendruck (Eliten-Ueberproduktion), Fiskaldruck (Staatsfinanzen), Aussendruck
    (Abhaengigkeit und Einkreisung).
    """

    volk: float = 0.0
    elite: float = 0.0
    fiskal: float = 0.0
    aussen: float = 0.0


class GoalKind(StrEnum):
    """Das feste, kleine Zielmenue einer Nation (Aenderung 4).

    Jede Nation waehlt pro Tick **gierig** das Ziel mit der hoechsten aktuellen
    Utility (argmax, ein Schritt, myopisch) — keine Suche, keine Vorausplanung.
    Die **Deklarationsreihenfolge ist bindend**: sie bricht Gleichstaende im
    argmax (danach die ``EntityId`` des Ziel-Objekts). ``UEBERLEBEN`` steht
    zuerst — es ist die stets erfuellbare Option "abwarten", gegen die sich jede
    Handlung erst lohnen muss.
    """

    UEBERLEBEN = "ueberleben"
    WACHSEN = "wachsen"
    RESSOURCE_SICHERN = "ressource_sichern"
    GROLL_VERGELTEN = "groll_vergelten"
    VERBUENDEN = "verbuenden"


@dataclass(frozen=True)
class Relation:
    """Das historische Gedaechtnis als gerichtete Kante a -> b (reiner Wert).

    ``favor`` ist akkumuliertes Wohlwollen (+) bzw. Groll (-) und zerfaellt ueber
    Jahrzehnte Richtung 0 (Vergebung). Buendnis und Feindschaft sind KEINE
    gespeicherten Flags: sie werden pro Tick aus ``favor`` abgeleitet (siehe
    ``systems.allied``/``systems.hostile``). ``dependency`` (Anteil des Bedarfs
    von a, den b's Lieferungen decken, 0..1) fuellt der Handel (Aenderung 5): sie
    steigt auf die aktuelle Angewiesenheit und zerfaellt, sobald die Lieferung
    ausbleibt. Eine Kante existiert, solange ``favor`` ODER ``dependency`` von 0
    verschieden ist (sonst ist sie neutral und entfaellt — sparse Matrix).
    """

    favor: float = 0.0
    dependency: float = 0.0


@dataclass
class Region:
    """Geographie als Verhaltenstraeger ("Feld"). Keine Tile-Mikrosimulation.

    Knoten im abstrakten Adjazenzgraphen; ``nachbarn`` sind die Grenzkanten.
    ``owner`` ist die beanspruchende Polity (``None`` = freies Feld).
    """

    id: EntityId
    name: str = ""
    food_capacity: float = 0.0
    # Aenderung 5: Eisen ist "oft nicht lokal" (Konzept §2.2) — nur ein Teil der
    # Regionen traegt ein Vorkommen. Eisenarme Nationen muessen Eisen importieren
    # (Handelsabhaengigkeit), notfalls vom Rivalen — die Wurzel des Handelskriegs.
    iron_rich: bool = False
    # Aenderung 7: die Geologie des Feldes. ``seismicity`` (0..1, aus dem Worldgen)
    # ist die Rate, mit der sich Gesteinsspannung aufbaut — 0 heisst aseismisch.
    # ``strain`` ist die aufgestaute Spannung selbst; erreicht sie 1, bricht sie
    # als Erdbeben. Damit ist der letzte exogene Schock kein Wurf mehr, sondern
    # dieselbe Figur wie alles andere in dieser Welt: Aufbau bis zur Schwelle,
    # dann Entladung. Der Zufall steckt in der Geologie (Anfangsbedingung), nicht
    # im Ereignispfad.
    seismicity: float = 0.0
    strain: float = 0.0
    # Adjazenz/Distanz fuer Handel & Krieg = Grenzen.
    nachbarn: tuple[EntityId, ...] = ()
    owner: EntityId | None = None
    # Rein geografische Lage in [0,1)^2 fuer die Karten-Darstellung (aus dem
    # worldgen-Sub-Strom, Teil des Determinismus-Vertrags). Die Simulation liest
    # sie NICHT — Verhalten kommt aus Adjazenz und Traits, nie aus der Lage.
    coord: tuple[float, float] = (0.0, 0.0)


@dataclass
class Settlement:
    """Eine Siedlung in einer Region, Mitglied einer Polity."""

    id: EntityId
    region: EntityId | None = None
    polity: EntityId | None = None
    population: int = 0
    unrest: float = 0.0


@dataclass
class Polity:
    """Herrschaftsverband ("Nation"), Knoten-Eigner im Territorialgraphen.

    Phase-1-Vereinfachung: Demografie und Bestaende liegen auf Nations-Ebene
    (``strata``, ``stocks``), nicht auf Siedlungs-Ebene. Die
    Settlement-Schicht (und ``members``/``leader``) bleibt fuer spaetere Phasen
    reserviert.
    """

    id: EntityId
    name: str = ""
    capital: EntityId | None = None
    # Beanspruchte Regionen (Felder) = das Territorium der Nation.
    territory: tuple[EntityId, ...] = ()
    founded_year: int = 0
    # Innere Struktur: die Schichten (Arbeiter/Soldat/Elite). Die Gesamt-
    # bevoelkerung ist die Summe der ``size`` — kein eigenes Feld.
    strata: tuple[Stratum, ...] = ()
    # Hoechststand der Bevoelkerung: damit jeder Meilenstein nur einmal feuert.
    peak_population: int = 0
    # Die drei handelbaren Bestaende (Getreide/Eisen/Gold).
    stocks: Stocks = field(default_factory=Stocks)
    # Transientes Tick-Signal: Getreidedefizit nach Verbrauch (>0 ⇒ Hunger).
    # Reine Daten, von consumption gesetzt und von Demografie/Groll gelesen.
    food_deficit: float = 0.0

    # --- Phase 2: Charakter, Diplomatie, Konflikt --------------------------
    traits: NationTraits = field(default_factory=NationTraits)
    # Beziehungen (favor/Groll) leben als gerichtete Kanten in ``World.relations``;
    # Buendnis/Feindschaft werden pro Tick daraus abgeleitet — keine Flags hier.
    # Persistenter Groll/Grenzreibung pro anderer Nation (akkumuliert ueber Jahre).
    friction: dict[EntityId, float] = field(default_factory=dict)
    # Transient: pro Tick neu berechnete Furcht vor jeder anderen Nation.
    fear: dict[EntityId, float] = field(default_factory=dict)
    # Jahr des letzten Krieges gegen jede andere Nation (Kriegsmuedigkeit).
    last_war: dict[EntityId, int] = field(default_factory=dict)

    # --- Aenderung 4: utility-basierte Zielwahl ----------------------------
    # Das im laufenden Tick per argmax gewaehlte Ziel (``None`` bis zum ersten
    # Tick einer Nation). Es traegt die Wahl in Systeme, die frueher im Tick
    # laufen als die Zielwahl selbst (siehe ``systems._recruit``).
    goal: GoalKind | None = None

    # --- Aenderung 6: der Spannungszustand ---------------------------------
    # Transient: die vier je Tick neu berechneten Druecke (siehe ``systems.spannung``).
    # Ueberschreitet ihre Summe die Schwelle, entlaedt sich die Spannung; die
    # groesste Komponente waehlt die Art. ``goals`` liest den Aussendruck, weil
    # dessen Entladung nach aussen geht (Krieg) statt nach innen.
    tension: Tension = field(default_factory=Tension)
    # Jahr der letzten Entladung. Danach ist die Nation eine Weile refraktaer: eine
    # eben erschuetterte Gesellschaft bricht nicht im naechsten Jahr erneut, der Druck
    # muss sich erst wieder aufbauen. Das ist es, was aus dem Auf und Ab einen ZYKLUS
    # macht statt eines Dauerflackerns (vgl. ``last_war``).
    last_crisis: int = -10_000

    # --- Phase 3: Herrscher ------------------------------------------------
    # Aktueller Herrscher: Verweis (id) in ``World.rulers``. Im laufenden Tick
    # zeigt ``leader`` immer auf einen lebenden Herrscher (Sukzession erfolgt im
    # selben Tick wie der Tod).
    leader: EntityId | None = None

    # --- Phase 4: Identitaet -----------------------------------------------
    # Diskrete Identitaets-/Glaubenszugehoerigkeit: Verweis (id) in
    # ``World.identities``. Gleiche id ⇒ Affinitaet, verschiedene id ⇒ Reibung.
    identity_id: EntityId | None = None

    # --- Phase 5: Technologie ----------------------------------------------
    # Erreichte Tech-Stufe (0 = Anfang). Hebt Produktion und Schlagkraft. Das
    # ``knowledge`` (Forschungsfortschritt, kein handelbarer Bestand) akkumuliert
    # und schaltet an Schwellen Zeitalter frei. ``peak_territory`` speist die
    # Kollaps-Erkennung (Phase 5).
    tech_level: int = 0
    knowledge: float = 0.0
    peak_territory: int = 0

    # --- fuer spaetere Phasen reserviert -----------------------------------
    # Legitimitaet ist KEIN gespeicherter Bestand: sie wird bei Bedarf aus dem
    # Zustand abgeleitet (Funktion der bewaeltigten Spannungen), konsistent mit
    # "Schlagkraft ist abgeleitet" (siehe systems._power).
    members: tuple[EntityId, ...] = ()


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
    # Der Seed, aus dem diese Welt entstand ("Speichern = Seed"). Reine Daten, keine
    # RNG-Instanz. Er dient allein dem KOSMETISCHEN Strom: der Name einer neu
    # entstehenden Nation/Identitaet wird daraus abgeleitet und beruehrt damit den
    # semantischen Strom nicht (Determinismus-Vertrag: Flavour darf nie beeinflussen,
    # WELCHE Fakten entstehen — vorher zog ``make_name`` aus dem Entscheidungsstrom).
    seed: int = 0
    regions: dict[EntityId, Region] = field(default_factory=dict)
    settlements: dict[EntityId, Settlement] = field(default_factory=dict)
    polities: dict[EntityId, Polity] = field(default_factory=dict)
    figures: dict[EntityId, Figure] = field(default_factory=dict)
    # Herrscher-Register (Phase 3). Tote Herrscher bleiben erhalten, damit die
    # Chronik sie namentlich aufloesen kann; ``alive`` unterscheidet sie.
    rulers: dict[EntityId, Ruler] = field(default_factory=dict)
    # Identitaets-Register (Phase 4). Durch Schisma entstandene Identitaeten
    # kommen hinzu; alle bleiben fuer die Chronik namentlich aufloesbar.
    identities: dict[EntityId, Identity] = field(default_factory=dict)

    # --- Aenderung 3: das historische Gedaechtnis ---------------------------
    # Gerichtete Beziehungs-Kanten (a_id, b_id) -> Relation, sparse: eine
    # fehlende Kante ist neutral (favor 0). Im Entscheidungspfad wird
    # ausschliesslich nach (a_id, b_id) sortiert iteriert (Determinismus).
    relations: dict[tuple[EntityId, EntityId], Relation] = field(default_factory=dict)

    # --- Phase 5: Wendepunkt-Erkennung & Zeitalter -------------------------
    # Erinnerte Trend-Zustaende, gegen die der ``epoch``-Waechter je Tick
    # vergleicht (reine Daten). Ein Bruch ⇒ WENDEPUNKT-Meta-Event.
    hegemon: EntityId | None = None  # aktuell staerkstes Reich
    dominant_faith: EntityId | None = None  # territorial groesste Identitaet
    industrial: bool = False  # ob die Industrielle Revolution schon begann
    # Laufendes Zeitalter: Name und fortlaufender Index (Zeitalter werden durch
    # Wendepunkte begrenzt und benannt).
    age_name: str = ""
    age_index: int = 0

    # Deterministischer ID-Zaehler.
    next_id: EntityId = 0
