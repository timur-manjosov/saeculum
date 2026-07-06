"""query — die "Warum?"-Abfrage: Rueckwaerts-Traversierung des Kausalgraphen.

Gegeben eine Entitaet oder ein Event, folgt ``warum_event`` den ``causes``-Kanten
rueckwaerts und gibt die Kette mit den **Chronik-Templates** aus — dieselbe
Narration wie die Chronik, nur als eingerueckter Ursachenbaum. Reine, read-only
Ableitung aus dem Log; kein RNG, keine Mutation. Funktioniert fuer Spieler wie
fuer Entwickler.

Diese Datei ist abhaengigkeitsfrei (nur Kern + ``chronicle``); ``rich`` faerbt die
Ausgabe erst in der Render-Schicht ein.
"""

from __future__ import annotations

from worldsim.chronicle import dominante_faktoren, erzaehle
from worldsim.events import EventId, EventKind, EventLog
from worldsim.models import EntityId, World

__all__ = [
    "finde_kollaps",
    "warum_entitaet",
    "warum_event",
]

# Ereignisse, die einen Rueckschlag/Zusammenbruch fuer ihr erstes bzw. betroffenes
# Subjekt markieren — Kandidaten fuer die Frage „Warum kollabierte X?".
_SETBACK_KINDS = (
    EventKind.WENDEPUNKT,
    EventKind.ABSPALTUNG,
    EventKind.SCHLACHT,
    EventKind.PEST,
    EventKind.ERDBEBEN,
    EventKind.DUERRE,
    EventKind.BUENDNIS_BRUCH,
)


def _faktor_text(event_id: EventId, log: EventLog) -> str:
    """Die dominanten Faktoren eines Events als kompakter ``label +w``-Anhang."""
    top = dominante_faktoren(log.get(event_id))
    if not top:
        return ""
    return " [" + ", ".join(f"{label} {weight:+.2f}" for label, weight in top) + "]"


def warum_event(
    world: World, log: EventLog, event_id: EventId, *, max_depth: int = 6
) -> list[str]:
    """Erzaehle die Ursachenkette eines Events als eingerueckten Baum.

    Jede Zeile traegt die Chronik-Narration plus ihre dominanten Faktoren. Die
    Traversierung folgt ausschliesslich **frueheren** ``causes`` (der Graph ist
    zyklenfrei), stabil sortiert und dedupliziert.
    """
    lines: list[str] = []
    seen: set[EventId] = set()

    def rec(eid: EventId, depth: int, prefix: str) -> None:
        event = log.get(eid)
        text = erzaehle(world, log, event)
        lines.append(f"{prefix}{text}{_faktor_text(eid, log)}")
        seen.add(eid)
        if depth >= max_depth:
            return
        causes = [c for c in sorted(event.causes) if c not in seen]
        for cause in causes:
            rec(cause, depth + 1, "    " + prefix if depth else "  └─ ")

    root = log.get(event_id)
    header = f"Why? — {erzaehle(world, log, root)}"
    lines.append(header)
    for cause in [c for c in sorted(root.causes) if c not in seen]:
        rec(cause, 1, "  └─ ")
    if len(lines) == 1:
        lines.append("  (no recorded cause — a root event.)")
    return lines


def finde_kollaps(log: EventLog, entity: EntityId) -> EventId | None:
    """Finde das aussagekraeftigste Rueckschlag-Event einer Entitaet.

    Bevorzugt einen territorialen Kollaps-Wendepunkt, sonst den juengsten
    Rueckschlag (Niederlage/Schock/Abspaltung/Buendnisbruch), in dem die Entitaet
    das **leidende** Subjekt ist. Territoriale Kollaps-Wendepunkte nennen die
    Entitaet als erstes Subjekt; Schlacht-Niederlagen als zweites.
    """
    candidates = [e for e in log.by_subject(entity) if e.kind in _SETBACK_KINDS]

    # 1) Ein Territoriums-Kollaps-Wendepunkt (Entitaet = erstes Subjekt).
    collapses = [
        e
        for e in candidates
        if e.kind == EventKind.WENDEPUNKT
        and e.subjects
        and e.subjects[0] == entity
        and any(f.label == "Gebietskollaps" for f in e.factors)
    ]
    if collapses:
        return collapses[-1].id

    # 2) Der juengste Rueckschlag, in dem die Entitaet leidet.
    def leidet(eid: EventId) -> bool:
        e = log.get(eid)
        if e.kind == EventKind.SCHLACHT:
            return len(e.subjects) > 1 and e.subjects[1] == entity  # Verlierer
        if e.kind == EventKind.ABSPALTUNG:
            return bool(e.subjects) and e.subjects[0] == entity  # Mutterland
        return bool(e.subjects) and e.subjects[0] == entity

    suffering = [e for e in candidates if leidet(e.id)]
    if suffering:
        return suffering[-1].id
    return None


def warum_entitaet(
    world: World, log: EventLog, entity: EntityId, *, max_depth: int = 6
) -> list[str]:
    """Beantworte „Warum kollabierte/geschah <Entitaet>?" ueber ihren Rueckschlag.

    Waehlt das aussagekraeftigste Rueckschlag-Event der Entitaet und traversiert
    von dort die Ursachenkette. Gibt es keinen Rueckschlag, eine ruhige Antwort.
    """
    from worldsim.chronicle import _nation_name  # lokal: privater Helfer der Chronik

    name = _nation_name(world, entity)
    event_id = finde_kollaps(log, entity)
    if event_id is None:
        return [f"Why did {name} decline? — no recorded setback; it endured."]
    lines = warum_event(world, log, event_id, max_depth=max_depth)
    lines[0] = f"Why did {name} suffer? — {erzaehle(world, log, log.get(event_id))}"
    return lines
