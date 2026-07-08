"""driver — der headless Kern: Weltgenerierung, Tick-Loop und ``simulate``.

**Keine** Abhaengigkeit zu Rendering oder Eingabe. Der Driver besitzt den
Master-RNG und den EventLog; Systeme bekommen nur ihren benannten Sub-Strom.
Die Pipeline ``SYSTEMS`` ist hier in **fester Reihenfolge** registriert.

``simulate`` ist eine reine Funktion der Eingabe ``(seed, years, cfg)`` —
Speichern = Seed.
"""

from __future__ import annotations

from dataclasses import replace

from worldsim.config import DEFAULT_CONFIG, Config
from worldsim.events import EventLog
from worldsim.models import (
    AccessionMode,
    EntityId,
    Identity,
    NationTraits,
    Polity,
    Region,
    Ruler,
    Stocks,
    World,
)
from worldsim.names import make_name
from worldsim.rng import Rng, Stream
from worldsim.systems import (
    System,
    consumption,
    diplomacy,
    disaster,
    epoch,
    expansion,
    forge_ruler,
    founding,
    friction,
    identity,
    population,
    production,
    research,
    ruler,
    war,
)

__all__ = ["SYSTEMS", "simulate", "worldgen"]

# Feste Pipeline-Reihenfolge. Gruendung zuerst (meldet neue Nationen), dann der
# Herrscher-Lauf (Alterung/Sukzession setzt die effektiven Traits dieses Jahres),
# die Subsistenz-Kette, friedliche Expansion, danach Reibung/Diplomatie/Krieg.
SYSTEMS: list[tuple[str, System]] = [
    ("founding", founding),
    ("ruler", ruler),
    # Forschung vor der Produktion: die erreichte Tech-Stufe hebt noch dieses Jahr
    # Effizienz und Schlagkraft.
    ("research", research),
    ("production", production),
    ("consumption", consumption),
    ("population", population),
    ("expansion", expansion),
    ("friction", friction),
    ("diplomacy", diplomacy),
    ("war", war),
    # Am Tick-Ende: Glaubensausbreitung (Konversion) und Schisma. Die Affinitaets-
    # Faktoren in Diplomatie/Krieg lesen die Identitaeten des Vorjahres.
    ("identity", identity),
    # Danach exogene Schocks (Pest/Erdbeben/Duerre), die Gleichgewichte stoeren ...
    ("disaster", disaster),
    # ... und zuletzt die Wendepunkt-Waechter, die den Ausgang des Jahres deuten.
    ("epoch", epoch),
]

# --- kosmetische Namensgebung (Flavour, getrennter RNG-Strom) --------------
# Nationsnamen kommen aus dem gemeinsamen ``names``-Generator (rein kosmetisch,
# da Nationsverhalten aus Traits stammt, nicht aus dem Namen). Regionsnamen sind
# beschreibend und behalten ihren eigenen, ebenfalls kosmetischen Stil.
_REGION_DIRECTIONS = (
    "northern", "southern", "eastern", "western", "central",
    "upper", "lower", "outer", "inner", "far",
)
_REGION_TERRAINS = (
    "plains", "hills", "forests", "coast", "valley",
    "marches", "steppe", "highlands", "delta", "moors",
)


def _region_name(cos: Stream) -> str:
    """Erfinde einen beschreibenden Regionsnamen (rein kosmetisch)."""
    return f"the {cos.choice(_REGION_DIRECTIONS)} {cos.choice(_REGION_TERRAINS)}"


def _nation_traits(gen: Stream) -> NationTraits:
    """Ziehe die sechs Nationscharakterzuege deterministisch aus dem Seed (0..1).

    Feste Ziehreihenfolge ⇒ reproduzierbar. Semantischer Strom, da Traits das
    Verhalten bestimmen.
    """
    return NationTraits(
        aggression=gen.random(),
        expansion=gen.random(),
        innovation=gen.random(),
        honor=gen.random(),
        diplomacy=gen.random(),
        caution=gen.random(),
    )


def worldgen(master: Rng, cfg: Config) -> World:
    """Erzeuge die Anfangswelt deterministisch aus dem Seed.

    Regionen sind Knoten eines abstrakten Adjazenzgraphen (Kanten = Grenzen),
    keine gerenderte Karte. ``num_nations`` Nationen starten je auf einem Feld
    mit Anfangsbevoelkerung, Anfangslager und generiertem Namen.

    Semantische Groessen (Kapazitaeten, Adjazenz, Platzierung) stammen aus dem
    Strom ``"worldgen"``; **Namen** aus einem getrennten *kosmetischen* Strom,
    damit Flavour die semantische Reproduzierbarkeit nie beeinflusst. Daher
    bekommt worldgen den Master-RNG (nicht nur einen Strom).
    """
    gen = master.stream("worldgen")
    cos = master.cosmetic_stream("worldgen-names")

    # Regionen: ids 0 .. num_regions-1.
    regions: dict[EntityId, Region] = {}
    for rid in range(cfg.num_regions):
        capacity = gen.uniform(cfg.region_food_capacity_min, cfg.region_food_capacity_max)
        regions[rid] = Region(id=rid, name=_region_name(cos), food_capacity=capacity)

    _build_adjacency(regions, gen, cfg)

    # Nationen: ids num_regions .. num_regions+num_nations-1.
    # Anfangsherrscher: ids danach, num_regions+num_nations .. +2*num_nations-1.
    # Anfangs-Identitaeten: ids danach, num_regions+2*num_nations .. +num_identities-1.
    polities: dict[EntityId, Polity] = {}
    rulers: dict[EntityId, Ruler] = {}
    capitals = _choose_capitals(regions, gen, cfg)
    ruler_base = cfg.num_regions + cfg.num_nations
    identity_base = ruler_base + cfg.num_nations

    # Wenige Anfangs-Identitaeten (< Nationen), damit Nationen sie teilen und
    # daraus Glaubensbloecke — und spaeter Schismata — entstehen koennen.
    identities: dict[EntityId, Identity] = {}
    identity_ids: list[EntityId] = []
    for i in range(cfg.num_identities):
        iid: EntityId = identity_base + i
        identities[iid] = Identity(id=iid, name=make_name(cos))
        identity_ids.append(iid)

    for n in range(cfg.num_nations):
        pid: EntityId = cfg.num_regions + n
        rid: EntityId = ruler_base + n
        capital = capitals[n]
        regions[capital].owner = pid
        # Anfangsherrscher gruenden eine Dynastie ⇒ Erbfolge-Legitimitaet.
        rulers[rid] = forge_ruler(rid, gen, cfg, mode=AccessionMode.INHERITED)
        polities[pid] = Polity(
            id=pid,
            name=make_name(cos),
            capital=capital,
            territory=(capital,),
            founded_year=0,
            population=cfg.initial_population,
            peak_population=cfg.initial_population,
            stocks=Stocks(
                getreide=cfg.initial_getreide,
                eisen=cfg.initial_eisen,
                gold=cfg.initial_gold,
            ),
            traits=_nation_traits(gen),
            leader=rid,
            identity_id=identity_ids[n % cfg.num_identities],
        )

    # Geografische Lage zuletzt ziehen: so bleiben alle vorherigen semantischen
    # Ziehungen (Kapazitaeten, Adjazenz, Hauptstaedte, Traits) unveraendert — der
    # Lauf ist byte-identisch zu vorher, nur um Koordinaten reicher.
    _place_regions(regions, gen)

    return World(
        year=0,
        regions=regions,
        polities=polities,
        rulers=rulers,
        identities=identities,
        next_id=identity_base + cfg.num_identities,
    )


def _build_adjacency(regions: dict[EntityId, Region], gen: Stream, cfg: Config) -> None:
    """Verbinde Regionen zu einem zusammenhaengenden Graphen (Ring + Extrakanten)."""
    ids = list(regions)
    edges: set[tuple[EntityId, EntityId]] = set()

    # Ring ueber eine deterministische Permutation ⇒ garantiert zusammenhaengend.
    order = ids[:]
    gen.shuffle(order)
    for i in range(len(order)):
        a, b = order[i], order[(i + 1) % len(order)]
        edges.add((min(a, b), max(a, b)))

    # Ein paar Extrakanten fuer ein reicheres Grenzgeflecht.
    for _ in range(cfg.extra_edges):
        a, b = gen.choice(ids), gen.choice(ids)
        if a != b:
            edges.add((min(a, b), max(a, b)))

    adjacency: dict[EntityId, set[EntityId]] = {rid: set() for rid in ids}
    for a, b in edges:
        adjacency[a].add(b)
        adjacency[b].add(a)
    for rid, neighbors in adjacency.items():
        regions[rid].nachbarn = tuple(sorted(neighbors))


def _choose_capitals(
    regions: dict[EntityId, Region], gen: Stream, cfg: Config
) -> list[EntityId]:
    """Waehle deterministisch verteilte Startfelder fuer die Nationen."""
    return gen.sample(sorted(regions), k=cfg.num_nations)


def _place_regions(regions: dict[EntityId, Region], gen: Stream) -> None:
    """Weise jeder Region eine geografische Koordinate in [0,1)^2 zu.

    Aus dem worldgen-Sub-Strom (Determinismus-Vertrag), rein zur Verortung auf der
    Karte. Keine Tile-Mikrosimulation, keine Geografie-Physik: die Lage beeinflusst
    das Verhalten nicht — sie ist nur eine Ansicht ueber dem Adjazenzgraphen.
    """
    for rid in sorted(regions):
        regions[rid].coord = (gen.random(), gen.random())


def simulate(
    seed: int, years: int, cfg: Config = DEFAULT_CONFIG
) -> tuple[World, EventLog]:
    """Fuehre die Simulation headless aus und gib ``(World, EventLog)`` zurueck.

    Reine Funktion der Eingabe: gleiches ``(seed, years, cfg)`` ⇒ identisches
    Ergebnis inklusive identischer EventIds.
    """
    master = Rng(seed)
    log = EventLog()
    world = worldgen(master, cfg)

    for year in range(years):
        world = replace(world, year=year)
        for sid, system in SYSTEMS:
            # Pro System und Jahr ein eigener, benannter Sub-Strom. Systeme
            # haengen ihre Events selbst in den Log ein (fuer cause-Verlinkung).
            stream = master.stream(f"{sid}:{year}")
            world = system(world, stream, cfg, log)

    return world, log
