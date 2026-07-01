"""Phase 4: Identitaet/Glaube — EIN Mechanismus mit Affinitaet, Konversion, Schisma.

Eine diskrete ``identity_id`` je Nation stiftet Affinitaet (gleicher Glaube ⇒
Buendnis leichter) oder Reibung (fremder Glaube ⇒ Krieg leichter). Ein zelotischer
Herrscher spaltet gelegentlich eine neue Identitaet ab (Schisma) — vorher gleiche
Nationen haben danach Reibung, und ein Buendnis unter Glaubensbruedern zerbricht.
Alles deterministisch und ueber den kausalen Event-Graphen nachvollziehbar.
"""

from __future__ import annotations

from worldsim.chronicle import chronik
from worldsim.config import DEFAULT_CONFIG
from worldsim.driver import simulate
from worldsim.events import EventKind, FactorLabel


def test_identity_layer_is_deterministic() -> None:
    """Gleiches ``(seed, years)`` ⇒ identische Welt inklusive Identitaeten/Log."""
    wa, la = simulate(seed=7, years=200)
    wb, lb = simulate(seed=7, years=200)
    assert wa == wb
    assert [e.__dict__ for e in la] == [e.__dict__ for e in lb]


def test_every_nation_has_a_registered_identity() -> None:
    """Aufgabe 1: jede Nation traegt genau eine gueltige, registrierte Identitaet."""
    world, _ = simulate(seed=42, years=120)
    assert world.identities
    for pol in world.polities.values():
        assert pol.identity_id is not None
        assert pol.identity_id in world.identities


def test_schism_creates_a_new_identity() -> None:
    """Aufgabe 4: ein Schisma erzeugt eine neue Identitaet (eigene id, Ursprung verlinkt)."""
    world, log = simulate(seed=42, years=200)
    schisms = [e for e in log if e.kind == EventKind.SCHISMA]
    assert schisms

    initial_faiths = {i for i in world.identities if world.identities[i].parent is None}
    born_by_schism = {i for i in world.identities if world.identities[i].parent is not None}
    assert born_by_schism  # es entstanden neue Identitaeten
    assert len(world.identities) > len(initial_faiths)

    for event in schisms:
        _nation, new_faith, old_faith = event.subjects
        assert new_faith in world.identities
        assert old_faith in world.identities
        assert new_faith != old_faith
        # Die neue Identitaet nennt ihre Ursprungs-Identitaet.
        assert world.identities[new_faith].parent == old_faith


def test_affinity_appears_as_a_named_factor_in_decisions() -> None:
    """Aufgabe 2/7: Affinitaet veraendert nachweisbar Entscheidungen (Faktor taucht auf)."""
    _, log = simulate(seed=42, years=200)

    # Fremder Glaube als Kriegsgrund: der Graben-Faktor steht in Kriegs-Events.
    war_friction = [
        e
        for e in log
        if e.kind == EventKind.KRIEG
        and any(f.label == FactorLabel.GLAUBENSGRABEN.value for f in e.factors)
    ]
    assert war_friction

    # Gleicher Glaube als Buendnis-Bonus: der Affinitaets-Faktor steht in Buendnissen.
    alliance_affinity = [
        e
        for e in log
        if e.kind == EventKind.BUENDNIS
        and any(f.label == FactorLabel.GLAUBENSAFFINITAET.value for f in e.factors)
    ]
    assert alliance_affinity


def test_schism_breaks_an_alliance_of_former_co_religionists() -> None:
    """Aufgabe 5/Abschluss: ein Schisma zerbricht ein Buendnis unter Glaubensbruedern."""
    _, log = simulate(seed=42, years=200)

    breaks_by_schism = [
        e
        for e in log
        if e.kind == EventKind.BUENDNIS_BRUCH
        and e.causes
        and log.get(e.causes[0]).kind == EventKind.SCHISMA
    ]
    assert breaks_by_schism

    for brk in breaks_by_schism:
        schism = log.get(brk.causes[0])
        # Der Buendnisbruch nennt genau das Schisma als Ursache.
        assert schism.kind == EventKind.SCHISMA
        # Die Bruchpartner waren am Buendnis beteiligt.
        assert len(brk.subjects) == 2


def test_schism_is_caused_by_a_ruler_succession() -> None:
    """Aufgabe 4: das Schisma folgt dem Machtantritt eines zelotischen Herrschers."""
    _, log = simulate(seed=42, years=200)
    schisms = [e for e in log if e.kind == EventKind.SCHISMA]
    assert schisms
    for event in schisms:
        assert event.causes  # ein Schisma hat stets eine Ursache
        assert all(log.get(c).kind == EventKind.SUKZESSION for c in event.causes)


def test_conversion_spreads_an_existing_faith() -> None:
    """Aufgabe 3: Konversion uebernimmt einen bestehenden Glauben eines Nachbarn."""
    world, log = simulate(seed=42, years=200)
    conversions = [e for e in log if e.kind == EventKind.KONVERSION]
    assert conversions
    for event in conversions:
        nation, new_faith, _dominant = event.subjects
        assert nation in world.polities
        assert new_faith in world.identities
        # Der Effekt dokumentiert den Glaubenswechsel als strukturiertes Delta.
        assert any(
            eff.field == "identity_id" and eff.after == new_faith for eff in event.effects
        )


def test_a_war_can_be_a_war_of_faith() -> None:
    """Aufgabe 5: ein Krieg, in dem Glaubensreibung ein Hauptantrieb ist (Glaubenskrieg).

    Geprueft am tatsaechlichen Chronik-Text: die Narration nennt ihn einen
    "war of faith", wenn der Glaubensgraben zu den treibenden Faktoren zaehlt.
    """
    world, log = simulate(seed=42, years=200)
    lines = chronik(world, log, DEFAULT_CONFIG)
    assert any("war of faith" in line for line in lines)
