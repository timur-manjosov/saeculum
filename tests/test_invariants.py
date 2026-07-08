"""Invarianten: in jedem Tick bleibt die Welt strukturell gueltig.

Geprueft ueber die oeffentliche API: ``simulate(seed, k)`` liefert den Zustand
nach ``k`` Jahren, also wird jeder Tick 0..N als eigener Endzustand validiert.
"""

from __future__ import annotations

import pytest
from worldsim.config import DEFAULT_CONFIG, Config
from worldsim.driver import simulate
from worldsim.models import World


def _assert_world_invariants(world: World, cfg: Config) -> None:
    region_ids = set(world.regions)

    for pid, pol in world.polities.items():
        # Nicht-negative Bestaende (drei handelbare) und Forschungsfortschritt.
        assert pol.population >= 0
        assert pol.stocks.getreide >= 0.0
        assert pol.stocks.eisen >= 0.0
        assert pol.stocks.gold >= 0.0
        assert pol.knowledge >= 0.0

        # Gueltiges Territorium: existierende Regionen, korrekt zugeordnet.
        assert set(pol.territory) <= region_ids
        assert pol.capital in pol.territory
        for rid in pol.territory:
            assert world.regions[rid].owner == pid

    # Eigentum ist konsistent und eindeutig (keine Region zwei Nationen).
    for rid, region in world.regions.items():
        if region.owner is not None:
            assert region.owner in world.polities
            assert rid in world.polities[region.owner].territory

    # Nie mehr beanspruchtes Gebiet als es Felder gibt.
    claimed = sum(len(p.territory) for p in world.polities.values())
    assert claimed <= cfg.num_regions

    # Phase 2: Buendnisse sind symmetrisch; Trust bleibt im gueltigen Bereich.
    for pid, pol in world.polities.items():
        for ally in pol.allies:
            assert ally in world.polities
            assert pid in world.polities[ally].allies
        for trust in pol.relations.values():
            assert -1.0 <= trust <= 1.0

    # Phase 3: Jede Polity hat am Tick-Ende genau einen lebenden Herrscher.
    living_leaders = {p.leader for p in world.polities.values()}
    for pol in world.polities.values():
        assert pol.leader is not None
        assert pol.leader in world.rulers
        ruler = world.rulers[pol.leader]
        assert ruler.alive
        assert 0.0 <= ruler.legitimacy <= 1.0
        assert ruler.age >= 0
        assert ruler.lifespan > 0
    # Tote Herrscher bleiben fuer die Chronik im Register, fuehren aber nichts mehr.
    for rid, ruler in world.rulers.items():
        if not ruler.alive:
            assert rid not in living_leaders

    # Phase 4: jede Nation traegt genau eine gueltige, registrierte Identitaet.
    assert world.identities
    for pol in world.polities.values():
        assert pol.identity_id is not None
        assert pol.identity_id in world.identities
    # Durch Schisma entstandene Identitaeten nennen eine ebenfalls registrierte
    # Ursprungs-Identitaet (keine haengenden Verweise).
    for iid, ident in world.identities.items():
        assert ident.id == iid
        if ident.parent is not None:
            assert ident.parent in world.identities

    # Phase 5: Technologie/Wissen bleiben im gueltigen Bereich; Regionen behalten
    # trotz Erdbeben-Narben eine positive Nahrungskapazitaet.
    for pol in world.polities.values():
        assert pol.tech_level >= 0
        assert pol.knowledge >= 0.0
        assert pol.peak_territory >= 0
    for region in world.regions.values():
        assert region.food_capacity > 0.0


@pytest.mark.parametrize("seed", [1, 42, 1234])
def test_invariants_hold_every_tick(seed: int) -> None:
    for k in range(0, 61):
        world, _ = simulate(seed=seed, years=k)
        _assert_world_invariants(world, DEFAULT_CONFIG)


def test_population_never_negative_under_heavy_famine() -> None:
    """Auch mit brutaler Hungersnot-Mechanik bleibt die Bevoelkerung >= 0."""
    cfg = Config(famine_deaths_per_deficit=1000.0, harvest_variance=0.9)
    world, _ = simulate(seed=5, years=80, cfg=cfg)
    for pol in world.polities.values():
        assert pol.population >= 0
