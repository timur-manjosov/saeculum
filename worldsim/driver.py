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
from worldsim.geo import RegionGeography, derive_regions
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
    demografie,
    diplomacy,
    epoch,
    forge_ruler,
    founding,
    friction,
    goals,
    grievance,
    identity,
    initial_strata,
    production,
    research,
    ruler,
    tectonics,
    tension,
    trade,
)

__all__ = ["SYSTEMS", "simulate", "worldgen"]

# Feste Pipeline-Reihenfolge. Gruendung zuerst (meldet neue Nationen), dann der
# Herrscher-Lauf (Alterung/Sukzession setzt die effektiven Traits dieses Jahres),
# die Subsistenz-Kette, danach Reibung/Diplomatie und zuletzt die Zielwahl.
SYSTEMS: list[tuple[str, System]] = [
    ("founding", founding),
    ("ruler", ruler),
    # Forschung vor der Produktion: die erreichte Tech-Stufe hebt noch dieses Jahr
    # Effizienz und Schlagkraft.
    ("research", research),
    ("production", production),
    # Handel gleich nach der Produktion (Aenderung 5): frisch geernteter/gefoerderter
    # Ueberschuss fliesst entlang der Grenzen zu Defizit-Nachbarn — importiertes
    # Getreide wendet noch DIESE Hungersnot ab, Eisen/Gold heben noch dieses Jahr die
    # Schlagkraft, und die entstehende Abhaengigkeit speist die spaetere Zielwahl.
    ("trade", trade),
    ("consumption", consumption),
    # Demografie: Wachstum/Schrumpfung je Schicht + Rekrutierung; danach der Groll-
    # Aufbau (liest das frische Nahrungsdefizit und die Wohlstandsanteile).
    ("demografie", demografie),
    ("grievance", grievance),
    ("friction", friction),
    ("diplomacy", diplomacy),
    # Der Spannungszustand (Aenderung 6) steht am Ende der Lage-Bildung und VOR der
    # Zielwahl: er liest alles Frische (Groll, Schatz, Schichten, Abhaengigkeit,
    # favor, Reibung) und entlaedt sich, wo der Druck die Schwelle reisst — nach
    # innen selbst (Aufstand/Putsch/Abspaltung/Bankrott/Kollaps), nach aussen ueber
    # die Zielwahl gleich danach (Krieg). Deshalb muss er ihr vorausgehen.
    ("tension", tension),
    # Die utility-basierte Zielwahl steht am Ende der Lage-Bildung: sie liest die
    # frischen Groessen (Defizit, Groll, Reibung, Furcht, favor, Spannung) und
    # vollzieht das gewaehlte Ziel sofort — Expansion und Krieg sind ihre Handlungen.
    ("goals", goals),
    # Am Tick-Ende: Glaubensausbreitung (Konversion) und Schisma. Die Affinitaets-
    # Faktoren in Diplomatie/Krieg lesen die Identitaeten des Vorjahres.
    ("identity", identity),
    # Danach der einzige verbliebene exogene Schock (Aenderung 7): das Erdbeben, das
    # sich als Gesteinsspannung aufstaut und an einer Schwelle bricht. Es steht VOR dem
    # Wendepunkt-Waechter, damit dieser es noch als nahe Ursache eines Niedergangs
    # zitieren kann — seine eigentliche Wirkung entfaltet es aber erst im naechsten
    # Jahr, durch das Spannungssystem (leerer Schatz ⇒ Fiskaldruck, vernarbtes Land
    # ⇒ Hunger ⇒ Volksdruck). Es loest nichts aus, es setzt Druck.
    ("tectonics", tectonics),
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
    """Erzeuge die Anfangswelt deterministisch aus dem Seed — AUF der Geografie.

    Schritt 2: die Regionen sind nicht mehr blinde Knoten eines RNG-Graphen, sondern
    Stuecke der bei :mod:`worldsim.geo` erzeugten Welt. ``derive_regions`` platziert die
    Zentren auf Land, leitet Tragfaehigkeit/Eisen/Gold aus Biom, Klima und Wasser ab und
    baut die Nachbarschaft aus der Voronoi-Zerlegung des Gitters (dieselbe, die die Karte
    zeichnet). ``num_nations`` Nationen starten auf dem **besten** Land (fruchtbar,
    bewaessert, kuestennah) — nicht mehr gleichverteilt.

    Die Geografie ist eine reine Funktion des Seeds (kein Ziehen). Der Strom ``"worldgen"``
    zieht nur noch, was NICHT geografisch ist: die Verwerfungen (Geologie), die Herrscher
    und die Nationscharaktere. **Namen** kommen aus dem getrennten *kosmetischen* Strom.
    """
    gen = master.stream("worldgen")
    cos = master.cosmetic_stream("worldgen-names")

    # Schritt 2: alle geografischen Region-Eigenschaften aus der Welt-Geografie ableiten.
    geo = derive_regions(master.seed, cfg)

    # Regionen: ids 0 .. num_regions-1. Lage/Tragfaehigkeit/Ressourcen/Adjazenz geografisch.
    regions: dict[EntityId, Region] = {}
    for rid in range(cfg.num_regions):
        regions[rid] = Region(
            id=rid,
            name=_region_name(cos),
            food_capacity=geo.food_capacity[rid],
            iron_rich=geo.iron_rich[rid],
            gold_rich=geo.gold_rich[rid],
            nachbarn=geo.adjacency[rid],
            coord=geo.coords[rid],
        )
    # Die Verwerfungen bleiben eine gezogene Anfangsbedingung (Erdbeben-Geologie).
    _assign_seismicity(regions, gen, cfg)

    # Nationen: ids num_regions .. num_regions+num_nations-1.
    # Anfangsherrscher: ids danach, num_regions+num_nations .. +2*num_nations-1.
    # Anfangs-Identitaeten: ids danach, num_regions+2*num_nations .. +num_identities-1.
    polities: dict[EntityId, Polity] = {}
    rulers: dict[EntityId, Ruler] = {}
    capitals = _choose_capitals(geo, cfg)  # das beste, gestreute Startland (Aufgabe 4)
    # Die Wiege ist tragfaehig: eine Hauptstadt muss die Anfangsbevoelkerung ernaehren
    # koennen, sonst startete die Nation im Defizit und ginge sofort bankrott. Floort NUR
    # die Hauptstadt-Felder — die karge Umgebung bleibt geografisch (und duenn).
    for cap in capitals:
        regions[cap].food_capacity = max(regions[cap].food_capacity, cfg.capital_min_capacity)
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
        # Anfangsherrscher gruenden eine Dynastie ⇒ Erbfolge-Legitimitaet. Der Name kommt
        # aus dem kosmetischen Strom, die Konstitution aus dem semantischen.
        rulers[rid] = forge_ruler(
            rid, gen, cfg, mode=AccessionMode.INHERITED, name=make_name(cos)
        )
        polities[pid] = Polity(
            id=pid,
            name=make_name(cos),
            capital=capital,
            territory=(capital,),
            founded_year=0,
            strata=initial_strata(cfg),
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

    return World(
        year=0,
        seed=master.seed,  # nur fuer den KOSMETISCHEN Strom (Namen), nie fuer Fakten
        regions=regions,
        polities=polities,
        rulers=rulers,
        identities=identities,
        next_id=identity_base + cfg.num_identities,
    )


def _choose_capitals(geo: RegionGeography, cfg: Config) -> list[EntityId]:
    """Waehle die Startfelder der Nationen: bestes Land zuerst, aber gestreut (Aufgabe 4).

    ``geo.capital_rank`` liefert die Regionen nach Startland-Guete (Fruchtbarkeit +
    Kueste + Suesswasser). Wir nehmen sie der Reihe nach, ueberspringen aber jede, die an
    eine schon gewaehlte Hauptstadt grenzt — so gehen die Nationen auf das beste Land,
    ohne sich alle in dieselbe Ecke zu draengen. Deterministisch (kein RNG): die Rangfolge
    kommt aus der Geografie. Region-Index == Region-Id (0..num_regions-1).
    """
    chosen: list[EntityId] = []
    chosen_set: set[EntityId] = set()
    for rid in geo.capital_rank:
        if any(nb in chosen_set for nb in geo.adjacency[rid]):
            continue  # zu nah an einer schon gewaehlten Hauptstadt
        chosen.append(rid)
        chosen_set.add(rid)
        if len(chosen) == cfg.num_nations:
            return chosen
    # Kleine, dichte Welt: reichte die Streuung nicht, mit den naechstbesten auffuellen.
    for rid in geo.capital_rank:
        if rid not in chosen_set:
            chosen.append(rid)
            chosen_set.add(rid)
            if len(chosen) == cfg.num_nations:
                break
    return chosen


def _assign_seismicity(
    regions: dict[EntityId, Region], gen: Stream, cfg: Config
) -> None:
    """Verteile die Verwerfungen: welche Felder stauen Gesteinsspannung, und wie schnell.

    Aenderung 7: das ist der GANZE Zufall, der im Erdbeben noch steckt — eine
    Anfangsbedingung wie die Nahrungskapazitaet oder das Eisen. Der Tick wuerfelt danach
    nicht mehr: er laesst nur faellig werden, was hier verteilt wurde.

    ``strain`` startet ebenfalls gezogen. Das ist die Phase: ohne sie beben alle
    Verwerfungen dieser Welt zum ersten Mal im Gleichschritt, was kein Erdbeben mehr
    waere, sondern ein Weltuntergang mit Fahrplan.
    """
    for rid in sorted(regions):
        if gen.random() < cfg.seismic_region_fraction:
            regions[rid].seismicity = gen.random()
            regions[rid].strain = gen.random()


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
