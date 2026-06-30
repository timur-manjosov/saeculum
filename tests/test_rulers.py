"""Phase 3: Herrscher — Lebensspannen, Sukzession, Sukzessionskrise/Fragmentierung.

Geschichte wird charaktergetrieben: Herrscher sind eine duenne Trait-Ueberlagerung,
deren Wechsel automatisch Wendepunkte (Sukzession, ggf. Abspaltung) erzeugt — alles
deterministisch und ueber den kausalen Event-Graphen nachvollziehbar.
"""

from __future__ import annotations

from worldsim.config import DEFAULT_CONFIG
from worldsim.driver import simulate
from worldsim.events import EventKind, FactorLabel
from worldsim.models import AccessionMode


def test_every_polity_has_a_living_ruler_with_a_lifespan() -> None:
    """Aufgabe 1/4: jede Nation wird von genau einem lebenden Herrscher gefuehrt."""
    cfg = DEFAULT_CONFIG
    world, _ = simulate(seed=42, years=80)
    assert world.rulers
    for pol in world.polities.values():
        assert pol.leader in world.rulers
        ruler = world.rulers[pol.leader]
        assert ruler.alive
        assert cfg.ruler_lifespan_min <= ruler.lifespan <= cfg.ruler_lifespan_max
        assert ruler.age >= 0
        assert isinstance(ruler.accession, AccessionMode)


def test_succession_follows_death_and_creates_new_rulers() -> None:
    """Aufgabe 4: Herrscher sterben ⇒ Tod-Event ⇒ neuer Herrscher (Sukzession)."""
    world, log = simulate(seed=42, years=200)

    deaths = [e for e in log if e.kind == EventKind.TOD_FIGUR]
    successions = [e for e in log if e.kind == EventKind.SUKZESSION]
    assert deaths
    assert successions
    # Mehr Herrscher als Anfangsnationen ⇒ es gab echte Generationswechsel.
    assert len(world.rulers) > DEFAULT_CONFIG.num_nations
    # Jede natuerliche Sukzession nennt einen Tod als Ursache.
    assert any(
        any(log.get(c).kind == EventKind.TOD_FIGUR for c in s.causes)
        for s in successions
    )


def test_succession_events_carry_named_factors() -> None:
    """Jede Sukzession traegt ihre Begruendung (Legitimitaet + Antrittsart)."""
    _, log = simulate(seed=42, years=200)
    successions = [e for e in log if e.kind == EventKind.SUKZESSION]
    assert successions
    legit = {FactorLabel.LEGITIMITAET.value}
    for event in successions:
        assert event.factors
        labels = {f.label for f in event.factors}
        assert legit <= labels


def test_fragmentation_creates_a_valid_new_nation() -> None:
    """Aufgabe 5: eine Abspaltung ist eine vollwertige neue Nation."""
    world, log = simulate(seed=42, years=200)
    splits = [e for e in log if e.kind == EventKind.ABSPALTUNG]
    assert splits  # bei diesem Seed entstehen Abspaltungen

    region_ids = set(world.regions)
    for event in splits:
        parent_id, child_id = event.subjects[0], event.subjects[1]
        assert parent_id in world.polities
        assert child_id in world.polities
        child = world.polities[child_id]
        # Eigenes Territorium, eigene gueltige Hauptstadt, eigener Herrscher.
        assert child.territory
        assert child.capital in child.territory
        assert set(child.territory) <= region_ids
        for rid in child.territory:
            assert world.regions[rid].owner == child_id
        assert child.leader in world.rulers
        assert world.rulers[child.leader].alive
        # Eigene id, verschieden vom Mutterland.
        assert child_id != parent_id


def test_fragmentation_is_caused_by_succession_caused_by_death() -> None:
    """Aufgabe 5: Abspaltung ← Sukzession(-krise) ← Herrschertod (Kausalkette)."""
    _, log = simulate(seed=42, years=200)
    splits = [e for e in log if e.kind == EventKind.ABSPALTUNG]
    assert splits
    for event in splits:
        succ = [log.get(c) for c in event.causes if log.get(c).kind == EventKind.SUKZESSION]
        assert succ  # Abspaltung verweist auf die ausloesende Sukzession
        # Die Sukzession wiederum verweist auf einen Herrschertod.
        assert any(
            log.get(c).kind == EventKind.TOD_FIGUR
            for s in succ
            for c in s.causes
        )


def test_a_ruler_change_is_sometimes_flagged_as_turning_point() -> None:
    """Aufgabe 4: ein grosser Trait-Sprung markiert einen potenziellen Wendepunkt."""
    world, log = simulate(seed=42, years=300)
    flagged_events = [
        e
        for e in log
        if e.kind == EventKind.SUKZESSION
        and any(eff.field == "wendepunkt" for eff in e.effects)
    ]
    assert flagged_events
    # Das Flag liegt konsistent auch am Herrscher selbst.
    assert any(r.turning_point for r in world.rulers.values())


def test_dead_rulers_persist_for_the_chronicle() -> None:
    """Tote Herrscher bleiben benennbar (im Register), fuehren aber nichts mehr."""
    world, _ = simulate(seed=42, years=200)
    dead = [r for r in world.rulers.values() if not r.alive]
    assert dead
    living_leaders = {p.leader for p in world.polities.values()}
    for ruler in dead:
        assert ruler.name  # weiterhin namentlich aufloesbar
        assert ruler.id not in living_leaders
