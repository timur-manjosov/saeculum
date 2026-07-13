"""chronicle — reine, read-only Ableitung lesbarer Geschichte aus dem Graphen.

Headless (erzeugt Text/Daten, keine Pixel) und **ohne RNG**: deterministisch.
Diese Schicht mutiert nichts.

Zwei Verantwortlichkeiten:
- **Wichtigkeit** (§6): Was in der Chronik auftaucht, entscheidet ein
  Wichtigkeits-Score — selbst eine **Summe benannter Faktoren** (Rekursion des
  Kernprinzips). Liegt der Score unter ``cfg.chronicle_min_importance``, faellt
  das Event aus der Zusammenfassung.
- **Narration**: deterministisches Templating je ``EventKind`` aus ``effects``
  und aufgeloesten Subjekt-Namen. Der erzaehlte Text existiert nur hier, nie im
  Event.

Daneben die Graph-Operationen (§5) als reine Abfragen.
"""

from __future__ import annotations

from dataclasses import dataclass

from worldsim.config import Config
from worldsim.events import Effect, Event, EventId, EventKind, EventLog, Factor, FactorLabel
from worldsim.models import EntityId, World
from worldsim.systems import bevoelkerung

__all__ = [
    "ChronikEintrag",
    "PraegendeFigur",
    "Weltbilanz",
    "Zeitalter",
    "annalen",
    "chronik",
    "chronik_mit_zeitaltern",
    "chronik_strukturiert",
    "dominante_faktoren",
    "epochen",
    "erklaere",
    "erzaehle",
    "folgen",
    "lebenslauf",
    "warum",
    "weltbilanz",
    "wichtigkeit",
    "zentralitaet",
]


# --- Graph-Abfragen (§5) ---------------------------------------------------

def annalen(log: EventLog, year: int) -> tuple[Event, ...]:
    """Jahresauszug: alle Events eines Jahres in Emissionsreihenfolge."""
    return log.by_year(year)


def lebenslauf(log: EventLog, entity: EntityId) -> tuple[Event, ...]:
    """Biographie/Polity-Geschichte: alle Events mit ``entity`` in ``subjects``."""
    return log.by_subject(entity)


def folgen(log: EventLog, event_id: EventId) -> tuple[Event, ...]:
    """Vorwaertskante: Events, die ``event_id`` als Ursache fuehren."""
    return tuple(e for e in log if event_id in e.causes)


def dominante_faktoren(event: Event, limit: int = 3) -> tuple[tuple[str, float], ...]:
    """Die Faktoren mit groesstem Betrag — die Hauptbegruendung eines Events."""
    ranked = sorted(event.factors, key=lambda f: abs(f.weight), reverse=True)
    return tuple((f.label, f.weight) for f in ranked[:limit])


def warum(log: EventLog, event_id: EventId) -> list[tuple[Event, tuple[tuple[str, float], ...]]]:
    """Warum-Kette: transitive Verfolgung der ``causes`` ab ``event_id``.

    Liefert je erreichtem Event seine dominanten Faktoren. Deterministisch und
    zyklenfrei (``causes`` zeigen ausschliesslich auf fruehere Events). In
    Phase 1 sind ``causes`` noch leer; die Kette ist daher einelementig.
    """
    chain: list[tuple[Event, tuple[tuple[str, float], ...]]] = []
    seen: set[EventId] = set()
    frontier: list[EventId] = [event_id]
    while frontier:
        current = frontier.pop(0)
        if current in seen:
            continue
        seen.add(current)
        event = log.get(current)
        chain.append((event, dominante_faktoren(event)))
        # Stabil sortiert, damit die Kette reproduzierbar ist.
        frontier.extend(sorted(event.causes))
    return chain


# --- kausale Zentralitaet: nachgelagerte Reichweite im Graphen --------------

def zentralitaet(log: EventLog) -> dict[EventId, int]:
    """Zaehle je Event die im Kausalgraphen **erreichbaren Folgen** (Nachfahren).

    Reine Graph-Kennzahl: die transitive Vorwaerts-Reichweite (distinkte
    Nachfahren) misst, wie folgenreich ein Ereignis war. Da ``causes`` stets auf
    **fruehere** Events zeigen (id kleiner), werden die Knoten in absteigender id
    verarbeitet — jedes Kind ist dann schon ausgewertet (topologische Ordnung).
    """
    children: dict[EventId, list[EventId]] = {}
    for event in log:
        for cause in event.causes:
            children.setdefault(cause, []).append(event.id)

    descendants: dict[EventId, set[EventId]] = {}
    reach: dict[EventId, int] = {}
    for event in sorted(log, key=lambda e: e.id, reverse=True):
        seen: set[EventId] = set()
        for child in children.get(event.id, ()):
            seen.add(child)
            seen |= descendants.get(child, frozenset())
        descendants[event.id] = seen
        reach[event.id] = len(seen)
    return reach


# --- Wichtigkeit (§6): selbst eine Summe benannter Faktoren -----------------

def wichtigkeit(
    event: Event, reach: int = 0, weight: float = 0.0, cap: float = 0.0
) -> tuple[float, tuple[Factor, ...]]:
    """Berechne den Wichtigkeits-Score als Summe benannter Faktoren.

    Gibt ``(score, faktoren)`` zurueck — die Faktoren SIND die Begruendung, auch
    fuer die Auswahl, was Geschichte „wert" ist. ``reach`` ist die kausale
    Zentralitaet (Zahl erreichbarer Folgen); sie tritt als eigener, gedeckelter
    Faktor hinzu — hochzentrale Ereignisse praegen die Chronik (Rekursion des
    Kernprinzips auf die Auswahl selbst).
    """
    factors: tuple[Factor, ...]
    match event.kind:
        case EventKind.GRUENDUNG:
            factors = (Factor(FactorLabel.NEUE_NATION, 5.0),)
        case EventKind.EXPANSION:
            factors = (Factor(FactorLabel.GEBIETSGEWINN, 3.0),)
        case EventKind.BEVOELKERUNG_MEILENSTEIN:
            after = _population_after(event.effects)
            factors = (Factor(FactorLabel.BEVOELKERUNGSGROESSE, 2.0 + after / 3000.0),)
        case EventKind.HUNGERSNOT:
            deaths = _population_loss(event.effects)
            factors = (Factor(FactorLabel.VERLUST_AN_LEBEN, 0.5 + deaths / 50.0),)
        case EventKind.KRIEG:
            factors = (Factor(FactorLabel.KRIEGSAUSBRUCH, 4.0),)
        case EventKind.SCHLACHT:
            took_land = any(e.field == "owner" for e in event.effects)
            factors = (Factor(FactorLabel.GEBIETSWECHSEL, 3.5 if took_land else 2.0),)
        case EventKind.BUENDNIS:
            factors = (Factor(FactorLabel.BUENDNISWANDEL, 3.0),)
        case EventKind.BUENDNIS_BRUCH:
            factors = (Factor(FactorLabel.BUENDNISWANDEL, 2.5),)
        case EventKind.GRENZREIBUNG:
            factors = (Factor(FactorLabel.GRENZREIBUNG, 0.3),)
        case EventKind.TOD_FIGUR:
            factors = (Factor(FactorLabel.HERRSCHERTOD, 2.5),)
        case EventKind.SUKZESSION:
            # Ein als Wendepunkt markierter Wechsel wiegt schwerer.
            turning = any(e.field == "wendepunkt" for e in event.effects)
            factors = (Factor(FactorLabel.THRONFOLGE, 3.5 if turning else 2.5),)
        case EventKind.ABSPALTUNG:
            factors = (Factor(FactorLabel.FRAGMENTIERUNG, 4.5),)
        case EventKind.AUFSTAND:
            deaths = _population_loss(event.effects)
            factors = (Factor(FactorLabel.INNERE_KRISE, 3.5 + deaths / 60.0),)
        case EventKind.PUTSCH:
            factors = (Factor(FactorLabel.INNERE_KRISE, 3.5),)
        case EventKind.BANKROTT:
            factors = (Factor(FactorLabel.INNERE_KRISE, 3.0),)
        case EventKind.KOLLAPS:
            # Der Zerfall eines Reiches in Nachfolgestaaten: das groesste innere
            # Ereignis, das die Welt kennt.
            factors = (
                Factor(FactorLabel.INNERE_KRISE, 3.0),
                Factor(FactorLabel.FRAGMENTIERUNG, 5.0),
            )
        case EventKind.KONVERSION:
            factors = (Factor(FactorLabel.BEKEHRUNG, 3.0),)
        case EventKind.SCHISMA:
            factors = (Factor(FactorLabel.GLAUBENSSPALTUNG, 4.5),)
        case EventKind.ERDBEBEN:
            deaths = _population_loss(event.effects)
            factors = (Factor(FactorLabel.KATASTROPHE, 1.5 + deaths / 60.0),)
        case EventKind.INNOVATION:
            factors = (Factor(FactorLabel.TECHNOLOGISCHER_DURCHBRUCH, 3.0),)
        case EventKind.WENDEPUNKT:
            factors = (Factor(FactorLabel.WENDEPUNKT, 5.0),)
        case _:
            factors = ()
    if reach > 0 and weight > 0.0:
        factors = (*factors, Factor(FactorLabel.ZENTRALITAET, min(reach * weight, cap)))
    score = sum(f.weight for f in factors)
    return score, factors


# --- Narration: deterministisches Templating je EventKind ------------------

def chronik(world: World, log: EventLog, cfg: Config) -> list[str]:
    """Filtere nach Wichtigkeits-Schwelle und erzaehle die Events als Text.

    Reihenfolge: nach Jahr, dann Emissions-id (stabil). Beispielzeile:
    ``Year 35: Veldoria expanded into the eastern plains``.
    """
    reach = zentralitaet(log)
    lines: list[str] = []
    for event in sorted(log, key=lambda e: (e.year, e.id)):
        score, _ = wichtigkeit(
            event, reach.get(event.id, 0), cfg.centrality_weight, cfg.centrality_cap
        )
        if score < cfg.chronicle_min_importance:
            continue
        lines.append(_narrate(world, event, log))
    return lines


def epochen(world: World, log: EventLog) -> list[tuple[int, str]]:
    """Die benannten Zeitalter als ``(Startjahr, Name)`` — begrenzt durch Wendepunkte.

    Das erste Zeitalter ("the First Expansion") laeuft bis zum ersten
    zeitalter-definierenden Wendepunkt (Machtwechsel/industrieller Durchbruch).
    """
    ages: list[tuple[int, str]] = [(0, "the First Expansion")]
    for event in sorted(log, key=lambda e: (e.year, e.id)):
        if event.kind == EventKind.WENDEPUNKT and any(
            eff.field == "age" for eff in event.effects
        ):
            ages.append((event.year, _age_name_of(world, event)))
    return ages


def chronik_mit_zeitaltern(world: World, log: EventLog, cfg: Config) -> list[str]:
    """Wie ``chronik``, aber gegliedert in benannte Zeitalter (Ueberschriften).

    Ein zeitalter-definierender Wendepunkt eroeffnet einen neuen Abschnitt; die
    Wendepunkt-Zeile selbst bleibt als erster Eintrag des neuen Zeitalters stehen.
    """
    reach = zentralitaet(log)
    lines: list[str] = ["=== the First Expansion ==="]
    for event in sorted(log, key=lambda e: (e.year, e.id)):
        if event.kind == EventKind.WENDEPUNKT and any(
            eff.field == "age" for eff in event.effects
        ):
            lines.append("")
            lines.append(f"=== {_age_name_of(world, event)} (from year {event.year}) ===")
        score, _ = wichtigkeit(
            event, reach.get(event.id, 0), cfg.centrality_weight, cfg.centrality_cap
        )
        if score < cfg.chronicle_min_importance:
            continue
        lines.append(_narrate(world, event, log))
    return lines


# --- strukturierte Narration: Daten fuer den (rich-)Renderer -----------------

@dataclass(frozen=True)
class ChronikEintrag:
    """Ein erzaehlter Chronik-Eintrag als **reine Daten** (kein Rendering).

    Traegt Jahr, Ereignisart und den fertigen, deterministischen Narrationstext
    sowie die Event-``id`` (fuer Verweise/Warum-Ketten). Die Praesentation stylt
    daraus Zeilen, erfindet aber keinen Text.
    """

    year: int
    kind: EventKind
    event_id: EventId
    text: str


@dataclass(frozen=True)
class Zeitalter:
    """Ein benanntes Zeitalter mit seinen erzaehlenswerten Eintraegen."""

    name: str
    start_year: int
    eintraege: tuple[ChronikEintrag, ...]


def chronik_strukturiert(world: World, log: EventLog, cfg: Config) -> list[Zeitalter]:
    """Die Chronik als **strukturierte** Daten: Zeitalter → erzaehlte Eintraege.

    Dieselbe Wichtigkeits-Filterung und Zeitalter-Gliederung wie
    ``chronik_mit_zeitaltern``, aber als navigierbare Daten statt fertiger Zeilen —
    damit die Praesentation gliedern kann, ohne Strings zu zerlegen. Rein und
    deterministisch (kein RNG); der erzaehlte Text existiert nur hier.
    """
    reach = zentralitaet(log)
    ages: list[tuple[str, int, list[ChronikEintrag]]] = [("the First Expansion", 0, [])]
    for event in sorted(log, key=lambda e: (e.year, e.id)):
        if event.kind == EventKind.WENDEPUNKT and any(
            eff.field == "age" for eff in event.effects
        ):
            ages.append((_age_name_of(world, event), event.year, []))
        score, _ = wichtigkeit(
            event, reach.get(event.id, 0), cfg.centrality_weight, cfg.centrality_cap
        )
        if score < cfg.chronicle_min_importance:
            continue
        ages[-1][2].append(
            ChronikEintrag(
                year=event.year,
                kind=event.kind,
                event_id=event.id,
                text=_narrate(world, event, log),
            )
        )
    return [Zeitalter(name, start, tuple(entries)) for name, start, entries in ages]


# --- Welt-Zusammenfassung: wer ueberlebte, groesste Macht, praegende Figuren ---

@dataclass(frozen=True)
class PraegendeFigur:
    """Eine praegende Figur: ein Herrscher, dessen Machtantritt ein Wendepunkt war."""

    ruler: str
    nation: str
    year: int


@dataclass(frozen=True)
class Weltbilanz:
    """Kompakte, deterministische Schluss-Bilanz der Welt (reine Daten)."""

    jahre: int
    nationen: int
    glauben: int
    groesste_nation: str
    groesstes_territorium: int
    groesste_bevoelkerung: int
    groesster_glaube: str
    zeitalter: int
    wendepunkte: int
    katastrophen: int
    ereignisse: int
    figuren: tuple[PraegendeFigur, ...]


def weltbilanz(world: World, log: EventLog, *, max_figuren: int = 5) -> Weltbilanz:
    """Leite die Schluss-Bilanz deterministisch aus Welt + Log ab (kein RNG).

    Groesste Macht = groesstes Territorium (Gleichstand: mehr Bevoelkerung, dann
    kleinere id). Groesster Glaube = die von den meisten Nationen getragene
    Identitaet. Praegende Figuren = Herrscher, deren Sukzession als Wendepunkt
    markiert wurde (die letzten ``max_figuren`` chronologisch).
    """
    shocks = (EventKind.ERDBEBEN,)

    if world.polities:
        largest = max(
            world.polities.values(),
            key=lambda p: (len(p.territory), bevoelkerung(p), -p.id),
        )
        largest_name = largest.name
        largest_terr = len(largest.territory)
        largest_pop = bevoelkerung(largest)
    else:  # pragma: no cover - eine Welt hat immer Nationen
        largest_name, largest_terr, largest_pop = "—", 0, 0

    faith_counts: dict[EntityId, int] = {}
    for pol in world.polities.values():
        if pol.identity_id is not None:
            faith_counts[pol.identity_id] = faith_counts.get(pol.identity_id, 0) + 1
    if faith_counts:
        top_faith = max(faith_counts.items(), key=lambda kv: (kv[1], -kv[0]))[0]
        faith_name = _identity_name(world, top_faith)
    else:  # pragma: no cover
        faith_name = "—"

    figuren = [
        PraegendeFigur(
            ruler=_ruler_name(world, e.subjects[1]),
            nation=_nation_name(world, e.subjects[0]),
            year=e.year,
        )
        for e in sorted(log, key=lambda e: (e.year, e.id))
        if e.kind == EventKind.SUKZESSION
        and len(e.subjects) > 1
        and any(eff.field == "wendepunkt" for eff in e.effects)
    ]

    return Weltbilanz(
        jahre=world.year + 1,
        nationen=len(world.polities),
        glauben=len(world.identities),
        groesste_nation=largest_name,
        groesstes_territorium=largest_terr,
        groesste_bevoelkerung=largest_pop,
        groesster_glaube=faith_name,
        zeitalter=len(epochen(world, log)),
        wendepunkte=sum(1 for e in log if e.kind == EventKind.WENDEPUNKT),
        katastrophen=sum(1 for e in log if e.kind in shocks),
        ereignisse=len(log),
        figuren=tuple(figuren[-max_figuren:]),
    )


def erzaehle(world: World, log: EventLog, event: Event) -> str:
    """Oeffentliche, deterministische Ein-Zeilen-Narration eines Events.

    Die Praesentations-Schicht (read-only) nutzt dieselbe Templating-Logik wie die
    Chronik — Sprache entsteht ausschliesslich hier, nie im Event.
    """
    return _narrate(world, event, log)


def _narrate(world: World, event: Event, log: EventLog) -> str:
    """Eine erzaehlte Zeile aus ``kind`` + ``subjects`` + ``effects`` + ``factors``."""
    nation = _nation_name(world, event.subjects[0])
    match event.kind:
        case EventKind.GRUENDUNG:
            where = _region_name(world, _capital_region(event.effects))
            return f"Year {event.year}: {nation} was founded in {where}."
        case EventKind.EXPANSION:
            where = _region_name(world, event.subjects[1])
            return f"Year {event.year}: {nation} expanded into {where}."
        case EventKind.BEVOELKERUNG_MEILENSTEIN:
            after = _population_after(event.effects)
            return f"Year {event.year}: {nation} grew to {after} people."
        case EventKind.HUNGERSNOT:
            deaths = _population_loss(event.effects)
            return f"Year {event.year}: {nation} suffered a famine, losing {deaths} people."
        case EventKind.KRIEG:
            target = _nation_name(world, event.subjects[1])
            drivers = _format_top_factors(event)
            if _is_faith_war(event):
                verb = "declared a war of faith on"
            elif _is_trade_war(event):
                verb = "declared a trade war on"
            elif _is_pressure_war(event):
                # Aenderung 6: der Krieg IST die Entladung des Aussendrucks.
                verb = "sought escape from its mounting crisis in war on"
            else:
                verb = "declared war on"
            return (
                f"Year {event.year}: {nation} {verb} {target}, "
                f"driven by {drivers}."
            )
        case EventKind.SCHLACHT:
            loser = _nation_name(world, event.subjects[1])
            land = _transferred_region(event.effects)
            if land is not None:
                where = _region_name(world, land)
                return f"Year {event.year}: {nation} defeated {loser} and annexed {where}."
            return f"Year {event.year}: {nation} defeated {loser} in battle."
        case EventKind.BUENDNIS:
            partner = _nation_name(world, event.subjects[1])
            enemy = _nation_name(world, event.subjects[2]) if len(event.subjects) > 2 else "?"
            return f"Year {event.year}: {nation} and {partner} allied against {enemy}."
        case EventKind.BUENDNIS_BRUCH:
            partner = _nation_name(world, event.subjects[1])
            schisma = _schisma_cause(log, event)
            if schisma is not None:
                faith = _identity_name(world, schisma.subjects[2])
                return (
                    f"Year {event.year}: the schism of the {faith} faith shattered "
                    f"the alliance between {nation} and {partner}."
                )
            return f"Year {event.year}: the alliance between {nation} and {partner} collapsed."
        case EventKind.GRENZREIBUNG:
            other = _nation_name(world, event.subjects[1])
            return f"Year {event.year}: border tension rose between {nation} and {other}."
        case EventKind.TOD_FIGUR:
            name = _ruler_name(world, event.subjects[1])
            age = _ruler_age(world, event.subjects[1])
            return f"Year {event.year}: {name}, ruler of {nation}, died at age {age}."
        case EventKind.SUKZESSION:
            name = _ruler_name(world, event.subjects[1])
            mode = _accession_mode(event.effects)
            turning = any(e.field == "wendepunkt" for e in event.effects)
            line = f"Year {event.year}: {name} succeeded to the throne of {nation} ({mode})."
            return line + (" A turning point." if turning else "")
        case EventKind.ABSPALTUNG:
            breakaway = _nation_name(world, event.subjects[1])
            if _driven_by(event, FactorLabel.ELITENDRUCK):
                # Aenderung 6: die ueberzaehlige Elite nimmt sich ihren eigenen Staat.
                return (
                    f"Year {event.year}: the surplus nobility of {nation} broke away "
                    f"and founded {breakaway}."
                )
            return f"Year {event.year}: {breakaway} broke away from {nation}."
        case EventKind.AUFSTAND:
            deaths = _population_loss(event.effects)
            gave = _wealth_redistributed(event.effects)
            return (
                f"Year {event.year}: an uprising convulsed {nation}, costing {deaths} "
                f"lives and forcing the elite to yield {gave:.0%} of its wealth."
            )
        case EventKind.PUTSCH:
            ruler = _ruler_name(world, event.subjects[1]) if len(event.subjects) > 1 else "?"
            return (
                f"Year {event.year}: the overgrown nobility of {nation} overthrew "
                f"{ruler} and purged its rivals."
            )
        case EventKind.BANKROTT:
            disbanded = _soldiers_disbanded(event.effects)
            return (
                f"Year {event.year}: {nation} went bankrupt and disbanded "
                f"{disbanded} soldiers it could no longer pay."
            )
        case EventKind.KOLLAPS:
            heirs = len(event.subjects) - 1
            states = "successor state" + ("s" if heirs != 1 else "")
            return (
                f"Year {event.year}: {nation} collapsed under pressures it could no "
                f"longer contain, shattering into {heirs} {states}."
            )
        case EventKind.KONVERSION:
            faith = _identity_name(world, event.subjects[1])
            return f"Year {event.year}: {nation} converted to the {faith} faith."
        case EventKind.SCHISMA:
            new_faith = _identity_name(world, event.subjects[1])
            old_faith = _identity_name(world, event.subjects[2])
            return (
                f"Year {event.year}: the {new_faith} faith schismed from the "
                f"{old_faith} faith within {nation}."
            )
        case EventKind.ERDBEBEN:
            deaths = _population_loss(event.effects)
            return (
                f"Year {event.year}: an earthquake devastated {nation}, "
                f"killing {deaths} and ruining its wealth."
            )
        case EventKind.INNOVATION:
            age = _tech_age(event.effects)
            return f"Year {event.year}: {nation} advanced into {age}."
        case EventKind.WENDEPUNKT:
            return _narrate_turning_point(world, event, log)
        case _:  # pragma: no cover - alle aktiven Arten sind oben abgedeckt
            return f"Year {event.year}: {nation} ({event.kind})."


def erklaere(world: World, log: EventLog, event: Event) -> list[str]:
    """Vollstaendige Faktoren-Aufschluesselung eines Events fuer die Erklaerung.

    Zeigt die Narration, alle ``factors`` nach Betrag sortiert (``label: gewicht``)
    und die zitierten ``causes`` als erzaehlte, eine Ebene tiefe Warum-Kette.
    """
    lines = [_narrate(world, event, log)]
    if event.factors:
        lines.append("  factors (sorted by magnitude):")
        for factor in sorted(event.factors, key=lambda f: abs(f.weight), reverse=True):
            lines.append(f"    {factor.label}: {factor.weight:+.3f}")
        lines.append(f"    = score {sum(f.weight for f in event.factors):+.3f}")
    if event.causes:
        lines.append("  because of:")
        for cause_id in event.causes:
            lines.append(f"    [{cause_id}] {_narrate(world, log.get(cause_id), log)}")
    return lines


def _format_top_factors(event: Event, limit: int = 3) -> str:
    """Top-Faktoren nach Betrag, als ``label (+w.ww)`` zusammengefasst."""
    top = sorted(event.factors, key=lambda f: abs(f.weight), reverse=True)[:limit]
    return ", ".join(f"{f.label} ({f.weight:+.2f})" for f in top) or "no factors"


# --- kleine, reine Helfer ---------------------------------------------------

def _nation_name(world: World, pid: EntityId) -> str:
    polity = world.polities.get(pid)
    return polity.name if polity else f"polity#{pid}"


def _ruler_name(world: World, rid: EntityId) -> str:
    """Loese einen Herrschernamen auf (auch verstorbene bleiben im Register)."""
    r = world.rulers.get(rid)
    return r.name if r else f"ruler#{rid}"


def _ruler_age(world: World, rid: EntityId) -> int:
    """Endalter eines Herrschers (beim Tod eingefroren im Register)."""
    r = world.rulers.get(rid)
    return r.age if r else 0


def _identity_name(world: World, iid: EntityId) -> str:
    """Loese einen Identitaets-/Glaubensnamen auf (bleibt dauerhaft im Register)."""
    ident = world.identities.get(iid)
    return ident.name if ident else f"faith#{iid}"


def _is_faith_war(event: Event) -> bool:
    """Ein Krieg ist ein Glaubenskrieg, wenn Glaubensreibung ein Hauptantrieb war."""
    return _driven_by(event, FactorLabel.GLAUBENSGRABEN)


def _is_trade_war(event: Event) -> bool:
    """Ein Krieg aus Handelsverflechtung: die Abhaengigkeit vom Gegner trieb ihn (Aenderung 5)."""
    return _driven_by(event, FactorLabel.HANDELSABHAENGIGKEIT)


def _is_pressure_war(event: Event) -> bool:
    """Ein Krieg als Entladung des Aussendrucks (Aenderung 6).

    Die Spannung stand ueber der Schwelle und ihr staerkster Druck kam von aussen —
    die Nation MUSSTE nach aussen handeln. Der Krieg ist dann kein Griff nach Beute,
    sondern das Ventil einer Krise.
    """
    return _driven_by(event, FactorLabel.AUSSENDRUCK)


def _driven_by(event: Event, label: str, limit: int = 3) -> bool:
    """War ``label`` einer der staerksten TREIBENDEN (positiven) Faktoren?

    Der gemeinsame Massstab von ``_is_faith_war``/``_is_trade_war`` und der
    Entladungs-Narration: ein Randbeitrag benennt das Ereignis nicht, ein Hauptantrieb
    schon.
    """
    drivers = sorted(
        (f for f in event.factors if f.weight > 0.0), key=lambda f: f.weight, reverse=True
    )[:limit]
    return any(f.label == label for f in drivers)


def _wealth_redistributed(effects: tuple[Effect, ...]) -> float:
    """Wieviel Wohlstandsanteil die Elite im Aufstand abgeben musste."""
    for effect in effects:
        if effect.field == "elite_wealth":
            return max(0.0, float(effect.before) - float(effect.after))  # type: ignore[arg-type]
    return 0.0


def _soldiers_disbanded(effects: tuple[Effect, ...]) -> int:
    """Wieviele Soldaten der Bankrott entliess."""
    for effect in effects:
        if effect.field == "soldiers":
            return int(float(effect.before) - float(effect.after))  # type: ignore[arg-type]
    return 0


def _schisma_cause(log: EventLog, event: Event) -> Event | None:
    """Das Schisma unter den Ursachen eines Events (fuer die Buendnisbruch-Narration)."""
    for cause_id in event.causes:
        cause = log.get(cause_id)
        if cause.kind == EventKind.SCHISMA:
            return cause
    return None


_DISASTER_WORDS: dict[EventKind, str] = {
    EventKind.ERDBEBEN: "earthquake",
}


def _disaster_cause(log: EventLog, event: Event) -> str | None:
    """Das Wort fuer einen Schock unter den Ursachen (fuer "dies ermoeglichte das")."""
    for cause_id in event.causes:
        word = _DISASTER_WORDS.get(log.get(cause_id).kind)
        if word is not None:
            return word
    return None


def _narrate_turning_point(world: World, event: Event, log: EventLog) -> str:
    """Erzaehle einen Wendepunkt; bei Machtwechsel eine kausale "ermoeglichte"-Aussage."""
    labels = {f.label for f in event.factors}
    year = event.year
    if FactorLabel.MACHTWECHSEL in labels:
        new = _nation_name(world, event.subjects[0])
        old = _nation_name(world, event.subjects[1]) if len(event.subjects) > 1 else "a rival"
        # Zeitliche Naehe + Kausalgraph: lag ein Schock kurz vor der Machtverschiebung?
        shock = _disaster_cause(log, event)
        if shock is not None:
            return (
                f"Year {year}: the {shock} that had weakened {old} allowed {new} "
                f"to rise to dominance — a turning point."
            )
        return (
            f"Year {year}: {new} supplanted {old} as the dominant power "
            f"— a turning point."
        )
    if FactorLabel.TECHNOLOGISCHER_DURCHBRUCH in labels:
        nation = _nation_name(world, event.subjects[0])
        return f"Year {year}: {nation} ushered in the Industrial Age — a turning point."
    if FactorLabel.GLAUBENSWANDEL in labels:
        faith = _identity_name(world, event.subjects[0])
        return f"Year {year}: the {faith} faith became the dominant creed — a turning point."
    if FactorLabel.BUENDNISZERFALL in labels:
        a = _nation_name(world, event.subjects[0])
        b = _nation_name(world, event.subjects[1])
        span = int(next(f.weight for f in event.factors if f.label == FactorLabel.BUENDNISZERFALL))
        return (
            f"Year {year}: the ancient alliance between {a} and {b} collapsed after "
            f"{span} years — a turning point."
        )
    if FactorLabel.GEBIETSKOLLAPS in labels:
        nation = _nation_name(world, event.subjects[0])
        return f"Year {year}: {nation} collapsed, losing much of its realm — a turning point."
    return f"Year {year}: a turning point reshaped the age."  # pragma: no cover


def _age_name_of(world: World, event: Event) -> str:
    """Der Name des durch einen Wendepunkt eroeffneten Zeitalters."""
    for eff in event.effects:
        if eff.field == "age_kind" and eff.after == "industrial":
            return "the Industrial Age"
    return f"the Age of {_nation_name(world, event.subjects[0])}"


def _tech_age(effects: tuple[Effect, ...]) -> str:
    """Lies das durch eine Innovation erreichte Zeitalter aus dem Effekt."""
    for effect in effects:
        if effect.field == "tech_age":
            return str(effect.after)
    return "a new age"


def _accession_mode(effects: tuple[Effect, ...]) -> str:
    """Lies den Machtantritt aus dem Sukzessions-Effekt."""
    for effect in effects:
        if effect.field == "accession":
            return str(effect.after)
    return "succeeded"


def _region_name(world: World, rid: EntityId | None) -> str:
    if rid is None:
        return "unknown territory"
    region = world.regions.get(rid)
    return region.name if region else f"region#{rid}"


def _capital_region(effects: tuple[Effect, ...]) -> EntityId | None:
    for effect in effects:
        if effect.field == "capital":
            return effect.after  # type: ignore[return-value]
    return None


def _transferred_region(effects: tuple[Effect, ...]) -> EntityId | None:
    for effect in effects:
        if effect.field == "owner":
            return effect.entity
    return None


def _population_after(effects: tuple[Effect, ...]) -> int:
    for effect in effects:
        if effect.field == "population":
            return int(effect.after)  # type: ignore[arg-type]
    return 0


def _population_loss(effects: tuple[Effect, ...]) -> int:
    for effect in effects:
        if effect.field == "population":
            return int(effect.before) - int(effect.after)  # type: ignore[arg-type]
    return 0
