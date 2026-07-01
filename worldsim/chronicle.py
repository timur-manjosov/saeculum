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

from worldsim.config import Config
from worldsim.events import Effect, Event, EventId, EventKind, EventLog, Factor, FactorLabel
from worldsim.models import EntityId, World

__all__ = [
    "annalen",
    "chronik",
    "dominante_faktoren",
    "erklaere",
    "folgen",
    "lebenslauf",
    "warum",
    "wichtigkeit",
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


# --- Wichtigkeit (§6): selbst eine Summe benannter Faktoren -----------------

def wichtigkeit(event: Event) -> tuple[float, tuple[Factor, ...]]:
    """Berechne den Wichtigkeits-Score als Summe benannter Faktoren.

    Gibt ``(score, faktoren)`` zurueck — die Faktoren SIND die Begruendung, auch
    fuer die Auswahl, was Geschichte „wert" ist.
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
        case EventKind.KONVERSION:
            factors = (Factor(FactorLabel.BEKEHRUNG, 3.0),)
        case EventKind.SCHISMA:
            factors = (Factor(FactorLabel.GLAUBENSSPALTUNG, 4.5),)
        case _:
            factors = ()
    score = sum(f.weight for f in factors)
    return score, factors


# --- Narration: deterministisches Templating je EventKind ------------------

def chronik(world: World, log: EventLog, cfg: Config) -> list[str]:
    """Filtere nach Wichtigkeits-Schwelle und erzaehle die Events als Text.

    Reihenfolge: nach Jahr, dann Emissions-id (stabil). Beispielzeile:
    ``Year 35: Veldoria expanded into the eastern plains``.
    """
    lines: list[str] = []
    for event in sorted(log, key=lambda e: (e.year, e.id)):
        score, _ = wichtigkeit(event)
        if score < cfg.chronicle_min_importance:
            continue
        lines.append(_narrate(world, event, log))
    return lines


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
            verb = "declared a war of faith on" if _is_faith_war(event) else "declared war on"
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
            return f"Year {event.year}: {breakaway} broke away from {nation}."
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


def _is_faith_war(event: Event, limit: int = 3) -> bool:
    """Ein Krieg ist ein Glaubenskrieg, wenn Glaubensreibung ein Hauptantrieb war.

    Massstab sind die **treibenden** (positiven) Faktoren: liegt der
    Glaubensgraben unter ihren groessten, war der fremde Glaube ein Hauptmotiv
    (nicht bloss ein Randbeitrag neben Aggression und Grenzreibung).
    """
    drivers = sorted(
        (f for f in event.factors if f.weight > 0.0), key=lambda f: f.weight, reverse=True
    )[:limit]
    return any(f.label == FactorLabel.GLAUBENSGRABEN for f in drivers)


def _schisma_cause(log: EventLog, event: Event) -> Event | None:
    """Das Schisma unter den Ursachen eines Events (fuer die Buendnisbruch-Narration)."""
    for cause_id in event.causes:
        cause = log.get(cause_id)
        if cause.kind == EventKind.SCHISMA:
            return cause
    return None


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
