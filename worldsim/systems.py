"""systems — Verhalten als reine Funktionen (Phase 2: Konflikt & Kausalgraph).

Einheitliche Signatur:

    def system(world: World, rng: Stream, cfg: Config, log: EventLog) -> World

Ein System liest die Welt (und den Log read-only, um Ursachen zu finden),
aktualisiert die Welt diszipliniert in-place auf reinen Daten und **haengt
emittierte Events selbst per** ``log.append(draft) -> EventId`` **ein** — so kennt
es die vergebene id und kann sie als ``cause`` weiterreichen. Der Log waechst nur
per append (Invariante §4). Systeme laufen je Jahr in **fester Reihenfolge** (im
Driver registriert) und bekommen ihren Sub-Strom explizit durchgereicht.

Im Entscheidungspfad wird ausschliesslich ueber **stabil sortierte** Sammlungen
iteriert (nach ``EntityId``); nie ueber ``set``/Einfuege-Reihenfolge. Damit ist
die Emissionsreihenfolge — und somit die EventId-Vergabe — deterministisch.

**Jede** KI-Entscheidung wird ueber :class:`~worldsim.events.Decision` als Summe
benannter Faktoren gebaut; die gesammelten ``factors``/``causes`` haengen
unveraendert am resultierenden Event. Rein mechanische Neuberechnungen
(production, consumption) emittieren kein Event (§10.1).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from worldsim.config import Config
from worldsim.events import (
    Decision,
    Effect,
    Event,
    EventDraft,
    EventId,
    EventKind,
    EventLog,
    Factor,
    FactorLabel,
)
from worldsim.models import (
    AccessionMode,
    EntityId,
    GoalKind,
    Identity,
    NationTraits,
    Polity,
    Region,
    Relation,
    Ruler,
    Stocks,
    Stratum,
    StratumKind,
    Tension,
    World,
)
from worldsim.names import make_name
from worldsim.rng import Rng, Stream

__all__ = [
    "System",
    "add_favor",
    "allied",
    "bevoelkerung",
    "consumption",
    "demografie",
    "dependency",
    "diplomacy",
    "epoch",
    "favor",
    "forge_ruler",
    "founding",
    "friction",
    "goals",
    "grievance",
    "hostile",
    "identity",
    "initial_strata",
    "production",
    "research",
    "ruler",
    "spannung",
    "tectonics",
    "tension",
    "trade",
]

# Ein System ist eine reine Funktion mit fester Signatur.
System = Callable[[World, Stream, Config, EventLog], World]


# === Schichten: abgeleitete Bevoelkerung & Helfer ===========================

def bevoelkerung(pol: Polity) -> int:
    """Gesamtbevoelkerung = Summe der Schichtgroessen (abgeleitet, kein Feld).

    Die eine Wahrheit ueber die Nations-Bevoelkerung, von Kern und Praesentation
    gemeinsam genutzt — so bleibt "Bevoelkerung = Summe der strata.size" konsistent.
    """
    return int(sum(s.size for s in pol.strata))


def initial_strata(cfg: Config) -> tuple[Stratum, ...]:
    """Baue die Anfangs-Schichtung einer Nation aus der Config (feste Reihenfolge).

    Kanonische Reihenfolge Arbeiter, Soldat, Elite — stabile Tuple-Positionen halten
    Iteration und Float-Reihenfolge (und damit den Determinismus) fest.
    """
    pop = cfg.initial_population
    return (
        Stratum(
            StratumKind.ARBEITER,
            size=pop * cfg.initial_worker_fraction,
            wealth_share=cfg.initial_worker_wealth,
        ),
        Stratum(
            StratumKind.SOLDAT,
            size=pop * cfg.initial_soldier_fraction,
            wealth_share=cfg.initial_soldier_wealth,
        ),
        Stratum(
            StratumKind.ELITE,
            size=pop * cfg.initial_elite_fraction,
            wealth_share=cfg.initial_elite_wealth,
        ),
    )


def _stratum_size(pol: Polity, kind: StratumKind) -> float:
    """Groesse einer Schicht (0.0, falls fehlend)."""
    return next((s.size for s in pol.strata if s.kind == kind), 0.0)


def _scaled_strata(strata: tuple[Stratum, ...], factor: float) -> tuple[Stratum, ...]:
    """Skaliere jede Schichtgroesse (Verluste/Teilung); Anteile & Groll bleiben."""
    return tuple(replace(s, size=max(0.0, s.size * factor)) for s in strata)


# === Beziehungs-Matrix: favor-Helfer & abgeleitete Status ===================

def favor(world: World, a: EntityId, b: EntityId) -> float:
    """favor der gerichteten Kante a -> b (fehlende Kante = neutral = 0.0)."""
    rel = world.relations.get((a, b))
    return rel.favor if rel is not None else 0.0


def dependency(world: World, a: EntityId, b: EntityId) -> float:
    """Handels-Abhaengigkeit der Kante a -> b: Anteil von a's Bedarf, den b deckt.

    Vom ``trade``-System gefuellt (Aenderung 5); fehlende Kante = 0.0. Speist als
    benannter Faktor die Zielwahl (siehe ``_score_ressource_sichern``).
    """
    rel = world.relations.get((a, b))
    return rel.dependency if rel is not None else 0.0


def add_favor(world: World, a: EntityId, b: EntityId, delta: float) -> None:
    """Haenge ein favor-Delta an die Kante a -> b (Gefallen +, Groll -).

    Die EINE zentrale Schreibstelle fuer alle Systeme (Diplomatie, Krieg,
    Abspaltung, Schisma, ...); geklammert auf [-1, +1].
    """
    if a == b or delta == 0.0:
        return
    rel = world.relations.get((a, b), Relation())
    world.relations[(a, b)] = replace(rel, favor=_clamp(rel.favor + delta))


def allied(world: World, a: EntityId, b: EntityId, cfg: Config) -> bool:
    """Abgeleiteter Buendnis-Status: beidseitiger favor ueber der Schwelle.

    Kein gespeichertes Flag: der Status folgt der Matrix und kippt im selben
    Tick, in dem favor die Schwelle kreuzt (das Event meldet der naechste
    diplomacy-Lauf).
    """
    return (
        favor(world, a, b) >= cfg.alliance_favor_threshold
        and favor(world, b, a) >= cfg.alliance_favor_threshold
    )


def hostile(world: World, a: EntityId, b: EntityId, cfg: Config) -> bool:
    """Abgeleiteter Feindschafts-Status: schon einseitiger Groll vergiftet das Paar."""
    return min(favor(world, a, b), favor(world, b, a)) <= cfg.enmity_favor_threshold


def _allies_of(world: World, pid: EntityId, cfg: Config) -> list[EntityId]:
    """Stabil sortierte Liste der aktuell Verbuendeten (pro Tick abgeleitet)."""
    return [q for q in sorted(world.polities) if q != pid and allied(world, pid, q, cfg)]


# === Subsistenz & Demografie (Phase 1, an neue Signatur angepasst) ==========

def founding(world: World, rng: Stream, cfg: Config, log: EventLog) -> World:
    """Emittiere ein GRUENDUNG-Event fuer jede in diesem Jahr gegruendete Nation."""
    for pid in sorted(world.polities):
        pol = world.polities[pid]
        if pol.founded_year == world.year:
            log.append(
                EventDraft(
                    year=world.year,
                    kind=EventKind.GRUENDUNG,
                    subjects=(pid,),
                    factors=(Factor(FactorLabel.WELTGENERIERUNG, 1.0),),
                    effects=(Effect(pid, "capital", None, pol.capital),),
                )
            )
    return world


def ruler(world: World, rng: Stream, cfg: Config, log: EventLog) -> World:
    """Herrscher altern und sterben; Sukzession (und ggf. Fragmentierung) folgt.

    Effektive Traits = Basis + Delta des lebenden Herrschers; alle nachgelagerten
    KI-Systeme nutzen sie. Stirbt ein Herrscher, wird **im selben Tick** ein
    Nachfolger eingesetzt (kein Interregnum), und der Sukzessions-Event verweist
    kausal auf den Tod. Bei schwacher Legitimitaet kann eine Sukzessionskrise das
    Reich fragmentieren — die Abspaltung verweist kausal auf die Sukzession.
    """
    # ``sorted`` liefert einen Snapshot: eine waehrend der Schleife per
    # Fragmentierung neu entstandene Polity wird erst naechstes Jahr verarbeitet.
    for pid in sorted(world.polities):
        pol = world.polities[pid]
        death_event = _age_and_maybe_die(world, pol, cfg, log)
        current = world.rulers.get(pol.leader) if pol.leader is not None else None
        if current is not None and current.alive:
            continue
        # Kein lebender Herrscher mehr ⇒ Sukzession. Ursache ist der juengste Tod
        # (dieses Jahr natuerlich gestorben oder zuvor in einem Krieg gefallen).
        if death_event is None:
            death_event = _recent_subject_event(
                log, world.year, EventKind.TOD_FIGUR, pid, cfg.cause_window_years
            )
        succ_event, new_ruler = _succeed(world, pol, rng, cfg, log, death_event)
        _maybe_fragment(world, pol, new_ruler, succ_event, rng, cfg, log)
    return world


def production(world: World, rng: Stream, cfg: Config, log: EventLog) -> World:
    """Territorium erzeugt die drei Bestaende — ohne einen einzigen Wuerfelwurf.

    Bis Aenderung 7 schwankte die Ernte jaehrlich per ``rng.uniform`` um die Kapazitaet,
    und DAS war die Quelle des Hungers: die Hungersnot — und mit ihr der Volksdruck, der
    Aufstand, der halbe Spannungsapparat — hing letztlich an einem Wurf. Jetzt ist die
    Ernte, was das Land hergibt, und der Hunger ist **malthusianisch**: die Bevoelkerung
    waechst logistisch bis an die Tragfaehigkeit und sitzt dann auf der Kante, gerade
    satt. Faellt die Tragfaehigkeit — verlorenes Land nach einem Krieg oder einer
    Abspaltung, vernarbte Kapazitaet nach einem Beben —, bleiben die Muender, und das
    Reich hungert, bis es sich auf sein neues Land zurueckgehungert hat. Die Hungersnot
    ist damit keine Laune des Wetters mehr, sondern der Preis einer Niederlage.

    Die zweite Schranke ist die **Arbeit** (Liebigsches Minimum, ``labor``): nur Arbeiter
    bestellen das Feld; wer Soldat oder Adliger wird, isst weiter, erzeugt aber nichts.
    Sie bindet selten (gemessen: ~1% der Nation-Jahre) — erst wenn eine Nation ihre
    Arbeiter regelrecht ausgeraeumt hat, wird sie zur zweiten Hungerquelle.
    """
    for pid in sorted(world.polities):
        pol = world.polities[pid]
        efficiency = 1.0 + pol.tech_level * cfg.tech_production_bonus
        # Eisen entsteht nur in Regionen mit Vorkommen (Aenderung 5): eisenarme
        # Nationen muessen es importieren oder erobern — die Quelle der Abhaengigkeit.
        iron_regions = sum(1 for r in pol.territory if world.regions[r].iron_rich)
        land = _land_capacity(world, pol, cfg)
        required = land * cfg.workers_per_capacity
        workers = _stratum_size(pol, StratumKind.ARBEITER)
        labor = min(1.0, workers / required) if required > 0.0 else 0.0
        s = pol.stocks
        pol.stocks = replace(
            s,
            getreide=s.getreide + land * efficiency * labor,
            eisen=s.eisen + iron_regions * cfg.iron_per_region * efficiency,
            gold=s.gold + _gold_income(pol, cfg),
        )
    return world


def consumption(world: World, rng: Stream, cfg: Config, log: EventLog) -> World:
    """Bevoelkerung isst Getreide, der Staat zahlt seine Pflichten; Reste verderben.

    Zwei Abfluesse, dieselbe Struktur: die Bevoelkerung isst (Rest verdirbt, Getreide
    ist schlecht lagerbar), und der Schatz zahlt Sold und Nothilfe (Aenderung 6).
    Damit ist Gold endlich ein echter Bestand mit Zu- UND Abfluss — vorher wuchs er
    nur, und ein Fiskaldruck haette nie entstehen koennen. Was der Staat nicht zahlen
    kann, bleibt ungezahlt; gemessen wird die Klemme in ``_fiskaldruck``.
    """
    for pid in sorted(world.polities):
        pol = world.polities[pid]
        need = bevoelkerung(pol) * cfg.food_per_person
        getreide = pol.stocks.getreide
        if getreide >= need:
            getreide -= need
            pol.food_deficit = 0.0
        else:
            pol.food_deficit = need - getreide
            getreide = 0.0
        storage_cap = cfg.food_storage_factor * _land_capacity(world, pol, cfg)
        gold = pol.stocks.gold
        pol.stocks = replace(
            pol.stocks,
            getreide=min(getreide, storage_cap),
            gold=gold - min(gold, _staatspflichten(pol, cfg)),
        )
    return world


def _gold_income(pol: Polity, cfg: Config) -> float:
    """Jaehrliche Gold-Foerderung des Territoriums (die EINE Wahrheit darueber).

    ``production`` foerdert sie, ``_fiskaldruck`` misst die Pflichten daran.
    """
    efficiency = 1.0 + pol.tech_level * cfg.tech_production_bonus
    return len(pol.territory) * cfg.gold_per_region * efficiency


def _staatspflichten(pol: Polity, cfg: Config) -> float:
    """Jaehrliche Pflichten des Staates in Gold: Sold + Hof + Nothilfe.

    Die EINE Wahrheit darueber, was der Schatz zu tragen hat — ``consumption`` zahlt
    danach, ``_fiskaldruck`` misst die Luecke daran. Drei Glieder, drei Kopplungen:

    * **Sold** je Soldat — Ruestung kostet, und der Krieg treibt die Rekrutierung.
    * **Hof** je Elite-Kopf — die Elite "verlangt Gold/Luxus" (Konzept §2.1). Dieses
      Glied ist der Motor des saekularen Zyklus: die Elite waechst durch Kriegsgewinn,
      die Foerderung waechst nur mit dem Territorium — also holt die Rechnung des Hofes
      die Kasse irgendwann ein. Die Fiskalkrise kommt SPAET im Leben eines Reiches,
      nach den siegreichen Kriegen, nicht am Anfang. Genau Turchin.
    * **Nothilfe** je Einheit Getreidedefizit — Brot in der Hungersnot. Sie verknuepft
      die Missernte mit den Staatsfinanzen: eine Hungersnot ist auch eine Fiskalkrise.
    """
    return (
        _stratum_size(pol, StratumKind.SOLDAT) * cfg.gold_upkeep_per_soldier
        + _stratum_size(pol, StratumKind.ELITE) * cfg.elite_gold_claim
        + pol.food_deficit * cfg.famine_relief_cost
    )


# === Handel und Abhaengigkeit (Aenderung 5) =================================

# Feste Reihenfolge der drei handelbaren Bestaende (Determinismus der Fluesse).
_TRADE_RESOURCES: tuple[str, ...] = ("getreide", "eisen", "gold")


def trade(world: World, rng: Stream, cfg: Config, log: EventLog) -> World:
    """Benachbarte Nationen tauschen Ueberschuss gegen Defizit; daraus waechst Abhaengigkeit.

    Rein und deterministisch, **ohne** RNG: fuer jede der drei Ressourcen fliesst
    Ueberschuss (Bestand ueber dem Bedarf) zu Defizit (Bestand unter dem Bedarf)
    entlang der Grenz-Kanten des Adjazenzgraphen (bis ``trade_max_distance``
    Spruenge, mit Distanz-Daempfung). Der Fluss ist reine **Umverteilung** — je
    Ressource bleibt die Weltsumme erhalten (keine Erzeugung aus dem Nichts).
    ``favor`` steuert die Praeferenz (offene Feinde handeln nicht, Freunde mehr);
    keine Nation gibt unter ihren eigenen Bedarf ab, keine nimmt ueber ihn hinaus.

    Der Handel laeuft direkt nach der Produktion: importiertes Getreide kann noch
    dieselbe Hungersnot abwenden, importiertes Eisen/Gold hebt noch dieses Jahr die
    Schlagkraft. Aus den Fluessen wird die ``dependency`` der Beziehungs-Matrix
    fortgeschrieben — der Stoff, aus dem "Krieg aus Handelsverflechtung" entsteht.
    """
    pids = sorted(world.polities)
    if len(pids) < 2:
        return world

    dist = _trade_distances(world, pids, cfg)
    need = {
        pid: {r: _trade_need(world.polities[pid], r, cfg) for r in _TRADE_RESOURCES}
        for pid in pids
    }
    have = {
        pid: {r: getattr(world.polities[pid].stocks, r) for r in _TRADE_RESOURCES}
        for pid in pids
    }
    # imported[b][r][a] = wie viel b in diesem Jahr von a an Ressource r erhielt.
    imported: dict[EntityId, dict[str, dict[EntityId, float]]] = {
        pid: {r: {} for r in _TRADE_RESOURCES} for pid in pids
    }

    for r in _TRADE_RESOURCES:
        for a in pids:  # a als Exporteur seines Ueberschusses
            if have[a][r] - need[a][r] <= cfg.trade_min_flow:
                continue
            for b in _trade_partners(world, a, pids, dist, cfg):
                avail = have[a][r] - need[a][r]
                if avail <= cfg.trade_min_flow:
                    break  # Ueberschuss von a erschoepft
                deficit = need[b][r] - have[b][r]
                if deficit <= cfg.trade_min_flow:
                    continue
                scale = _trade_volume_scale(world, a, b, dist[(a, b)], cfg)
                flow = cfg.trade_rate * min(avail, deficit) * scale
                if flow <= cfg.trade_min_flow:
                    continue
                have[a][r] -= flow
                have[b][r] += flow
                imported[b][r][a] = imported[b][r].get(a, 0.0) + flow

    for pid in pids:
        h = have[pid]
        pol = world.polities[pid]
        pol.stocks = replace(
            pol.stocks, getreide=h["getreide"], eisen=h["eisen"], gold=h["gold"]
        )

    _update_dependency(world, pids, need, imported, cfg)
    return world


def _trade_distances(
    world: World, pids: list[EntityId], cfg: Config
) -> dict[tuple[EntityId, EntityId], int]:
    """Grenz-Sprung-Distanz zwischen Territorien (nur Paare <= ``trade_max_distance``).

    Multi-Source-BFS ueber den Regionsgraphen von jedem Territorium aus: direkte
    Nachbarn liegen bei Distanz 1, ein Land dazwischen bei 2 (Gueter transitieren).
    Rein aus der Adjazenz — die Koordinaten bleiben kosmetisch. Distanz ist
    symmetrisch; je gerichtetem Paar gespeichert fuer den direkten Zugriff.
    """
    max_d = cfg.trade_max_distance
    dist: dict[tuple[EntityId, EntityId], int] = {}
    for a in pids:
        territory = world.polities[a].territory
        hops: dict[EntityId, int] = {rid: 0 for rid in territory}
        reached: dict[EntityId, int] = {}
        frontier = sorted(territory)
        d = 0
        while frontier and d < max_d:
            d += 1
            nxt: list[EntityId] = []
            for rid in frontier:
                for nb in world.regions[rid].nachbarn:
                    if nb in hops:
                        continue
                    hops[nb] = d
                    nxt.append(nb)
                    owner = world.regions[nb].owner
                    if owner is not None and owner != a and owner not in reached:
                        reached[owner] = d
            frontier = sorted(nxt)
        for b, hd in reached.items():
            dist[(a, b)] = hd
    return dist


def _trade_need(pol: Polity, resource: str, cfg: Config) -> float:
    """Jahresbedarf an einer handelbaren Ressource (Basis von Ueberschuss/Defizit).

    Getreide ernaehrt die Bevoelkerung, Eisen ruestet die Soldaten, Gold besoldet
    sie — dieselben Schwellen, die Hunger (``consumption``) und Schlagkraft
    (``_power``) lesen. Gold traegt zusaetzlich eine unantastbare Schatz-Reserve,
    damit der Handel den Expansions-Kriegskasten nicht wegspuelt.
    """
    if resource == "getreide":
        return bevoelkerung(pol) * cfg.food_per_person
    soldiers = _stratum_size(pol, StratumKind.SOLDAT)
    if resource == "eisen":
        return soldiers * cfg.iron_per_soldier
    return soldiers * cfg.gold_per_soldier + cfg.trade_gold_reserve


def _trade_partners(
    world: World,
    a: EntityId,
    pids: list[EntityId],
    dist: dict[tuple[EntityId, EntityId], int],
    cfg: Config,
) -> list[EntityId]:
    """Handelspartner von a in Reichweite, nach Praeferenz sortiert (Determinismus).

    Offene Feinde (``hostile``) sind ausgeschlossen — Krieg kappt den Handel. Sonst
    zuerst die wohlgesonnensten (hoechster favor), bei Gleichstand die kleinste
    ``EntityId``: so bekommt der bevorzugte Partner den knappen Ueberschuss zuerst.
    """
    partners = [
        b for b in pids if b != a and (a, b) in dist and not hostile(world, a, b, cfg)
    ]
    partners.sort(key=lambda b: (-favor(world, a, b), b))
    return partners


def _trade_volume_scale(
    world: World, a: EntityId, b: EntityId, hops: int, cfg: Config
) -> float:
    """Volumen-Faktor der Kante a -> b: Distanz-Daempfung mal favor-Praeferenz (0..1)."""
    decay = cfg.trade_distance_decay ** (hops - 1)
    preference = _clamp01(cfg.trade_favor_base + cfg.trade_favor_bias * favor(world, a, b))
    return decay * preference


def _update_dependency(
    world: World,
    pids: list[EntityId],
    need: dict[EntityId, dict[str, float]],
    imported: dict[EntityId, dict[str, dict[EntityId, float]]],
    cfg: Config,
) -> None:
    """Schreibe ``dependency`` je Kante als zerfallende **Akkumulation** der Reliance fort.

    Reliance-Fluss(b -> a) = groesster Anteil eines Jahresbedarfs von b, den a in
    diesem Jahr deckte (imported/need, ueber die drei Ressourcen das Maximum). Die
    dependency akkumuliert diesen Fluss und zerfaellt zugleich:

        dep' = clamp01( dep * (1 - decay) + reliance_fluss )

    So baut *anhaltende* Lieferung eine echte, bleibende Abhaengigkeit auf (ein
    Zufluss von decay je Jahr saettigt sie), waehrend das Ausbleiben der Lieferung
    sie ueber Jahre zerfallen laesst — genau das Fenster, in dem "Krieg aus
    Handelsverflechtung" gegen den nun gekappten Lieferanten entsteht. Dieselbe
    akkumulierende Gedaechtnis-Struktur wie ``favor`` (Aenderung 3), nur ohne
    Vorzeichen. Nur nach (a,b) sortiert iteriert (Matrix-Determinismus); winzige
    Werte schnappen auf 0, damit die neutrale Kante entfallen kann (sparse).
    """
    reliance: dict[tuple[EntityId, EntityId], float] = {}
    for b in pids:
        for r in _TRADE_RESOURCES:
            need_r = need[b][r]
            if need_r <= cfg.trade_min_flow:
                continue
            for a, amount in imported[b][r].items():
                key = (b, a)
                reliance[key] = max(reliance.get(key, 0.0), amount / need_r)

    for key in sorted(set(world.relations) | set(reliance)):
        old = world.relations.get(key)
        old_dep = old.dependency if old is not None else 0.0
        new_dep = _clamp01(old_dep * (1.0 - cfg.dependency_decay) + reliance.get(key, 0.0))
        if new_dep < cfg.dependency_epsilon:
            new_dep = 0.0
        if old is None:
            if new_dep > 0.0:
                world.relations[key] = Relation(dependency=new_dep)
        elif new_dep != old.dependency:
            world.relations[key] = replace(old, dependency=new_dep)


def _supplier_risk(world: World, a: EntityId, y: EntityId, cfg: Config) -> float:
    """Wie gefaehrlich es ist, von Y abzuhaengen: Misstrauen (neg. favor) + Y's Unruhe.

    Ein feindlicher Lieferant kann die Versorgung als Waffe einsetzen, ein innerlich
    instabiler kann sie unfreiwillig verlieren — beides macht die Abhaengigkeit
    riskant und den Griff nach der eigenen Quelle rational (0..1).
    """
    distrust = max(0.0, -favor(world, a, y))
    instability = _volksgroll(world.polities[y], cfg)
    return _clamp01(distrust + instability)


def demografie(world: World, rng: Stream, cfg: Config, log: EventLog) -> World:
    """Wachstum/Schrumpfung je Schicht, Rekrutierung Arbeiter→Soldat, Hungersnot.

    Logistisches Wachstum gilt fuer die Gesamtbevoelkerung gegen die Tragfaehigkeit
    des Landes und wird proportional auf die Schichten verteilt (die Zusammensetzung
    bleibt, bis die Rekrutierung sie verschiebt). Getreidemangel toetet anteilig ueber
    alle Schichten. Meilensteine feuern auf die abgeleitete Gesamtbevoelkerung.
    """
    for pid in sorted(world.polities):
        pol = world.polities[pid]
        before = bevoelkerung(pol)
        if before <= 0:
            continue

        if pol.food_deficit > 0.0:
            _starve(world, pol, before, cfg, log)
            continue

        _grow(world, pol, before, cfg, log)
        _recruit(pol, cfg)
    return world


def _starve(
    world: World, pol: Polity, before: int, cfg: Config, log: EventLog
) -> None:
    """Hungersnot: verteile die Toten anteilig ueber alle Schichten."""
    deaths = min(before, int(pol.food_deficit * cfg.famine_deaths_per_deficit))
    if deaths <= 0:
        return
    pol.strata = _scaled_strata(pol.strata, 1.0 - deaths / before)
    log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.HUNGERSNOT,
            subjects=(pol.id,),
            factors=(Factor(FactorLabel.NAHRUNGSDEFIZIT, pol.food_deficit),),
            effects=(Effect(pol.id, "population", before, bevoelkerung(pol)),),
        )
    )


def _grow(
    world: World, pol: Polity, before: int, cfg: Config, log: EventLog
) -> None:
    """Logistisches Wachstum, proportional auf die Schichten verteilt; Meilensteine."""
    efficiency = 1.0 + pol.tech_level * cfg.tech_production_bonus
    capacity = _land_capacity(world, pol, cfg) * efficiency / cfg.food_per_person
    if capacity <= 0:
        return
    factor = cfg.growth_rate * (1.0 - before / capacity)
    if factor <= 0.0:
        return
    pol.strata = tuple(replace(s, size=s.size * (1.0 + factor)) for s in pol.strata)
    after = bevoelkerung(pol)
    crossed = [m for m in cfg.population_milestones if pol.peak_population < m <= after]
    if after > pol.peak_population:
        pol.peak_population = after
    for _ in crossed:
        log.append(
            EventDraft(
                year=world.year,
                kind=EventKind.BEVOELKERUNG_MEILENSTEIN,
                subjects=(pol.id,),
                factors=(Factor(FactorLabel.BEVOELKERUNGSWACHSTUM, float(after - before)),),
                effects=(Effect(pol.id, "population", before, after),),
            )
        )


def _recruit(pol: Polity, cfg: Config) -> None:
    """Verschiebe Arbeiter↔Soldat homoeostatisch zum angestrebten Soldaten-Anteil.

    Ohne Zufall: der Bruchteil ``recruit_rate`` der Luecke zum Zielanteil wird je Jahr
    geschlossen. Rekrutierung zieht Arbeiter aus der Getreideproduktion, Demobilisierung
    gibt sie zurueck — die Guns-versus-Butter-Kopplung.

    Das erklaerte Ziel steuert den Zielanteil: wer ums Ueberleben ringt, schickt
    Soldaten zurueck aufs Feld. Da die Zielwahl spaeter im Tick laeuft, wirkt die
    Politik des Vorjahres — eine bewusste, deterministische Verzoegerung.
    """
    total = sum(s.size for s in pol.strata)
    if total <= 0.0:
        return
    workers = _stratum_size(pol, StratumKind.ARBEITER)
    soldiers = _stratum_size(pol, StratumKind.SOLDAT)
    fraction = cfg.target_soldier_fraction
    if pol.goal is GoalKind.UEBERLEBEN:
        fraction *= cfg.retrench_soldier_fraction
    delta = cfg.recruit_rate * (fraction * total - soldiers)
    # Nie mehr rekrutieren als Arbeiter da sind, nie mehr demobilisieren als Soldaten.
    delta = min(delta, workers) if delta > 0.0 else -min(-delta, soldiers)
    if delta == 0.0:
        return
    pol.strata = tuple(
        replace(s, size=s.size - delta)
        if s.kind == StratumKind.ARBEITER
        else replace(s, size=s.size + delta)
        if s.kind == StratumKind.SOLDAT
        else s
        for s in pol.strata
    )


def _promote_elite(pol: Polity, rate: float) -> None:
    """Hebe einen Anteil der Bevoelkerung aus den Arbeitern in die Elite (Aenderung 6).

    Der zweite Kanal sozialer Mobilitaet neben ``_recruit`` — und der einzige, der den
    Elite-Anteil HEBT (alle uebrigen senken ihn: Purge, Abspaltung, Deklassierung im
    Bankrott). Ihn nutzt der Sieger eines Krieges (Kriegsgewinner-Adel, Konzept §3.3):
    die Bevoelkerung bleibt gleich, aber sie schichtet sich um. Weil Aemter und Pfruenden
    nicht mitwachsen, ist der frisch gewonnene Adel der Keim der naechsten Krise (siehe
    ``_elitendruck``); zugleich fehlen die Befoerderten auf dem Feld (die Elite baut kein
    Getreide an) — der Sieg hat einen Preis.
    """
    gain = min(rate * bevoelkerung(pol), _stratum_size(pol, StratumKind.ARBEITER))
    if gain <= 0.0:
        return
    pol.strata = tuple(
        replace(s, size=s.size - gain)
        if s.kind == StratumKind.ARBEITER
        else replace(s, size=s.size + gain)
        if s.kind == StratumKind.ELITE
        else s
        for s in pol.strata
    )


def grievance(world: World, rng: Stream, cfg: Config, log: EventLog) -> World:
    """Baue den Groll je Schicht auf; zerfalle sonst langsam. KEINE Entladung.

    Groll steigt bei Getreidemangel (Verelendung der unteren Schichten) und bei
    ungleichem Wohlstandsanteil (haelt eine Schicht weniger als ihren Bevoelkerungs-
    Anteil). Ohne Druck zerfaellt er Richtung 0. Nur die Groesse baut sich auf —
    Aufstaende folgen mit Aenderung 6. Reine Zustandsfortschreibung, kein Event.
    """
    for pid in sorted(world.polities):
        pol = world.polities[pid]
        total = sum(s.size for s in pol.strata)
        if total <= 0.0:
            continue
        need = total * cfg.food_per_person
        hunger = min(1.0, pol.food_deficit / need) if need > 0.0 else 0.0
        new_strata: list[Stratum] = []
        for s in pol.strata:
            pressure = 0.0
            # Verelendung trifft die unteren Schichten (Arbeiter/Soldat), nicht die Elite.
            if s.kind != StratumKind.ELITE:
                pressure += cfg.grievance_hunger_rate * hunger
            # Ungleichheit: haelt die Schicht weniger Wohlstand als ihren Groessen-Anteil?
            shortfall = max(0.0, s.size / total - s.wealth_share)
            pressure += cfg.grievance_inequality_rate * shortfall
            g = s.grievance * (1.0 - cfg.grievance_decay) + pressure
            new_strata.append(replace(s, grievance=min(cfg.grievance_cap, max(0.0, g))))
        pol.strata = tuple(new_strata)
    return world


# === Konflikt & Diplomatie (Phase 2) ========================================

def friction(world: World, rng: Stream, cfg: Config, log: EventLog) -> World:
    """Akkumuliere Grenzreibung zwischen rivalisierenden Nachbarn ueber Jahre.

    Reibung waechst staerker unter Ressourcendruck. Beim Ueberschreiten einer
    Stufe wird ein (geringwertiges) GRENZREIBUNG-Event eingehaengt — diese Events
    sind die spaeter zitierten Ursachen des Kriegswunsches.
    """
    for pid in sorted(world.polities):
        pol = world.polities[pid]
        pressure = 1.0 + (1.0 if pol.food_deficit > 0.0 else 0.0)
        for other in _bordering_nations(world, pol):
            if allied(world, pid, other, cfg):
                continue
            growth = cfg.friction_growth * pressure
            # Offene Feindschaft (abgeleitet aus dem Groll der Matrix) laesst
            # die Reibung schneller wachsen — Rachezyklen, bis der Groll verblasst.
            if hostile(world, pid, other, cfg):
                growth *= 1.0 + cfg.hostility_friction_bonus
            before = pol.friction.get(other, 0.0)
            after = min(before + growth, cfg.friction_cap)
            pol.friction[other] = after
            if int(after / cfg.friction_event_step) > int(before / cfg.friction_event_step):
                log.append(
                    EventDraft(
                        year=world.year,
                        kind=EventKind.GRENZREIBUNG,
                        subjects=(pid, other),
                        factors=(Factor(FactorLabel.GRENZREIBUNG, after),),
                    )
                )
    return world


def diplomacy(world: World, rng: Stream, cfg: Config, log: EventLog) -> World:
    """Furcht neu berechnen; favor zerfaellt und driftet; Status-Wechsel melden.

    Buendnis ist kein gespeichertes Flag: gemeinsame Furcht vor dem Staerksten
    (Balance of Power) und friedliche Nachbarschaft bauen favor auf, der
    jaehrliche Zerfall traegt ihn ab; der Status wird pro Tick aus den Schwellen
    abgeleitet. Kippt er gegenueber dem zuletzt im Log gemeldeten Stand, wird
    BUENDNIS bzw. BUENDNIS_BRUCH emittiert. Diese Quellen sind **ambient**
    (Nachbarschaft, gemeinsame Furcht); den gezielten Gefallen legt die Nation
    obendrauf, wenn sie das Ziel VERBUENDEN waehlt (siehe ``goals``). Verschwindet
    der gemeinsame Feind und bleibt die Werbung aus, sinkt das Band durch den
    Zerfall von selbst unter die Schwelle — und alter Groll verblasst, bis Feinde
    wieder neutral sind.
    """
    pids = sorted(world.polities)
    powers = {pid: _power(world.polities[pid], cfg) for pid in pids}
    strongest = max(pids, key=lambda p: (powers[p], -p))

    _recompute_fear(world, pids, powers, cfg)
    _decay_favor(world, cfg)
    _drift_favor(world, cfg)
    _cooperate_against_hegemon(world, pids, strongest, cfg)
    _emit_alliance_flips(world, pids, strongest, cfg, log)
    return world


# === Spannung und Entladung (Aenderung 6) ===================================

# Deklarationsreihenfolge der vier Druecke. Sie bricht Gleichstaende bei der Wahl
# der dominanten Komponente (Determinismus-Vertrag) und ist die Reihenfolge, in der
# ``spannung`` die Faktorsumme akkumuliert (Float-Reproduzierbarkeit).
_TENSION_ORDER: tuple[str, ...] = (
    FactorLabel.VOLKSDRUCK,
    FactorLabel.ELITENDRUCK,
    FactorLabel.FISKALDRUCK,
    FactorLabel.AUSSENDRUCK,
)

# Das Ereignis, das jeden Druck naehrt — zitiert wird es nur, wenn der Druck steht.
_TENSION_CAUSE: dict[str, EventKind] = {
    # Die Hungersnot ist es, die das Volk erzuernt.
    FactorLabel.VOLKSDRUCK: EventKind.HUNGERSNOT,
    # Der Krieg treibt die Elite — von BEIDEN Seiten: der Sieg schafft die Gewinner-
    # Elite (``_promote_elite``), die Niederlage nimmt der bestehenden ihre Aemter
    # (verlorenes Land). Darum zaehlt die Schlacht fuer Sieger wie Verlierer.
    FactorLabel.ELITENDRUCK: EventKind.SCHLACHT,
    # Das Erdbeben frisst den Schatz: der exogene Schock laeuft durch die Spannung.
    FactorLabel.FISKALDRUCK: EventKind.ERDBEBEN,
    # Die Reibung an der Grenze, die dem aeusseren Druck vorausgeht.
    FactorLabel.AUSSENDRUCK: EventKind.GRENZREIBUNG,
}


def spannung(world: World, pol: Polity, cfg: Config, log: EventLog) -> Decision:
    """Die Spannung einer Nation als Summe der VIER benannten Druecke (reine Funktion).

    Nach der Strukturell-Demografischen Theorie — und damit keine undurchsichtige
    Instabilitaets-Zahl, sondern eine Liste, die sagt, WORAN eine Zivilisation leidet:

        Volksdruck   Groll der unteren Schichten (Getreidemangel + ungleicher
                     Wohlstandsanteil naehren ihn; siehe ``grievance``)
        Elitendruck  Eliten-Ueberproduktion: mehr Anwaerter als Aemter und Pfruenden
        Fiskaldruck  Staatspflichten (Sold + Nothilfe) gegen die Mittel des Schatzes
        Aussendruck  riskante Handels-Abhaengigkeit + Einkreisung durch offene Grolle

    Jede Komponente ist auf 0..1 normiert, damit die Gewichte der Config vergleichbar
    sind (dieselbe Disziplin wie in der Zielwahl). Die zurueckgegebene Faktorliste IST
    die Begruendung: exakt sie haengt unveraendert an der Entladung. Ein Druck von 0
    faellt heraus und nimmt seine Ursachen mit — er hat nichts erklaert; darum wird das
    Log fuer ihn erst gar nicht durchsucht (die drei letzten stehen meist auf 0).
    """
    weights = _tension_weights(cfg)
    decision = Decision()
    for label, raw in (
        (FactorLabel.VOLKSDRUCK, _volksgroll(pol, cfg)),
        (FactorLabel.ELITENDRUCK, _elitendruck(pol, cfg)),
        (FactorLabel.FISKALDRUCK, _fiskaldruck(pol, cfg)),
        (FactorLabel.AUSSENDRUCK, _aussendruck(world, pol, cfg)),
    ):
        pressure = weights[label] * raw
        if pressure == 0.0:
            continue
        decision.add(
            label,
            pressure,
            causes=_recent_subject_event_all(
                log, world.year, _TENSION_CAUSE[label], pol.id, cfg.cause_window_years
            ),
        )
    return decision


def tension(world: World, rng: Stream, cfg: Config, log: EventLog) -> World:
    """Berechne je Nation die Spannung; ueber der Schwelle entlaedt sie sich.

    Der Kern von Aenderung 6: innere Umbrueche entstehen aus akkumuliertem Druck, der
    an einer Schwelle bricht — nicht aus Zufalls-Triggern. Die DOMINANTE Komponente
    waehlt die Art:

        Volksdruck  ⇒ AUFSTAND   — Umverteilung
        Elitendruck ⇒ ABSPALTUNG (teilbares Reich) oder PUTSCH (unteilbares)
        Fiskaldruck ⇒ BANKROTT   — der Staat entlaesst, was er nicht bezahlen kann
        Aussendruck ⇒ KRIEG      — die einzige Entladung nach AUSSEN; sie wird nicht
                                   hier vollzogen, sondern von der Zielwahl (``goals``,
                                   gleich danach im selben Tick). Die Spannung liefert
                                   das Motiv als benannten Faktor, die Utility waehlt
                                   das Ziel — es bleibt bei EINEM Kriegspfad.
        extrem + zusammengesetzt ⇒ KOLLAPS — Zerfall in Nachfolgestaaten

    Jede Entladung ENTLASTET ihren eigenen Druck und saet einen anderen (Konzept §3.3).
    Darum rotiert das System durch die Krisentypen — saekulare Zyklen — statt in einen
    Fixpunkt zu laufen. ``sorted`` liefert einen Snapshot: eine hier entstandene
    Nachfolge-Nation kommt erst naechstes Jahr an die Reihe.
    """
    for pid in sorted(world.polities):
        pol = world.polities[pid]
        decision = spannung(world, pol, cfg, log)
        # ``pol.tension`` ist die Lage, unter der die Nation in DIESEM Jahr handelt —
        # dieselbe Rechnung, die auch das Entladungs-Event begruendet. Sie bleibt bis
        # zur naechsten Bewertung stehen: der Zustand darf dem Event nicht widersprechen,
        # und ein Verlauf, der den Gipfel wegkuerzt, zeigte die Krise nicht mehr, die er
        # zeigen soll. Was die Entladung entlastet hat, sagt das naechste Jahr.
        pol.tension = _tension_of(decision)
        # Ohne Faktoren gibt es keine dominante Komponente — und nichts zu begruenden.
        if decision.factors and decision.passes(cfg.tension_threshold):
            _entlade(world, pol, decision, rng, cfg, log)
    return world


# --- die vier Druecke (je auf 0..1 normiert) ---------------------------------
#
# Volksdruck ist ``_volksgroll`` (groessengewichteter Groll der unteren Schichten):
# dieselbe Groesse, die schon die Zielwahl und ``_supplier_risk`` lesen — es gibt kein
# zweites Groll-Mass.


def _kronmittel(pol: Polity, cfg: Config) -> float:
    """Was die Krone in einem Jahr aufbringen kann: Foerderung + angezapfter Schatz.

    Die EINE Wahrheit ueber die Mittel des Staates. Sie ist stets positiv (Territorium
    foerdert Gold) — das ist wichtig: ein Mass, das mit dem Schatz auf 0 faellt, saette
    jeden davon abgeleiteten Druck auf sein Maximum, egal wie klein Heer oder Adel
    waeren. Der Schatz ist der Puffer, die Foerderung der Boden.
    """
    return _gold_income(pol, cfg) + pol.stocks.gold / cfg.fiscal_buffer_years


def _elitendruck(pol: Polity, cfg: Config) -> float:
    """Eliten-Ueberproduktion: Anteil der Elite ohne Amt und ohne Pfruende (0..1).

    Eine Elite traegt zweierlei: die **Aemter**, die das Land hergibt, und die
    **Pfruenden**, die die Krone aufbringen kann (``_kronmittel`` geteilt durch den
    Anspruch eines Kopfes). Es bindet die knappere der beiden Schranken (Liebigsches
    Minimum, wie in ``production``) — die Elite braucht Rang UND Auskommen.

    Die Elite waechst mit der Bevoelkerung und durch Kriegsgewinn (siehe
    ``_wage_war``); die Aemter wachsen nur mit dem Territorium, die Pfruenden nur mit
    den Mitteln der Krone. Die Schere IST der Druck: verlorenes Land, versiegende
    Mittel und siegreiche Kriege oeffnen sie — Purge, Abspaltung und Kollaps schliessen
    sie wieder.
    """
    elite = _stratum_size(pol, StratumKind.ELITE)
    if elite <= 0.0:
        return 0.0
    posts = len(pol.territory) * cfg.elite_posts_per_region
    prebends = (
        _kronmittel(pol, cfg) / cfg.elite_gold_claim if cfg.elite_gold_claim > 0.0 else 0.0
    )
    return _clamp01((elite - min(posts, prebends)) / elite)


def _fiskaldruck(pol: Polity, cfg: Config) -> float:
    """Fiskaldruck: wie weit die Staatspflichten die Mittel der Krone uebersteigen (0..1).

    Ein struktureller Fehlbetrag ist der Druck. Weil er an den *Pflichten* haengt (nicht
    am Kassenstand), senkt ihn der Bankrott SOFORT: entlassene Soldaten kosten keinen
    Sold mehr. Und weil der Hof in den Pflichten steckt, senkt ihn auch der Putsch —
    ein gestutzter Adel ist eine kleinere Rechnung. Die beiden inneren Krisen greifen
    also ineinander, statt sich zu blockieren.
    """
    duty = _staatspflichten(pol, cfg)
    if duty <= 0.0:
        return 0.0
    return _clamp01(1.0 - _kronmittel(pol, cfg) / duty)


def _aussendruck(world: World, pol: Polity, cfg: Config) -> float:
    """Aeusserer Druck: riskante Abhaengigkeit + Einkreisung durch offene Grolle (0..1).

    Zwei Quellen, genau die des Konzepts (§3.1). (a) Von einem feindlichen oder
    innerlich instabilen Lieferanten abzuhaengen — Aenderung 5 liefert beide Groessen.
    (b) Die **Einkreisung**: der Anteil der Nachbarn, mit denen offene Feindschaft
    besteht.

    Die Einkreisung zaehlt Feinde (abgeleitet aus dem Groll der Matrix), NICHT die
    Grenzreibung. Das ist ein Unterschied ums Ganze: Reibung waechst zwischen je zwei
    Rivalen ohnehin und liegt bald dauerhaft an ihrer Obergrenze — sie waere ein
    stehender Sockel, der die Spannung permanent nahe an die Schwelle druecken wuerde,
    bis nur noch die Sperre die Krisen taktete. Feindschaft dagegen kommt und geht, weil
    ``favor`` zerfaellt (die Vergebung): Einkreisung ist ein Zustand, aus dem man
    wieder herauskommt — und damit ein Druck, der sich aufbauen UND abbauen kann.
    """
    pid = pol.id
    reliance = max(
        (
            dependency(world, pid, y) * _supplier_risk(world, pid, y, cfg)
            for y in sorted(world.polities)
            if y != pid
        ),
        default=0.0,
    )
    neighbors = _bordering_nations(world, pol)
    enemies = sum(1 for y in neighbors if hostile(world, pid, y, cfg))
    encirclement = enemies / len(neighbors) if neighbors else 0.0
    return _clamp01(
        cfg.tension_dependency_share * reliance + cfg.tension_grudge_share * encirclement
    )


# --- Spannung als reine Daten: Summe, Dominanz, Kollaps-Test ------------------


def _tension_of(decision: Decision) -> Tension:
    """Die vier Gewichte der Faktorliste als reine Daten (fuer Zielwahl und Ansicht).

    Kein zweites Modell und keine zweite Rechnung: exakt die Zahlen, aus denen die
    Faktorliste besteht. Ein Druck, den ``Decision`` als 0 verworfen hat, ist hier 0.
    """
    weights = {f.label: f.weight for f in decision.factors}
    return Tension(
        volk=weights.get(FactorLabel.VOLKSDRUCK, 0.0),
        elite=weights.get(FactorLabel.ELITENDRUCK, 0.0),
        fiskal=weights.get(FactorLabel.FISKALDRUCK, 0.0),
        aussen=weights.get(FactorLabel.AUSSENDRUCK, 0.0),
    )


def _tension_total(t: Tension) -> float:
    """Der Spannungs-Score: Summe der vier Druecke in Deklarationsreihenfolge."""
    return t.volk + t.elite + t.fiskal + t.aussen


def _tension_parts(t: Tension) -> dict[str, float]:
    """Die vier Druecke einer Nation als Abbildung Label -> Wert (feste Reihenfolge)."""
    return {
        FactorLabel.VOLKSDRUCK: t.volk,
        FactorLabel.ELITENDRUCK: t.elite,
        FactorLabel.FISKALDRUCK: t.fiskal,
        FactorLabel.AUSSENDRUCK: t.aussen,
    }


def _tension_weights(cfg: Config) -> dict[str, float]:
    """Die vier Gewichte der Config als Abbildung Label -> Gewicht.

    Sie stehen genau hier: ``spannung`` multipliziert damit, ``_raw_pressures``
    dividiert sie wieder heraus. Liefen die beiden auseinander, wuerden die Rohwerte
    luegen — und mit ihnen der Kollaps-Test, der an ihnen haengt.
    """
    return {
        FactorLabel.VOLKSDRUCK: cfg.tension_volk_weight,
        FactorLabel.ELITENDRUCK: cfg.tension_elite_weight,
        FactorLabel.FISKALDRUCK: cfg.tension_fiskal_weight,
        FactorLabel.AUSSENDRUCK: cfg.tension_aussen_weight,
    }


def _dominant(t: Tension) -> str:
    """Die dominante Komponente: groesster Wert, Gleichstand nach Deklarationsreihenfolge."""
    parts = _tension_parts(t)
    return min(_TENSION_ORDER, key=lambda label: (-parts[label], _TENSION_ORDER.index(label)))


def _raw_pressures(t: Tension, cfg: Config) -> list[float]:
    """Die vier Druecke zurueck auf ihre 0..1-Rohwerte gerechnet (ohne Gewicht).

    Nur so ist "dieser Druck steht hoch" ueber die Komponenten hinweg vergleichbar:
    die Gewichte sagen, wie sehr ein Druck ZAEHLT, nicht wie hoch er STEHT.
    """
    parts, weights = _tension_parts(t), _tension_weights(cfg)
    return [
        parts[label] / weights[label] if weights[label] > 0.0 else 0.0
        for label in _TENSION_ORDER
    ]


def _is_kollaps(t: Tension, cfg: Config) -> bool:
    """Zusammengesetzte Extremkrise: sehr hohe Spannung, von MEHREREN Druecken getragen.

    Ein einzelner Druck, so hoch er auch stehen mag, entlaedt sich in seiner eigenen
    Art. Erst wenn das Reich an mehreren Fronten ZUGLEICH reisst, faellt es auseinander
    — nur dann waehlt keine einzelne Komponente mehr. Gemessen wird an den Rohwerten,
    nicht an den Gewichten: sonst koennte ein leicht gewichteter Druck (Aussendruck) die
    Schwelle nie erreichen und der Kollaps waere unerreichbar.
    """
    if _tension_total(t) < cfg.collapse_threshold:
        return False
    carrying = sum(
        1 for raw in _raw_pressures(t, cfg) if raw >= cfg.collapse_component_floor
    )
    return carrying >= cfg.collapse_min_components


# --- die Entladungen ---------------------------------------------------------


def _entlade(
    world: World,
    pol: Polity,
    decision: Decision,
    rng: Stream,
    cfg: Config,
    log: EventLog,
) -> bool:
    """Vollziehe die Entladung: die dominante Komponente waehlt die Art.

    Gibt zurueck, ob sich der Druck wirklich entladen hat — nur dann ist die Sperre
    verbraucht und der Zustand der Nation ein anderer als vorher.
    """
    t = pol.tension
    kollaps = _is_kollaps(t, cfg) and len(pol.territory) >= cfg.collapse_min_territory

    # Der Aussendruck entlaedt sich nach AUSSEN — es sei denn, das Reich reisst ohnehin
    # an allen Fronten (dann gilt der Kollaps). Sein Ereignis ist der KRIEG, den die
    # Zielwahl gleich danach vollzieht (siehe ``_krisendruck``) und den die Kriegs-
    # muedigkeit bremst. Hier gibt es keinen inneren Bruch — und darum auch keine
    # Sperre zu verbrauchen.
    if not kollaps and _dominant(t) == FactorLabel.AUSSENDRUCK:
        return False

    # Refraktaer: eine eben erschuetterte Gesellschaft bricht nicht schon im naechsten
    # Jahr erneut — der Druck muss sich erst wieder aufbauen. Ohne diese Sperre
    # flackerte dieselbe Nation im Dreijahrestakt durch Putsche, statt Zyklen zu
    # durchlaufen: sie ist es, die aus dem Auf und Ab einen ZYKLUS macht.
    if world.year - pol.last_crisis < cfg.crisis_cooldown_years:
        return False

    if kollaps:
        if not _kollaps(world, pol, decision, rng, cfg, log):
            return False  # kein Reichsteil abtrennbar: es ist nichts geschehen
    else:
        dominant = _dominant(t)
        if dominant == FactorLabel.VOLKSDRUCK:
            _aufstand(world, pol, decision, cfg, log)
        elif dominant == FactorLabel.ELITENDRUCK:
            _elitenkrise(world, pol, decision, rng, cfg, log)
        else:  # FISKALDRUCK
            _bankrott(world, pol, decision, cfg, log)
    pol.last_crisis = world.year
    return True


def _aufstand(
    world: World, pol: Polity, decision: Decision, cfg: Config, log: EventLog
) -> None:
    """Volksdruck entlaedt sich: Aufstand, Umverteilung, gepluenderter Schatz.

    ENTLASTUNG des eigenen Drucks, doppelt: der aufgestaute Groll bricht sich Bahn und
    faellt auf einen Restanteil — UND der Wohlstand wird umverteilt, was die
    Ungleichheit senkt, die den Groll ueberhaupt naehrt. Er bleibt also laenger unten,
    statt sofort wieder hochzulaufen (das ist die Laenge des Zyklus).

    FOLGEWIRKUNG: der Schatz wird gepluendert (⇒ Fiskaldruck) und Soldaten wie Adel
    bluten (⇒ das Reich steht entbloesst da — die Nachbarn lesen die Schwaeche in
    ``_weakness`` und fallen ueber es her). So saet der Aufstand die naechste Krise
    anderer Art.
    """
    pop_before = bevoelkerung(pol)
    gold_before = pol.stocks.gold
    elite_wealth_before = _elite_wealth(pol.strata)

    # Der Groll entlaedt sich, und die Elite gibt Wohlstand ab.
    pol.strata = _relieve_grievance(pol.strata, cfg.revolt_grievance_relief)
    pol.strata = _shift_wealth(pol.strata, -cfg.revolt_redistribution)
    # Die Rechnung: gepluenderter Schatz, gefallene Soldaten und Adlige.
    pol.stocks = replace(pol.stocks, gold=gold_before * (1.0 - cfg.revolt_gold_loss))
    pol.strata = _cull(pol.strata, StratumKind.SOLDAT, cfg.revolt_soldier_losses)
    pol.strata = _cull(pol.strata, StratumKind.ELITE, cfg.revolt_elite_losses)

    log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.AUFSTAND,
            subjects=(pol.id,),
            factors=decision.as_factors(),
            causes=decision.as_causes(),
            effects=(
                Effect(pol.id, "elite_wealth", elite_wealth_before, _elite_wealth(pol.strata)),
                Effect(pol.id, "gold", gold_before, pol.stocks.gold),
                Effect(pol.id, "population", pop_before, bevoelkerung(pol)),
            ),
        )
    )


def _elitenkrise(
    world: World,
    pol: Polity,
    decision: Decision,
    rng: Stream,
    cfg: Config,
    log: EventLog,
) -> None:
    """Elitendruck entlaedt sich: die ueberzaehlige Elite nimmt sich einen Staat — oder purgiert.

    Ein teilbares Reich zerbricht an ihr (ABSPALTUNG): die ueberzaehligen Anwaerter
    gruenden ihr eigenes Land und sind unter den Auswanderern ueberrepraesentiert
    (``secession_elite_bias``) — genau das entlastet die Mutter. Ein unteilbares Reich
    frisst sie von innen (PUTSCH).
    """
    if len(pol.territory) >= cfg.secession_min_territory:
        blob = _carve_breakaway(world, pol)
        if blob:
            pop_before = bevoelkerung(pol)
            child, capital, effects = _secede(
                world, pol, blob, rng, cfg, elite_bias=cfg.secession_elite_bias
            )
            effects.append(Effect(pol.id, "population", pop_before, bevoelkerung(pol)))
            log.append(
                EventDraft(
                    year=world.year,
                    kind=EventKind.ABSPALTUNG,
                    subjects=(pol.id, child.id, capital),
                    factors=decision.as_factors(),
                    causes=decision.as_causes(),
                    effects=tuple(effects),
                )
            )
            return
    _putsch(world, pol, decision, rng, cfg, log)


def _putsch(
    world: World,
    pol: Polity,
    decision: Decision,
    rng: Stream,
    cfg: Config,
    log: EventLog,
) -> None:
    """Elitendruck ohne Ventil: die Elite stuerzt den Herrscher und purgiert sich selbst.

    ENTLASTUNG: die unterlegene Faktion wird purgiert — die Elite schrumpft, der Druck
    faellt sofort.
    FOLGEWIRKUNG: die Sieger greifen nach dem Wohlstand (⇒ die Ungleichheit steigt,
    der Volksgroll waechst ueber die naechsten Jahre), und auf dem Thron sitzt ein
    Usurpator mit schwacher Legitimitaet — die bestehende Sukzessionskrise kann daran
    das Reich spalten (der Buergerkrieg des Konzepts, ohne eine Zeile neuer Mechanik).
    """
    elite_before = _stratum_size(pol, StratumKind.ELITE)
    pol.strata = _cull(pol.strata, StratumKind.ELITE, cfg.coup_elite_purge)
    pol.strata = _shift_wealth(pol.strata, cfg.coup_wealth_grab)

    rid = pol.leader
    fallen = world.rulers.get(rid) if rid is not None else None
    subjects: tuple[EntityId, ...] = (pol.id,) if rid is None else (pol.id, rid)
    putsch_id = log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.PUTSCH,
            subjects=subjects,
            factors=decision.as_factors(),
            causes=decision.as_causes(),
            effects=(
                Effect(pol.id, "elite", elite_before, _stratum_size(pol, StratumKind.ELITE)),
            ),
        )
    )
    if rid is None or fallen is None or not fallen.alive:
        return

    # Der gestuerzte Herrscher faellt; der Usurpator folgt noch im selben Tick (der
    # ``ruler``-Lauf ist vorbei — kein Tick endet ohne lebenden Herrscher).
    fallen.alive = False
    death_id = log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.TOD_FIGUR,
            subjects=(pol.id, rid),
            factors=(Factor(FactorLabel.ELITENDRUCK, pol.tension.elite),),
            causes=(putsch_id,),
            effects=(Effect(rid, "alive", True, False),),
        )
    )
    succ_event, new_ruler = _succeed(
        world, pol, rng, cfg, log, death_id, mode=AccessionMode.USURPED
    )
    _maybe_fragment(world, pol, new_ruler, succ_event, rng, cfg, log)


def _bankrott(
    world: World, pol: Polity, decision: Decision, cfg: Config, log: EventLog
) -> None:
    """Fiskaldruck entlaedt sich: der Staat entlaesst, was er nicht bezahlen kann.

    ENTLASTUNG, auf BEIDEN Seiten der Rechnung: die Soldaten, deren Sold die Kasse nicht
    traegt, kehren aufs Feld zurueck — und das Gefolge, dessen Pfruende die Krone nicht
    mehr aufbringt, faellt aus dem Stand. Das zweite Glied ist das entscheidende: der Hof
    ist der groesste Posten der Pflichten, der Sold der kleinste. Ein Bankrott, der nur
    das Heer verkleinert, senkte seine eigene Rechnung um wenige Prozent — er waere gar
    keine Entladung. Und weil beide Gruppen wieder Getreide erzeugen, sinkt ueber die
    naechsten Jahre auch das dritte Glied der Pflichten (die Nothilfe).

    FOLGEWIRKUNG: bezahlt wird der Rest mit Zwangsabgaben — der Groll der unteren
    Schichten steigt. Und die Deklassierten sinken in eben diese Schichten, ohne dass
    deren Wohlstandsanteil mitwuechse: mehr Koepfe teilen dasselbe wenige, die
    Ungleichheit je Kopf steigt und mit ihr, ueber die naechsten Jahre, der Volksdruck
    (⇒ Aufstand). Der verarmte Adel ist der Zuender der naechsten Krise anderer Art —
    und das entbloesste Heer laedt die Nachbarn ein.
    """
    soldiers_before = _stratum_size(pol, StratumKind.SOLDAT)
    elite_before = _stratum_size(pol, StratumKind.ELITE)
    released = soldiers_before * cfg.bankruptcy_demobilization
    dismissed = elite_before * cfg.bankruptcy_dismissal
    # Die Entlassenen verschwinden nicht: sie werden (wieder) Arbeiter.
    pol.strata = tuple(
        replace(s, size=s.size - released)
        if s.kind == StratumKind.SOLDAT
        else replace(s, size=s.size - dismissed)
        if s.kind == StratumKind.ELITE
        else replace(s, size=s.size + released + dismissed)
        if s.kind == StratumKind.ARBEITER
        else s
        for s in pol.strata
    )
    pol.strata = _aggrieve(pol.strata, cfg.bankruptcy_levy_grievance, cfg)

    log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.BANKROTT,
            subjects=(pol.id,),
            factors=decision.as_factors(),
            causes=decision.as_causes(),
            effects=(
                Effect(
                    pol.id,
                    "soldiers",
                    soldiers_before,
                    _stratum_size(pol, StratumKind.SOLDAT),
                ),
                Effect(
                    pol.id,
                    "elite",
                    elite_before,
                    _stratum_size(pol, StratumKind.ELITE),
                ),
            ),
        )
    )


def _kollaps(
    world: World,
    pol: Polity,
    decision: Decision,
    rng: Stream,
    cfg: Config,
    log: EventLog,
) -> bool:
    """Die zusammengesetzte Extremkrise: das Reich zerfaellt in Nachfolgestaaten.

    Keine einzelne Komponente traegt das mehr — das Reich reisst an mehreren Fronten
    zugleich. Es gibt Reichsteile ab, bis nur ein Rumpf bleibt, und mit der alten
    Ordnung gehen auch der alte Adel und der alte Groll: Rumpf wie Nachfolger starten
    mit gebrochener Elite und weitgehend entladenem Groll. Das ist die Entlastung —
    sie trifft ALLE Druecke, denn alle hatten das Reich zerrissen.

    Gibt zurueck, ob der Zerfall stattfand: laesst sich kein Reichsteil abtrennen,
    ist nichts geschehen — dann darf er auch die Sperre nicht verbrauchen.
    """
    pop_before = bevoelkerung(pol)
    effects: list[Effect] = []
    successors: list[EntityId] = []
    while (
        len(successors) < cfg.collapse_max_successors
        and len(pol.territory) >= cfg.collapse_min_territory
    ):
        blob = _carve_breakaway(world, pol)
        if not blob:
            break
        child, _capital, child_effects = _secede(
            world, pol, blob, rng, cfg, elite_bias=cfg.secession_elite_bias
        )
        successors.append(child.id)
        effects.extend(child_effects)
        _sweep_away_old_order(child, cfg)
    if not successors:  # kein Reichsteil abtrennbar ⇒ keine Entladung dieser Art
        return False

    _sweep_away_old_order(pol, cfg)
    effects.append(Effect(pol.id, "population", pop_before, bevoelkerung(pol)))
    log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.KOLLAPS,
            subjects=(pol.id, *successors),
            factors=decision.as_factors(),
            causes=decision.as_causes(),
            effects=tuple(effects),
        )
    )
    return True


def _sweep_away_old_order(pol: Polity, cfg: Config) -> None:
    """Der Kollaps fegt die alte Ordnung fort: gebrochene Elite, entladener Groll."""
    pol.strata = _cull(pol.strata, StratumKind.ELITE, cfg.collapse_elite_purge)
    pol.strata = _relieve_grievance(pol.strata, cfg.collapse_grievance_relief)


# --- Schichten-Helfer der Entladungen ----------------------------------------


def _elite_wealth(strata: tuple[Stratum, ...]) -> float:
    """Wohlstandsanteil der Elite (0..1)."""
    return next((s.wealth_share for s in strata if s.kind == StratumKind.ELITE), 0.0)


def _cull(strata: tuple[Stratum, ...], kind: StratumKind, rate: float) -> tuple[Stratum, ...]:
    """Verkleinere EINE Schicht um einen Anteil (die Verluste einer Entladung)."""
    if rate <= 0.0:
        return strata
    return tuple(
        replace(s, size=max(0.0, s.size * (1.0 - rate))) if s.kind == kind else s
        for s in strata
    )


def _relieve_grievance(strata: tuple[Stratum, ...], keep: float) -> tuple[Stratum, ...]:
    """Der Groll der unteren Schichten entlaedt sich auf den Restanteil ``keep``."""
    return tuple(
        replace(s, grievance=s.grievance * keep) if s.kind != StratumKind.ELITE else s
        for s in strata
    )


def _aggrieve(strata: tuple[Stratum, ...], amount: float, cfg: Config) -> tuple[Stratum, ...]:
    """Hebe den Groll der unteren Schichten (Zwangsabgaben), gedeckelt wie immer."""
    return tuple(
        replace(s, grievance=min(cfg.grievance_cap, s.grievance + amount))
        if s.kind != StratumKind.ELITE
        else s
        for s in strata
    )


def _shift_wealth(strata: tuple[Stratum, ...], to_elite: float) -> tuple[Stratum, ...]:
    """Verschiebe Wohlstandsanteil zwischen unteren Schichten und Elite.

    ``to_elite > 0``: die Elite greift zu (Putsch) — die Ungleichheit steigt und mit
    ihr, ueber die naechsten Jahre, der Volksgroll. ``to_elite < 0``: die Elite gibt ab
    (Aufstand) — die Umverteilung, die den Groll dauerhaft daempft.

    Verschoben wird hoechstens, was die abgebende Seite wirklich haelt; damit bleiben
    alle Anteile in [0, 1] und summieren weiterhin zu 1 (Invariante). Der ZUGRIFF nimmt
    anteilig zum Besitz — wo nichts ist, ist nichts zu holen. Die UMVERTEILUNG gibt
    anteilig zur Kopfzahl, denn genau das ist der gerechte Anteil, an dem sich der Groll
    misst (``grievance``: Groesse/Gesamt gegen ``wealth_share``). Sie darf sich nicht am
    Besitz orientieren: eine total enteignete Unterschicht haelt 0 und bekaeme dann
    anteilig 0 zurueck — die vollstaendige Enteignung waere ein Zustand, aus dem kein
    Aufstand mehr herausfuehrt.
    """
    lower = [s for s in strata if s.kind != StratumKind.ELITE]
    grab = to_elite > 0.0
    keys = {s.kind: (s.wealth_share if grab else s.size) for s in lower}
    total = sum(keys.values())
    if total <= 0.0:  # niemand, der geben koennte — bzw. niemand, der lebte
        return strata
    shift = (
        min(to_elite, sum(s.wealth_share for s in lower))
        if grab
        else -min(-to_elite, _elite_wealth(strata))
    )
    if shift == 0.0:
        return strata
    return tuple(
        replace(s, wealth_share=s.wealth_share + shift)
        if s.kind == StratumKind.ELITE
        else replace(s, wealth_share=max(0.0, s.wealth_share - shift * keys[s.kind] / total))
        for s in strata
    )


# === Utility-basierte Zielwahl (Aenderung 4) ================================

# Die Deklarationsreihenfolge des Zielmenues bricht Gleichstaende im argmax.
_GOAL_ORDER: dict[GoalKind, int] = {kind: i for i, kind in enumerate(GoalKind)}
# Ziele, die in einen Krieg muenden (beide vollziehen ihn ueber ``_wage_war``).
_WAR_GOALS = (GoalKind.RESSOURCE_SICHERN, GoalKind.GROLL_VERGELTEN)


@dataclass(frozen=True)
class _GoalChoice:
    """Ein bewertetes Ziel: seine Art, seine Faktorsumme und sein Objekt.

    ``target`` ist die ``EntityId``, auf die sich das Ziel richtet (Region bei
    WACHSEN, Nation bei Krieg/Buendnis) — bei UEBERLEBEN gibt es keine.
    """

    kind: GoalKind
    decision: Decision
    target: EntityId | None = None


def goals(world: World, rng: Stream, cfg: Config, log: EventLog) -> World:
    """Jede Nation waehlt gierig ihr Ziel (argmax) und verfolgt es sofort.

    Ein Schritt, myopisch, ohne Suche und ohne Vorausplanung: jedes erfuellbare
    Ziel des festen Menues wird als Summe **benannter Faktoren** bewertet
    (Trait des Herrschers mal Situation), das hoechstbewertete gewaehlt und im
    selben Tick vollzogen. Die exakt verwendete Faktorliste haengt am
    resultierenden Event — sie IST die Begruendung.

    Dieses System hat die frueheren Systeme ``expansion`` und ``war`` abgeloest:
    Expansion und Krieg sind Vollzuege eines gewaehlten Ziels, keine eigenstaendig
    geschwellten Reaktionen mehr ("ist Aggression hoch?" → "welches Ziel sichert
    jetzt am besten Ueberleben/Wachstum?"). Pro Tick fuehrt eine Nation hoechstens
    einen Krieg; ein bereits verwickelter Gegner wird nicht erneut angegriffen.
    """
    pids = sorted(world.polities)
    powers = {pid: _power(world.polities[pid], cfg) for pid in pids}
    strongest = max(pids, key=lambda p: (powers[p], -p))
    busy: set[EntityId] = set()

    for pid in pids:
        choice = _choose_goal(world, pid, powers, strongest, busy, cfg, log)
        world.polities[pid].goal = choice.kind
        _pursue_goal(world, pid, choice, busy, rng, cfg, log)
    return world


def _goal_rank(choice: _GoalChoice) -> tuple[float, int, int]:
    """Sortierschluessel des argmax (kleinster gewinnt).

    Hoechster Score zuerst; bei Gleichstand die Reihenfolge des Zielmenues,
    danach die ``EntityId`` des Ziel-Objekts (Determinismus-Vertrag).
    """
    target = choice.target if choice.target is not None else -1
    return (-choice.decision.score, _GOAL_ORDER[choice.kind], target)


def _choose_goal(
    world: World,
    pid: EntityId,
    powers: dict[EntityId, float],
    strongest: EntityId,
    busy: set[EntityId],
    cfg: Config,
    log: EventLog,
) -> _GoalChoice:
    """argmax ueber das Zielmenue; nur *erfuellbare* Ziele stehen zur Wahl.

    Erfuellbarkeit ist keine Schwelle, sondern eine Vorbedingung der Handlung
    (kein freies Feld, kein Angriffsziel, kein Mangel zu decken). UEBERLEBEN ist
    stets erfuellbar und traegt den Grundnutzen ``Beharrung`` — es ist die Option
    "abwarten", gegen die sich jede Handlung erst lohnen muss.
    """
    targets = _war_targets(world, pid, busy, cfg)
    menu = [_score_ueberleben(world, pid, cfg)]
    for candidate in (
        _score_wachsen(world, pid, cfg),
        _score_ressource_sichern(world, pid, targets, powers, cfg, log),
        _score_groll_vergelten(world, pid, targets, powers, cfg, log),
        _score_verbuenden(world, pid, strongest, cfg),
    ):
        if candidate is not None:
            menu.append(candidate)
    return min(menu, key=_goal_rank)


def _pursue_goal(
    world: World,
    pid: EntityId,
    choice: _GoalChoice,
    busy: set[EntityId],
    rng: Stream,
    cfg: Config,
    log: EventLog,
) -> None:
    """Vollziehe das gewaehlte Ziel; die Faktorliste wandert ans Event."""
    target = choice.target
    if target is None:  # UEBERLEBEN: kein Feld, kein Krieg, keine Werbung.
        return
    if choice.kind is GoalKind.WACHSEN:
        _expand(world, pid, target, choice.decision, cfg, log)
    elif choice.kind in _WAR_GOALS:
        _wage_war(world, pid, target, choice.decision, rng, cfg, log)
        busy.add(pid)
        busy.add(target)
    elif choice.kind is GoalKind.VERBUENDEN:
        _court(world, pid, target, cfg)


# --- die fuenf Ziele des Menues ---------------------------------------------

def _score_ueberleben(world: World, pid: EntityId, cfg: Config) -> _GoalChoice:
    """Auf sich selbst zurueckziehen: Hunger, Unmut und Furcht wiegen schwer.

    Stets erfuellbar und damit der Nullpunkt des Menues; der Grundnutzen
    ``Beharrung`` ist die Traegheit des Status quo.
    """
    pol = world.polities[pid]
    et = _effective_traits(world, pol)
    decision = Decision()
    decision.add(FactorLabel.BEHARRUNG, cfg.goal_status_quo)
    decision.add(FactorLabel.NAHRUNGSDEFIZIT, cfg.goal_hunger_weight * _hunger(pol, cfg))
    decision.add(FactorLabel.VOLKSGROLL, cfg.goal_unrest_weight * _volksgroll(pol, cfg))
    decision.add(FactorLabel.FURCHT, cfg.goal_fear_weight * _dread(pol, cfg))
    decision.add(FactorLabel.VORSICHT, cfg.goal_caution_weight * et.caution)
    return _GoalChoice(GoalKind.UEBERLEBEN, decision)


def _score_wachsen(world: World, pid: EntityId, cfg: Config) -> _GoalChoice | None:
    """Ein freies Nachbarfeld beanspruchen — erfuellbar nur mit Land und Gold."""
    pol = world.polities[pid]
    affordable = pol.stocks.gold - cfg.expand_gold_cost
    if affordable < 0.0:
        return None
    target = _free_neighbor(world, pol)
    if target is None:
        return None

    capacity = _land_capacity(world, pol, cfg)
    surplus = pol.stocks.getreide / capacity if capacity > 0 else 0.0
    et = _effective_traits(world, pol)
    decision = Decision()
    decision.add(FactorLabel.EXPANSIONSDRANG, et.expansion)
    decision.add(FactorLabel.NAHRUNGSUEBERSCHUSS, surplus)
    decision.add(FactorLabel.WOHLSTAND, min(affordable / cfg.expand_gold_cost, 1.0))
    decision.add(FactorLabel.VORSICHT, -et.caution * 0.5)
    return _GoalChoice(GoalKind.WACHSEN, decision, target)


def _score_ressource_sichern(
    world: World,
    pid: EntityId,
    targets: list[EntityId],
    powers: dict[EntityId, float],
    cfg: Config,
    log: EventLog,
) -> _GoalChoice | None:
    """Die fehlende Ressource beim Nachbarn holen: Mangel treibt, Beute lockt.

    Erfuellbar nur bei echtem Mangel — man kann keine Ressource sichern, die man
    nicht braucht. Damit entsteht dieser Krieg **nachweisbar aus der
    Ressourcenlage**. Der stehende Antrieb ist die *Landnot* (Bevoelkerung gegen
    Tragfaehigkeit), nicht die akute Hungersnot: wer schon verhungert, ist zu
    geschwaecht zum Erobern und zieht sich zurueck (UEBERLEBEN). Hunger und
    Eisenbedarf verstaerken; die Fruchtbarkeit des erreichbaren Feldes waehlt das
    Ziel. Ein weiterer Mangel ist die **Handelsabhaengigkeit** (Aenderung 5): von
    einem feindlichen/instabilen Lieferanten abhaengig zu sein, treibt gezielt den
    Krieg gegen genau diesen Lieferanten — so entsteht Krieg aus Handelsverflechtung.
    """
    pol = world.polities[pid]
    pressure = _land_pressure(world, pol, cfg)
    hunger = _hunger(pol, cfg)
    iron_gap = _iron_gap(pol, cfg)
    # Eine riskante Abhaengigkeit oeffnet das Ziel auch ohne rohen Eigenmangel:
    # von einem gefaehrlichen Lieferanten abzuhaengen IST ein zu deckender Mangel.
    dependence = max(
        (dependency(world, pid, y) * _supplier_risk(world, pid, y, cfg) for y in targets),
        default=0.0,
    )
    if pressure <= 0.0 and hunger <= 0.0 and iron_gap <= 0.0 and dependence <= 0.0:
        return None

    et = _effective_traits(world, pol)
    crisis = _krisendruck(pol, world.year, cfg)  # haengt an der Nation, nicht am Ziel
    best: _GoalChoice | None = None
    for y in targets:
        # Nur ein Ziel mit erreichbarem Feld kommt in Frage: eine Nation, die
        # ausser ihrer Hauptstadt nichts haelt, gibt kein Land her — ein Krieg um
        # Ressourcen waere gegen sie ein Krieg um nichts.
        prize = _contested_region(world, pid, y)
        if prize is None:
            continue
        weakness, weakness_causes = _weakness(world, pid, y, powers, cfg, log)
        decision = Decision()
        decision.add(FactorLabel.RESSOURCENDRUCK, cfg.goal_seize_weight * pressure)
        decision.add(FactorLabel.NAHRUNGSDEFIZIT, cfg.goal_famine_weight * hunger)
        decision.add(FactorLabel.EISENBEDARF, cfg.goal_iron_weight * iron_gap)
        # Der gezielte Faktor: Abhaengigkeit von genau diesem Nachbarn, gewichtet
        # mit seiner Gefaehrlichkeit (Misstrauen + Unruhe). Null (und damit aus der
        # Begruendung) fuer jeden Nicht-Lieferanten.
        decision.add(
            FactorLabel.HANDELSABHAENGIGKEIT,
            cfg.goal_dependency_weight
            * dependency(world, pid, y)
            * _supplier_risk(world, pid, y, cfg),
        )
        decision.add(FactorLabel.BEUTE, cfg.goal_prize_weight * _prize(world, pid, prize, cfg))
        decision.add(FactorLabel.AUSSENDRUCK, crisis)
        decision.add(FactorLabel.ZIEL_SCHWAECHE, weakness, causes=weakness_causes)
        decision.add(FactorLabel.MILITAERVORTEIL, _advantage(world, pid, y, powers, cfg))
        decision.add(FactorLabel.FURCHT, -pol.fear.get(y, 0.0))
        decision.add(FactorLabel.VORSICHT, -et.caution)
        best = _better_target(best, _GoalChoice(GoalKind.RESSOURCE_SICHERN, decision, y))
    return best


def _krisendruck(pol: Polity, year: int, cfg: Config) -> float:
    """Der Zuschlag der Aussendruck-Entladung auf die Kriegsziele (Aenderung 6).

    Steht die Spannung einer Nation ueber der Schwelle und ist der **Aussendruck** ihre
    dominante Komponente, dann muss sie nach aussen handeln — der Krieg IST ihre
    Entladung. Statt einen zweiten Kriegspfad zu bauen, legt die Spannung ihr Motiv als
    benannten Faktor auf die bestehende Zielwahl: die Utility waehlt das Ziel, der
    KRIEG-Event traegt den ``Aussendruck`` in seiner Begruendung. Unterhalb der
    Schwelle ist der Zuschlag 0 (und faellt damit aus der Faktorliste) — der aeussere
    Druck wirkt dann weiter ueber seine gewohnten Kanaele (Handelsabhaengigkeit,
    Misstrauen, Grenzreibung), nur eben nicht als Krise.

    Wer sich noch in diesem Jahr nach INNEN entladen hat, zieht nicht auch noch in den
    Krieg: die Spannung hatte ihr Ventil. Das trifft genau den Kollaps — er allein
    bricht ein Reich auch dann auf, wenn der aeussere Druck der dominante ist (er
    ueberstimmt die Dominanz). Ein eben zerfallenes Reich soll nicht im selben Jahr mit
    dem Zuschlag einer Krise angreifen, die es gerade zerrissen hat.
    """
    t = pol.tension
    if pol.last_crisis == year:
        return 0.0
    if _tension_total(t) < cfg.tension_threshold or _dominant(t) != FactorLabel.AUSSENDRUCK:
        return 0.0
    return cfg.goal_crisis_weight * t.aussen


def _score_groll_vergelten(
    world: World,
    pid: EntityId,
    targets: list[EntityId],
    powers: dict[EntityId, float],
    cfg: Config,
    log: EventLog,
) -> _GoalChoice | None:
    """Alte Rechnung begleichen: Groll aus der Matrix, Reibung an der Grenze.

    Das Gegenstueck zum Ressourcenkrieg — hier treibt das historische Gedaechtnis
    (negativer favor), nicht der Mangel.
    """
    pol = world.polities[pid]
    et = _effective_traits(world, pol)
    crisis = _krisendruck(pol, world.year, cfg)  # haengt an der Nation, nicht am Ziel
    best: _GoalChoice | None = None
    for y in targets:
        py = world.polities[y]
        et_y = _effective_traits(world, py)
        weakness, weakness_causes = _weakness(world, pid, y, powers, cfg, log)
        decision = Decision()

        # Das historische Gedaechtnis: Groll rechtfertigt den Krieg, Wohlwollen
        # daempft ihn — und beides verblasst ueber Jahrzehnte.
        goodwill = favor(world, pid, y)
        if goodwill < 0.0:
            decision.add(FactorLabel.MISSTRAUEN, -goodwill)
        else:
            decision.add(FactorLabel.VERTRAUEN, -goodwill * 0.5)
        decision.add(
            FactorLabel.GRENZREIBUNG,
            pol.friction.get(y, 0.0) * cfg.war_friction_weight,
            causes=_recent_pair_events(
                log, world.year, EventKind.GRENZREIBUNG, pid, y, cfg.cause_window_years
            ),
        )
        decision.add(FactorLabel.AGGRESSION, et.aggression)
        # Affinitaet (Phase 4): fremder Glaube rechtfertigt den Krieg leichter. Wird
        # dieser Faktor zum Hauptantrieb, gilt der Krieg als Glaubenskrieg (chronicle).
        if py.identity_id is not None and py.identity_id != pol.identity_id:
            decision.add(FactorLabel.GLAUBENSGRABEN, cfg.identity_war_friction)
        # Persoenliche Rivalitaet: zwei aggressive Herrscher heizen den Krieg an.
        if (
            et.aggression >= cfg.personal_aggression_threshold
            and et_y.aggression >= cfg.personal_aggression_threshold
        ):
            decision.add(FactorLabel.PERSOENLICHE_RIVALITAET, cfg.personal_rivalry_weight)
        # Aussendruck-Entladung (Aenderung 6): die Krise treibt auch die Vergeltung.
        decision.add(FactorLabel.AUSSENDRUCK, crisis)
        decision.add(FactorLabel.ZIEL_SCHWAECHE, weakness, causes=weakness_causes)
        decision.add(FactorLabel.MILITAERVORTEIL, _advantage(world, pid, y, powers, cfg))
        decision.add(FactorLabel.FURCHT, -pol.fear.get(y, 0.0))
        decision.add(FactorLabel.VORSICHT, -et.caution)
        best = _better_target(best, _GoalChoice(GoalKind.GROLL_VERGELTEN, decision, y))
    return best


def _score_verbuenden(
    world: World, pid: EntityId, strongest: EntityId, cfg: Config
) -> _GoalChoice | None:
    """Um einen Partner werben — die gewaehlte Balance of Power.

    Gemeinsame Furcht vor dem Staerksten ist der Hauptantrieb; Diplomatie-Trait,
    gleicher Glaube und gewachsenes Vertrauen verstaerken ihn. Offene Feinde sind
    keine Kandidaten; **bestehende Verbuendete sehr wohl**: ein Pakt lebt von der
    fortgesetzten Werbung. Bleibt sie aus (die gemeinsame Furcht ist verblasst),
    traegt der Zerfall den favor unter die Schwelle und das Buendnis endet.
    """
    pol = world.polities[pid]
    et = _effective_traits(world, pol)
    best: _GoalChoice | None = None
    for q in sorted(world.polities):
        if q == pid or hostile(world, pid, q, cfg):
            continue
        pq = world.polities[q]
        decision = Decision()
        decision.add(
            FactorLabel.GEMEINSAMER_FEIND,
            cfg.goal_coalition_weight * _common_dread(pol, pq, strongest, cfg),
        )
        decision.add(FactorLabel.DIPLOMATIE, et.diplomacy)
        if pol.identity_id is not None and pol.identity_id == pq.identity_id:
            decision.add(FactorLabel.GLAUBENSAFFINITAET, cfg.identity_alliance_bonus)
        # Gewachsenes Vertrauen bindet: es haelt die Werbung beim selben Partner
        # (kein jaehrliches Partner-Hopping), traegt allein aber kein Buendnis.
        decision.add(FactorLabel.VERTRAUEN, cfg.goal_loyalty_weight * favor(world, pid, q))
        best = _better_target(best, _GoalChoice(GoalKind.VERBUENDEN, decision, q))
    return best


def _better_target(best: _GoalChoice | None, candidate: _GoalChoice) -> _GoalChoice:
    """Bestes Objekt eines Ziels: hoechster Score, Gleichstand nach kleinster EntityId."""
    if best is None:
        return candidate
    return min((best, candidate), key=_goal_rank)


# --- Vollzug der Ziele ------------------------------------------------------

def _expand(
    world: World,
    pid: EntityId,
    region: EntityId,
    decision: Decision,
    cfg: Config,
    log: EventLog,
) -> None:
    """Vollzug von WACHSEN: das freie Nachbarfeld wird beansprucht."""
    pol = world.polities[pid]
    pol.stocks = replace(pol.stocks, gold=pol.stocks.gold - cfg.expand_gold_cost)
    world.regions[region].owner = pid
    pol.territory = tuple(sorted((*pol.territory, region)))
    log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.EXPANSION,
            subjects=(pid, region),
            factors=decision.as_factors(),
            causes=decision.as_causes(),
            effects=(Effect(region, "owner", None, pid),),
        )
    )


def _court(world: World, pid: EntityId, partner: EntityId, cfg: Config) -> None:
    """Vollzug von VERBUENDEN: ein Jahr Werbung ist ein Gefallen auf beiden Kanten.

    Kein eigenes Event — der Pakt selbst wird gemeldet, sobald der favor beider
    Seiten die Buendnis-Schwelle kreuzt (``diplomacy``); die Werbung ist der Weg
    dorthin, nicht das Ereignis.
    """
    add_favor(world, pid, partner, cfg.goal_courtship_favor)
    add_favor(world, partner, pid, cfg.goal_courtship_favor)


# --- situative Groessen der Zielbewertung -----------------------------------

def _hunger(pol: Polity, cfg: Config) -> float:
    """Not durch Getreidemangel, auf 0..1 normiert (0 = satt, 1 = volle Hungersnot).

    Bezug ist ``famine_reference``: fehlt dieser Bruchteil des Jahresbedarfs, gilt
    die Not als total. Ein Defizit von einem Fuenftel des Jahresbedarfs ist bereits
    eine Hungersnot mit Toten — die Groesse darf nicht linear bis 1.0 verduennt
    werden, sonst geht das Mangel-Signal im Rauschen unter.
    """
    need = bevoelkerung(pol) * cfg.food_per_person
    if need <= 0.0:
        return 0.0
    return min(1.0, pol.food_deficit / (need * cfg.famine_reference))


def _land_pressure(world: World, pol: Polity, cfg: Config) -> float:
    """Landnot: Bevoelkerung gegen die Tragfaehigkeit des eigenen Landes (0..1).

    0, solange Spielraum bleibt (unter ``land_pressure_onset``), 1, wenn die
    Bevoelkerung die Tragfaehigkeit erreicht. Das ist der **stehende**
    Ressourcendruck, aus dem Eroberungskriege erwachsen — anders als die akute
    Hungersnot, die eine bereits geschwaechte Nation zum Rueckzug zwingt.
    Expansion, Pest und Eroberung senken ihn, Wachstum hebt ihn: der Antrieb
    atmet mit der Demografie.
    """
    efficiency = 1.0 + pol.tech_level * cfg.tech_production_bonus
    capacity = _land_capacity(world, pol, cfg) * efficiency / cfg.food_per_person
    if capacity <= 0.0:
        return 1.0
    span = max(1e-9, 1.0 - cfg.land_pressure_onset)
    return _clamp01((bevoelkerung(pol) / capacity - cfg.land_pressure_onset) / span)


def _iron_gap(pol: Polity, cfg: Config) -> float:
    """Anteil der unbewaffneten Soldaten (0 = alle geruestet) — der Eisenbedarf."""
    soldiers = _stratum_size(pol, StratumKind.SOLDAT)
    if soldiers <= 0.0:
        return 0.0
    return max(0.0, 1.0 - pol.stocks.eisen / (soldiers * cfg.iron_per_soldier))


def _volksgroll(pol: Polity, cfg: Config) -> float:
    """Groessengewichteter Groll der unteren Schichten, normiert auf 0..1."""
    lower = [s for s in pol.strata if s.kind != StratumKind.ELITE]
    size = sum(s.size for s in lower)
    if size <= 0.0 or cfg.grievance_cap <= 0.0:
        return 0.0
    weighted = sum(s.grievance * s.size for s in lower) / size
    return min(1.0, weighted / cfg.grievance_cap)


def _dread(pol: Polity, cfg: Config) -> float:
    """Furcht vor der bedrohlichsten anderen Nation, normiert auf 0..1.

    Die Zielbewertung mischt situative Groessen additiv — deshalb muessen sie
    dieselbe Skala haben. ``Polity.fear`` laeuft bis ``fear_cap`` (3.0) und wuerde
    Hunger, Groll und Vorsicht (je 0..1) sonst schlicht ueberstimmen.
    """
    return max(pol.fear.values(), default=0.0) / cfg.fear_cap if cfg.fear_cap > 0 else 0.0


def _common_dread(pa: Polity, pb: Polity, strongest: EntityId, cfg: Config) -> float:
    """Gemeinsame Furcht zweier Nationen vor dem Staerksten, normiert auf 0..1."""
    common = min(pa.fear.get(strongest, 0.0), pb.fear.get(strongest, 0.0))
    return common / cfg.fear_cap if cfg.fear_cap > 0 else 0.0


def _prize(world: World, x: EntityId, region: EntityId, cfg: Config) -> float:
    """Fruchtbarkeit des erreichbaren Feldes — relativ zum eigenen Land (gedeckelt)."""
    px = world.polities[x]
    own_mean = _land_capacity(world, px, cfg) / max(len(px.territory), 1)
    if own_mean <= 0.0:
        return 0.0
    gain = world.regions[region].food_capacity * cfg.grain_per_capacity
    return min(gain / own_mean, cfg.goal_prize_cap)


def _advantage(
    world: World, x: EntityId, y: EntityId, powers: dict[EntityId, float], cfg: Config
) -> float:
    """Gedeckelter Machtvorsprung inklusive Verbuendeter (Balance of Power).

    Der Deckel haelt rohe Ueberlegenheit davon ab, ein endloser Kriegsgrund zu sein.
    """
    margin = _effective_power(world, x, powers, cfg) - _effective_power(world, y, powers, cfg)
    return _clamp(margin / cfg.power_reference, -cfg.advantage_cap, cfg.advantage_cap)


def _weakness(
    world: World,
    x: EntityId,
    y: EntityId,
    powers: dict[EntityId, float],
    cfg: Config,
    log: EventLog,
) -> tuple[float, list[EventId]]:
    """Wie verwundbar Y gerade ist: klar unterlegen und/oder eben verlassen."""
    weakness = 0.0
    causes: list[EventId] = []
    power_x = _power_of(world, x, powers, cfg)
    if _power_of(world, y, powers, cfg) < power_x * cfg.weakness_power_ratio:
        weakness += cfg.weakness_bonus
    ally_loss = _recent_subject_event(
        log, world.year, EventKind.BUENDNIS_BRUCH, y, cfg.cause_window_years
    )
    if ally_loss is not None:
        weakness += cfg.ally_loss_bonus
        causes.append(ally_loss)
    return weakness, causes


def _war_targets(
    world: World, pid: EntityId, busy: set[EntityId], cfg: Config
) -> list[EntityId]:
    """Angreifbare Nachbarn (stabil sortiert): kein Verbuendeter, keine Muedigkeit.

    Kriegsmuedigkeit und laufende Verwicklungen sind Vorbedingungen der Handlung,
    keine Entscheidungs-Schwellen — sie machen ein Kriegsziel schlicht unerfuellbar.
    """
    pol = world.polities[pid]
    if pid in busy:
        return []
    # Globale Kriegsmuedigkeit: nach einem Krieg ruht die Nation eine Weile.
    if pol.last_war and world.year - max(pol.last_war.values()) < cfg.war_global_cooldown_years:
        return []
    return [
        y
        for y in _bordering_nations(world, pol)
        if y not in busy
        and not allied(world, pid, y, cfg)
        and world.year - pol.last_war.get(y, -10_000) >= cfg.war_cooldown_years
    ]


def _wage_war(
    world: World,
    x: EntityId,
    y: EntityId,
    decision: Decision,
    rng: Stream,
    cfg: Config,
    log: EventLog,
) -> None:
    """Erklaere Krieg (KRIEG-Event), loese ihn per Machtvergleich (SCHLACHT) auf."""
    px, py = world.polities[x], world.polities[y]

    war_id = log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.KRIEG,
            subjects=(x, y),
            factors=decision.as_factors(),
            causes=decision.as_causes(),
        )
    )

    # Aufloesung: Vergleich der effektiven Macht (mit Verbuendeten) plus Jitter.
    powers = {p: _power(world.polities[p], cfg) for p in sorted(world.polities)}
    jitter = rng.uniform(-cfg.battle_jitter, cfg.battle_jitter)
    margin = (
        _effective_power(world, x, powers, cfg) - _effective_power(world, y, powers, cfg)
    ) / cfg.power_reference + jitter
    winner, loser = (x, y) if margin >= 0.0 else (y, x)
    pw, pl = world.polities[winner], world.polities[loser]

    loser_before = bevoelkerung(pl)
    pl.strata = _scaled_strata(pl.strata, 1.0 - cfg.war_loser_losses)
    pw.strata = _scaled_strata(pw.strata, 1.0 - cfg.war_winner_losses)
    # Ausruestung geht mit den Gefallenen verloren. Der Krieg ist der einzige
    # Abfluss des Eisenbestands: ohne ihn waere die Bewaffnung nach wenigen
    # Jahrzehnten dauerhaft gesaettigt, das Eisen ein toter Bestand und der
    # Eisenbedarf ein Faktor, der nie etwas entscheidet.
    pl.stocks = replace(pl.stocks, eisen=pl.stocks.eisen * (1.0 - cfg.war_iron_loss))
    pw.stocks = replace(
        pw.stocks, eisen=pw.stocks.eisen * (1.0 - cfg.war_iron_loss * cfg.war_winner_iron_share)
    )
    # Kriegsgewinner-Eliten (Aenderung 6, Konzept §3.3): der Sieg hebt Offiziere und
    # Profiteure aus den Arbeitern in die Elite. Der Krieg loest die Knappheit — und
    # saet die Eliten-Ueberproduktion, die als naechste Krise faellig wird. Das ist der
    # EINZIGE Kanal, der den Elite-Anteil je verschiebt: ohne ihn bliebe er auf ewig
    # exakt bei seinem Anfangswert und der Elitendruck eine flache Linie.
    _promote_elite(pw, cfg.war_elite_promotion)

    effects: list[Effect] = []
    region = _contested_region(world, winner, loser)
    if region is not None:
        world.regions[region].owner = winner
        pl.territory = tuple(r for r in pl.territory if r != region)
        pw.territory = tuple(sorted((*pw.territory, region)))
        effects.append(Effect(region, "owner", loser, winner))
    effects.append(Effect(loser, "population", loser_before, bevoelkerung(pl)))

    win_margin = (_power(pw, cfg) - _power(pl, cfg)) / cfg.power_reference
    subjects = (winner, loser, region) if region is not None else (winner, loser)
    battle_id = log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.SCHLACHT,
            subjects=subjects,
            factors=(
                Factor(FactorLabel.MILITAERVORTEIL, win_margin),
                Factor(FactorLabel.ZUFALL, jitter),
            ),
            causes=(war_id,),
            effects=tuple(effects),
        )
    )

    # Nachklang: favor bricht ein — der Groll steht fortan als negative Kante im
    # historischen Gedaechtnis. Honor des Opfers skaliert die Reaktion.
    add_favor(world, x, y, -cfg.favor_drop_on_attack)
    honor_y = _effective_traits(world, py).honor
    add_favor(world, y, x, -cfg.favor_drop_on_attack * (0.5 + honor_y))
    # Der Krieg loest die aufgestaute Spannung; es bleibt nur ein Groll-Restbetrag,
    # der sich ueber Jahre neu aufbaut (verhindert Krieg jedes Jahr).
    px.friction[y] = cfg.grudge_floor
    py.friction[x] = cfg.grudge_floor
    px.last_war[y] = world.year
    py.last_war[x] = world.year

    # Persoenliche Rivalitaet kann mit dem Tod des Verlierer-Herrschers enden.
    personal = any(
        f.label == FactorLabel.PERSOENLICHE_RIVALITAET for f in decision.factors
    )
    if personal:
        _maybe_personal_death(world, loser, battle_id, win_margin, rng, cfg, log)


def _maybe_personal_death(
    world: World,
    loser: EntityId,
    battle_id: EventId,
    win_margin: float,
    rng: Stream,
    cfg: Config,
    log: EventLog,
) -> None:
    """In einem persoenlichen Krieg faellt der VERNICHTEND geschlagene Herrscher.

    Aenderung 7: hier stand ein Wuerfel (``personal_death_chance`` = 0.40) — und er
    entschied ueber eine ganze Kette: Herrschertod ⇒ Sukzession ⇒ (bei schwacher
    Legitimitaet) Abspaltung. Ein Wurf liess Reiche zerfallen.

    Jetzt entscheidet die Schlacht selbst, und zwar mit einer Groesse, die ohnehin schon
    in ihrer Begruendung steht: dem **Militaervorteil**, mit dem der Sieger sie gewann.
    Wer vernichtend geschlagen wird, bleibt auf dem Feld; wer knapp verliert (oder gegen
    einen glueckhaft siegreichen Schwaecheren), kommt davon. Das TOD_FIGUR-Event traegt
    beides — die persoenliche Feindschaft und die Wucht der Niederlage —, und damit sagt
    der Graph, warum dieser Koenig starb.

    Der Tod haengt kausal an der Schlacht; die Sukzession erfolgt noch im selben Tick
    (der ``ruler``-Lauf ist vorbei), damit kein Tick mit totem Herrscher endet.
    """
    if win_margin < cfg.personal_death_margin:
        return  # knapp geschlagen: der Koenig entkommt
    pol = world.polities[loser]
    rid = pol.leader
    if rid is None:
        return
    fallen = world.rulers.get(rid)
    if fallen is None or not fallen.alive:
        return
    fallen.alive = False
    death_id = log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.TOD_FIGUR,
            subjects=(loser, rid),
            factors=(
                Factor(FactorLabel.PERSOENLICHE_RIVALITAET, 1.0),
                Factor(FactorLabel.MILITAERVORTEIL, win_margin),
            ),
            causes=(battle_id,),
            effects=(Effect(rid, "alive", True, False),),
        )
    )
    succ_event, new_ruler = _succeed(world, pol, rng, cfg, log, death_id)
    _maybe_fragment(world, pol, new_ruler, succ_event, rng, cfg, log)


# === Herrscher-Helfer (Phase 3) =============================================

def forge_ruler(
    ruler_id: EntityId,
    rng: Stream,
    cfg: Config,
    *,
    mode: AccessionMode,
    name: str,
) -> Ruler:
    """Erzeuge einen Herrscher: seine KONSTITUTION, gezogen bei der Geburt.

    Hier — und nur hier — zieht der Ereignispfad noch Zufall (Aenderung 7): Charakter
    (Trait-Deltas), Lebensspanne und Alter beim Antritt. Das ist kein Ausloeser, sondern
    eine **Anfangsbedingung**: der Wuerfel entscheidet nicht, DASS etwas geschieht,
    sondern womit eine neu geborene Entitaet ausgestattet ist — genau die Rolle, die
    Konzept §0 dem Zufall zuweist (Worldgen zieht die Traits einer Nation auf dieselbe
    Weise). Der Machtantritt wird NICHT mehr gezogen (er folgt dem Elitendruck, siehe
    ``_accession_for``), und der Name kommt von aussen aus dem kosmetischen Strom.
    """
    d = cfg.ruler_trait_delta
    deltas = NationTraits(
        aggression=rng.uniform(-d, d),
        expansion=rng.uniform(-d, d),
        innovation=0.0,  # ruht bis zur Tech-Phase ⇒ kein Delta
        honor=rng.uniform(-d, d),
        diplomacy=rng.uniform(-d, d),
        caution=rng.uniform(-d, d),
    )
    lifespan = rng.randint(cfg.ruler_lifespan_min, cfg.ruler_lifespan_max)
    age = rng.randint(cfg.ruler_accession_age_min, cfg.ruler_accession_age_max)
    return Ruler(
        id=ruler_id,
        name=name,
        trait_deltas=deltas,
        age=age,
        lifespan=lifespan,
        accession=mode,
        legitimacy=_legitimacy_for(mode, cfg),
    )


def _cosmetic_name(world: World, entity_id: EntityId) -> str:
    """Ein Name aus dem KOSMETISCHEN Strom, stabil an der id der Entitaet.

    Der Determinismus-Vertrag verlangt, dass Flavour den Entscheidungspfad nie beruehrt
    — bis Aenderung 7 zog ``make_name`` aber aus dem SEMANTISCHEN Strom des Systems.
    Damit verschob der Name eines Herrschers alle folgenden Ziehungen: haette jemand die
    Silbenliste geaendert, waere eine andere Geschichte herausgekommen. Jetzt haengt der
    Name an (Seed, id) in einem eigenen Namensraum und kann nichts mehr verschieben.
    """
    return make_name(Rng(world.seed).cosmetic_stream(f"name:{entity_id}"))


def _effective_traits(world: World, pol: Polity) -> NationTraits:
    """Effektive Traits = Basis + Delta des lebenden Herrschers (geklammert 0..1).

    Ohne lebenden Herrscher (theoretisch) gelten die Basis-Traits unveraendert.
    """
    base = pol.traits
    rid = pol.leader
    ruler_obj = world.rulers.get(rid) if rid is not None else None
    if ruler_obj is None or not ruler_obj.alive:
        return base
    d = ruler_obj.trait_deltas
    return NationTraits(
        aggression=_clamp01(base.aggression + d.aggression),
        expansion=_clamp01(base.expansion + d.expansion),
        innovation=base.innovation,
        honor=_clamp01(base.honor + d.honor),
        diplomacy=_clamp01(base.diplomacy + d.diplomacy),
        caution=_clamp01(base.caution + d.caution),
    )


def _age_and_maybe_die(
    world: World, pol: Polity, cfg: Config, log: EventLog
) -> EventId | None:
    """Altere den Herrscher um ein Jahr; erreicht er seine Lebensspanne, stirbt er.

    Aenderung 7: kein jaehrlicher Sterbe-Wurf mehr. Die Lebensspanne wird bei der GEBURT
    des Herrschers gezogen (seine Konstitution, eine Anfangsbedingung) — der Tod ist von
    da an terminiert. Der Unterschied ist nicht kosmetisch: vorher entschied ein Wurf im
    Ereignispfad, WANN eine Dynastie bricht, und daran hingen Sukzession, Schisma und
    Fragmentierung. Jetzt steht es von der ersten Stunde an fest, und der Faktor des
    Todes-Events sagt genau das (Alter/Spanne = 1).
    """
    rid = pol.leader
    if rid is None:
        return None
    r = world.rulers.get(rid)
    if r is None or not r.alive:
        return None
    r.age += 1
    if r.age < r.lifespan:
        return None
    r.alive = False
    return log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.TOD_FIGUR,
            subjects=(pol.id, rid),
            factors=(Factor(FactorLabel.ALTER, r.age / max(r.lifespan, 1)),),
            effects=(Effect(rid, "alive", True, False),),
        )
    )


def _succeed(
    world: World,
    pol: Polity,
    rng: Stream,
    cfg: Config,
    log: EventLog,
    cause: EventId | None,
    *,
    mode: AccessionMode | None = None,
) -> tuple[EventId, Ruler]:
    """Setze einen Nachfolger ein und emittiere das SUKZESSION-Event (caused-by Tod).

    ``mode=None`` LEITET den Machtantritt aus dem Elitendruck ab (Aenderung 7; vorher
    wurde er gewuerfelt) — der Normalfall nach einem natuerlichen Tod. Ein Putsch
    (Aenderung 6) gibt ihn vor: wer sich an die Macht putscht, ist ein Usurpator und
    traegt dessen schwache Legitimitaet.
    """
    old = world.rulers.get(pol.leader) if pol.leader is not None else None
    contest = Decision()
    if mode is None:
        mode, contest = _accession_for(pol, cfg)
    new = forge_ruler(
        world.next_id, rng, cfg, mode=mode, name=_cosmetic_name(world, world.next_id)
    )
    world.next_id += 1
    # Wendepunkt-Flag: grosser Trait-Sprung gegenueber dem Vorgaenger.
    new.turning_point = (
        old is not None and _delta_distance(old, new) >= cfg.turning_point_delta
    )
    world.rulers[new.id] = new
    pol.leader = new.id

    # Die Faktoren beschreiben das Fundament der neuen Herrschaft (kein Gate) — und,
    # wenn der Thron umstritten war, den Druck, der ihn umstritten machte.
    factors = [Factor(FactorLabel.LEGITIMITAET, new.legitimacy)]
    if new.accession == AccessionMode.INHERITED:
        factors.append(Factor(FactorLabel.ERBFOLGE, 1.0))
    else:
        factors.append(Factor(FactorLabel.THRONSTREIT, 1.0))
    factors.extend(contest.as_factors())
    effects = [Effect(new.id, "accession", None, str(new.accession))]
    if new.turning_point:
        effects.append(Effect(new.id, "wendepunkt", None, True))

    succ_id = log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.SUKZESSION,
            subjects=(pol.id, new.id),
            factors=tuple(factors),
            causes=(cause,) if cause is not None else (),
            effects=tuple(effects),
        )
    )
    return succ_id, new


def _accession_for(pol: Polity, cfg: Config) -> tuple[AccessionMode, Decision]:
    """Wie kommt der Nachfolger auf den Thron? Der ELITENDRUCK entscheidet (Aenderung 7).

    Hier zog frueher ein Wuerfel (``heir_uncertainty``), und er entschied ueber weit mehr
    als eine Formalie: ein umstrittener Antritt bringt einen Herrscher mit schwacher
    Legitimitaet — und an der zerbricht in ``_maybe_fragment`` das Reich. Ein Wurf liess
    also Imperien zerfallen, ohne dass jemand sagen konnte, warum.

    Jetzt sagt es der Adel. Hat er mehr Anwaerter als Aemter (Elitendruck, Aenderung 6),
    streitet er um den Thron: wenig Druck ⇒ die Dynastie erbt; viel ⇒ die Elite handelt
    einen Nachfolger aus (Wahl); sehr viel ⇒ eine Faktion nimmt sich die Macht
    (Usurpation). Die zurueckgegebene Faktorliste haengt am SUKZESSION-Event — sie IST
    die Begruendung, warum dieser Thronwechsel strittig war, und sie macht die
    Sukzessionskrise zu dem, was sie immer sein sollte: einem Symptom.
    """
    decision = Decision()
    decision.add(FactorLabel.ELITENDRUCK, pol.tension.elite)
    if decision.score >= cfg.accession_usurped_threshold:
        return AccessionMode.USURPED, decision
    if decision.score >= cfg.accession_contested_threshold:
        return AccessionMode.ELECTED, decision
    return AccessionMode.INHERITED, decision


def _legitimacy_for(mode: AccessionMode, cfg: Config) -> float:
    """Anfangs-Legitimitaet je Machtantritt."""
    if mode == AccessionMode.INHERITED:
        return cfg.legitimacy_inherited
    if mode == AccessionMode.ELECTED:
        return cfg.legitimacy_elected
    return cfg.legitimacy_usurped


def _delta_distance(old: Ruler, new: Ruler) -> float:
    """Summe der |Differenzen| der aktiven Trait-Deltas (Mass des Charakter-Sprungs)."""
    a, b = old.trait_deltas, new.trait_deltas
    return (
        abs(a.aggression - b.aggression)
        + abs(a.expansion - b.expansion)
        + abs(a.honor - b.honor)
        + abs(a.diplomacy - b.diplomacy)
        + abs(a.caution - b.caution)
    )


def _maybe_fragment(
    world: World,
    pol: Polity,
    new_ruler: Ruler,
    succ_event: EventId | None,
    rng: Stream,
    cfg: Config,
    log: EventLog,
) -> None:
    """Sukzessionskrise: bei schwacher Legitimitaet kann ein Reichsteil abspalten.

    Die Entscheidung ist eine benannte Faktorsumme (niedrige Legitimitaet,
    strittiger Antritt, Ueberdehnung, Ressourcendruck). Ueber der Schwelle wird
    ein zusammenhaengender Grenzteil als neue Nation ausgegliedert; das
    ABSPALTUNG-Event verweist kausal auf die Sukzession (und damit den Tod).
    """
    if len(pol.territory) < cfg.secession_min_territory:
        return

    decision = Decision()
    legit_gap = max(0.0, cfg.fragmentation_legit_ref - new_ruler.legitimacy)
    decision.add(FactorLabel.LEGITIMITAET, legit_gap * cfg.fragmentation_legit_weight)
    if new_ruler.accession != AccessionMode.INHERITED:
        decision.add(FactorLabel.THRONSTREIT, cfg.fragmentation_dispute_bonus)
    over = len(pol.territory) - cfg.overextension_size
    if over > 0:
        decision.add(FactorLabel.UEBERDEHNUNG, over * cfg.fragmentation_size_weight)
    if pol.food_deficit > 0.0:
        decision.add(FactorLabel.RESSOURCENDRUCK, 1.0)

    if not decision.passes(cfg.fragmentation_threshold):
        return
    blob = _carve_breakaway(world, pol)
    if not blob:
        return
    _spawn_breakaway(world, pol, blob, decision, succ_event, rng, cfg, log)


def _carve_breakaway(world: World, pol: Polity) -> list[EntityId]:
    """Schneide einen zusammenhaengenden, hauptstadtfernen Reichsteil heraus.

    Waehlt ein peripheres Saatfeld (groesste Graph-Distanz zur Hauptstadt) und
    laesst von dort einen zusammenhaengenden Bereich bis zur halben Reichsgroesse
    wachsen — nie die Hauptstadt. Deterministisch (stabile Sortierung).
    """
    cap = pol.capital
    if cap is None:
        return []
    terr = set(pol.territory)
    others = sorted(r for r in terr if r != cap)
    if not others:
        return []

    dist = _bfs_distance(world, cap, terr)
    seed = max(others, key=lambda r: (dist.get(r, 0), -r))
    target = max(1, len(pol.territory) // 2)

    blob: list[EntityId] = []
    visited: set[EntityId] = set()
    frontier = [seed]
    while frontier and len(blob) < target:
        # Bevorzuge hauptstadtferne Felder; deterministische Tie-Break.
        frontier.sort(key=lambda r: (dist.get(r, 0), r), reverse=True)
        cur = frontier.pop(0)
        if cur in visited or cur == cap:
            continue
        visited.add(cur)
        blob.append(cur)
        for nb in world.regions[cur].nachbarn:
            if nb in terr and nb != cap and nb not in visited:
                frontier.append(nb)
    return sorted(blob)


def _bfs_distance(
    world: World, start: EntityId, allowed: set[EntityId]
) -> dict[EntityId, int]:
    """Graph-Distanz von ``start`` zu allen Feldern innerhalb von ``allowed``."""
    dist = {start: 0}
    frontier = [start]
    while frontier:
        nxt: list[EntityId] = []
        for rid in frontier:
            for nb in world.regions[rid].nachbarn:
                if nb in allowed and nb not in dist:
                    dist[nb] = dist[rid] + 1
                    nxt.append(nb)
        frontier = sorted(nxt)
    return dist


def _spawn_breakaway(
    world: World,
    parent: Polity,
    blob: list[EntityId],
    decision: Decision,
    succ_event: EventId | None,
    rng: Stream,
    cfg: Config,
    log: EventLog,
) -> None:
    """Gruende die Abspaltung der Sukzessionskrise als neue Nation (Phase 3)."""
    pop_before = bevoelkerung(parent)
    child, capital, effects = _secede(world, parent, blob, rng, cfg)
    effects.append(Effect(parent.id, "population", pop_before, bevoelkerung(parent)))
    # Die Sukzession ist der strukturelle Ausloeser der Krise und wird stets als
    # Ursache verlinkt (Fragmentierung ← Sukzession ← Herrschertod), unabhaengig
    # davon, welcher Faktor die Entscheidung dominierte.
    causes = decision.as_causes()
    if succ_event is not None and succ_event not in causes:
        causes = tuple(sorted({*causes, succ_event}))
    log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.ABSPALTUNG,
            subjects=(parent.id, child.id, capital),
            factors=decision.as_factors(),
            causes=causes,
            effects=tuple(effects),
        )
    )


def _secede(
    world: World,
    parent: Polity,
    blob: list[EntityId],
    rng: Stream,
    cfg: Config,
    *,
    elite_bias: float = 1.0,
) -> tuple[Polity, EntityId, list[Effect]]:
    """Gliedere ``blob`` als neue Nation aus — reiner Zustandswechsel, KEIN Event.

    Der gemeinsame Kern aller Reichsteilungen: der Sukzessionskrise (Phase 3), der
    Abspaltung aus Elitendruck und des Kollaps (Aenderung 6). Der Aufrufer emittiert
    das Ereignis und haengt die zurueckgegebenen ``effects`` daran — so traegt jede
    Teilung die Faktoren IHRER Ursache.

    Bevoelkerung und Bestaende gehen anteilig zur Regionszahl mit; Groll und
    Wohlstandsanteile sind intensiv und wandern unveraendert. ``elite_bias`` hebt den
    Anteil der Elite, der mitgeht: bei einer Abspaltung AUS Elitendruck ist es gerade
    die ueberzaehlige Elite, die geht. Eine proportionale Teilung (``1.0``, der Weg der
    Sukzessionskrise) halbierte Elite UND Aemter zugleich und liesse den Elitendruck
    unveraendert — sie waere keine Entlastung.
    """
    total_regions = len(parent.territory)
    k = len(blob)
    blob_set = set(blob)

    new_pid = world.next_id
    world.next_id += 1
    new_ruler = forge_ruler(
        world.next_id,
        rng,
        cfg,
        mode=AccessionMode.USURPED,
        name=_cosmetic_name(world, world.next_id),
    )
    world.next_id += 1
    world.rulers[new_ruler.id] = new_ruler

    new_capital = max(blob, key=lambda r: (world.regions[r].food_capacity, -r))
    for r in blob:
        world.regions[r].owner = new_pid

    share = k / total_regions
    elite_share = min(1.0, share * elite_bias)
    moved_strata = _split_strata(parent.strata, share, elite_share)
    parent.strata = _split_strata(parent.strata, 1.0 - share, 1.0 - elite_share)
    parent.peak_population = max(parent.peak_population, bevoelkerung(parent))
    moved_pop = int(sum(s.size for s in moved_strata))
    ps = parent.stocks
    moved = Stocks(
        getreide=ps.getreide * share,
        eisen=ps.eisen * share,
        gold=ps.gold * share,
    )
    parent.stocks = replace(
        ps,
        getreide=ps.getreide - moved.getreide,
        eisen=ps.eisen - moved.eisen,
        gold=ps.gold - moved.gold,
    )
    parent.territory = tuple(sorted(r for r in parent.territory if r not in blob_set))

    new_pol = Polity(
        id=new_pid,
        name=_cosmetic_name(world, new_pid),
        capital=new_capital,
        territory=tuple(sorted(blob)),
        founded_year=world.year,
        strata=moved_strata,
        peak_population=max(1, moved_pop),
        stocks=moved,
        # Kulturelle Kontinuitaet: gleiche Basis-Traits, abweichender Herrscher.
        traits=parent.traits,
        leader=new_ruler.id,
        # Glaubens-Kontinuitaet: die Abspaltung teilt zunaechst die Identitaet.
        identity_id=parent.identity_id,
    )
    # Gegenseitiger Groll (negative favor-Kanten) und frische Grenzreibung
    # zwischen Tochter und Mutterland.
    add_favor(world, parent.id, new_pid, -cfg.secession_distrust)
    add_favor(world, new_pid, parent.id, -cfg.secession_distrust)
    parent.friction[new_pid] = cfg.grudge_floor
    new_pol.friction[parent.id] = cfg.grudge_floor
    world.polities[new_pid] = new_pol

    effects = [Effect(r, "owner", parent.id, new_pid) for r in sorted(blob)]
    return new_pol, new_capital, effects


def _split_strata(
    strata: tuple[Stratum, ...], share: float, elite_share: float
) -> tuple[Stratum, ...]:
    """Skaliere die Schichten fuer eine Reichsteilung; die Elite mit eigenem Anteil."""
    return tuple(
        replace(
            s,
            size=max(
                0.0, s.size * (elite_share if s.kind == StratumKind.ELITE else share)
            ),
        )
        for s in strata
    )


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


# === Identitaet & Glaube (Phase 4) ==========================================

def identity(world: World, rng: Stream, cfg: Config, log: EventLog) -> World:
    """EIN Identitaets-Mechanismus: Ausbreitung (Konversion) und Schisma.

    Dominante Nationen verbreiten ihren Glauben — eine viel schwaechere Nation
    uebernimmt die Identitaet eines uebermaechtigen andersglaeubigen Nachbarn
    (erobertes/unterlegenes Gebiet konvertiert). Gelegentlich spaltet ein
    zelotischer Herrscher (oder schiere Groesse) eine Identitaet in eine neue
    ``id`` — vorher gleiche Nationen haben danach Reibung, und ein Buendnis unter
    Glaubensbrueder kann daran zerbrechen. Laeuft am Tick-Ende: die Affinitaets-
    Faktoren in Diplomatie/Krieg lesen die Identitaeten des Vorjahres.
    """
    powers = {pid: _power(world.polities[pid], cfg) for pid in sorted(world.polities)}
    for pid in sorted(world.polities):
        _maybe_convert(world, pid, powers, cfg, log)
    for pid in sorted(world.polities):
        _maybe_schisma(world, pid, rng, cfg, log)
    return world


def _maybe_convert(
    world: World,
    pid: EntityId,
    powers: dict[EntityId, float],
    cfg: Config,
    log: EventLog,
) -> None:
    """Konvertiere eine viel schwaechere Nation zum Glauben eines dominanten Nachbarn."""
    pol = world.polities[pid]
    own_faith = pol.identity_id
    # Ein frisch konvertierter (oder schismierter) Glaube haelt eine Weile:
    # verhindert das jaehrliche Kippen eines Pufferstaats.
    if (
        _recent_subject_event(
            log, world.year, EventKind.KONVERSION, pid, cfg.conversion_cooldown_years
        )
        is not None
        or _recent_subject_event(
            log, world.year, EventKind.SCHISMA, pid, cfg.conversion_cooldown_years
        )
        is not None
    ):
        return
    candidates = [
        n
        for n in _bordering_nations(world, pol)
        if world.polities[n].identity_id is not None
        and world.polities[n].identity_id != own_faith
    ]
    if not candidates:
        return
    dominant = max(candidates, key=lambda n: (powers[n], -n))
    own = max(powers[pid], 1.0)
    if powers[dominant] < own * cfg.conversion_power_ratio:
        return

    decision = Decision()
    dominance = min(powers[dominant] / own - 1.0, cfg.conversion_dominance_cap)
    # Eine kuerzliche Niederlage gegen den Dominanten macht die Bekehrung plausibel.
    battle = _recent_pair_events(
        log, world.year, EventKind.SCHLACHT, pid, dominant, cfg.cause_window_years
    )
    decision.add(
        FactorLabel.DOMINANZ, dominance * cfg.conversion_dominance_weight, causes=battle
    )
    honor = _effective_traits(world, pol).honor
    decision.add(FactorLabel.GLAUBENSTREUE, -honor * cfg.conversion_honor_resist)
    if not decision.passes(cfg.conversion_threshold):
        return

    new_faith = world.polities[dominant].identity_id
    if new_faith is None:  # per Kandidatenfilter unmoeglich, aber typ-sicher
        return
    pol.identity_id = new_faith
    log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.KONVERSION,
            subjects=(pid, new_faith, dominant),
            factors=decision.as_factors(),
            causes=decision.as_causes(),
            effects=(Effect(pid, "identity_id", own_faith, new_faith),),
        )
    )


def _maybe_schisma(
    world: World, pid: EntityId, rng: Stream, cfg: Config, log: EventLog
) -> None:
    """Ein frisch aufgestiegener zelotischer Herrscher spaltet eine Identitaet ab.

    Nur teilbar, wenn die Identitaet von mehreren Nationen geteilt wird — sonst
    entstuende bloss eine Umbenennung ohne neue Reibung. Der Ausloeser ist an
    einen kuerzlichen Machtantritt gebunden: ein Impuls je Thronwechsel, kein
    Dauerdruck ⇒ Schismata bleiben selten. Kausalkette: Schisma ← Sukzession
    (← Herrschertod). Bricht Buendnisse zu den ehemaligen Glaubensbruedern.
    """
    pol = world.polities[pid]
    old_faith = pol.identity_id
    if old_faith is None:
        return
    # Gate: nur ein gerade aufgestiegener Herrscher stoesst ein Schisma an.
    accession = _recent_subject_event(
        log, world.year, EventKind.SUKZESSION, pid, cfg.schism_window_years
    )
    if accession is None:
        return
    followers = [
        q for q in sorted(world.polities) if world.polities[q].identity_id == old_faith
    ]
    if len(followers) < cfg.schism_min_followers:
        return

    decision = Decision()
    decision.add(FactorLabel.GLAUBENSGROESSE, (len(followers) - 1) * cfg.schism_size_weight)
    zeal = _effective_traits(world, pol).honor - cfg.schism_zeal_ref
    if zeal > 0.0:
        decision.add(FactorLabel.GLAUBENSEIFER, zeal * cfg.schism_zeal_weight)
    if not decision.passes(cfg.schism_threshold):
        return

    new_id = world.next_id
    world.next_id += 1
    world.identities[new_id] = Identity(
        id=new_id, name=_cosmetic_name(world, new_id), parent=old_faith
    )
    pol.identity_id = new_id

    log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.SCHISMA,
            subjects=(pid, new_id, old_faith),
            factors=decision.as_factors(),
            causes=(accession,),
            effects=(Effect(pid, "identity_id", old_faith, new_id),),
        )
    )
    # Das Schisma ist ein Groll-Stoss auf die Kanten zu den ehemaligen
    # Glaubensbruedern. Ob ein Buendnis daran zerbricht, entscheidet der
    # favor-Stand — den Bruch meldet der naechste diplomacy-Lauf und zitiert
    # dieses SCHISMA-Event als Ursache.
    for other in followers:
        if other == pid:
            continue
        add_favor(world, pid, other, -cfg.schism_favor_drop)
        add_favor(world, other, pid, -cfg.schism_favor_drop)


# === Schocks, Technologie, Wendepunkte (Phase 5) ============================

def research(world: World, rng: Stream, cfg: Config, log: EventLog) -> World:
    """Wissen akkumuliert (innovation treibt die Rate); Schwellen schalten Tech frei.

    Ueberschreitet eine Nation eine Wissens-Schwelle, steigt ihre Tech-Stufe — das
    hebt fortan Produktion und Schlagkraft (siehe ``production``/``_power``) und
    emittiert ein INNOVATION-Event (die erreichte Stufe benennt ein Zeitalter).
    """
    for pid in sorted(world.polities):
        pol = world.polities[pid]
        innovation = _effective_traits(world, pol).innovation
        rate = cfg.research_base_rate * innovation * (
            1.0 + bevoelkerung(pol) / cfg.research_pop_scale
        )
        pol.knowledge += rate
        while (
            pol.tech_level < len(cfg.tech_thresholds)
            and pol.knowledge >= cfg.tech_thresholds[pol.tech_level]
        ):
            before = pol.tech_level
            pol.tech_level += 1
            log.append(
                EventDraft(
                    year=world.year,
                    kind=EventKind.INNOVATION,
                    subjects=(pid,),
                    factors=(Factor(FactorLabel.FORSCHUNG, pol.knowledge),),
                    effects=(
                        Effect(pid, "tech_level", before, pol.tech_level),
                        Effect(pid, "tech_age", None, cfg.tech_age_names[before]),
                    ),
                )
            )
    return world


def tectonics(world: World, rng: Stream, cfg: Config, log: EventLog) -> World:
    """Der EINE verbliebene exogene Schock — und auch er wird nicht gewuerfelt.

    Aenderung 7 raeumt das alte Katastrophen-System ab. Pest und Duerre waren reine
    Wuerfelwuerfe im Ereignispfad: "weil der Wuerfel es sagte, starb ein Drittel des
    Volkes". Sie sind fort, und sie fehlen nicht — was sie taten (Bevoelkerung toeten,
    Vorraete vernichten), tut die Welt aus sich selbst: Hungersnot aus Uebervoelkerung,
    Mobilmachung und verlorenem Land (siehe ``production``), Verluste aus Krieg,
    Aufstand und Kollaps.

    Das Erdbeben bleibt, denn es ist der einzige Schock, der KEINE soziale Ursache haben
    kann — Geologie fragt nicht nach Politik (Konzept §5 erlaubt genau das). Aber es
    faellt nicht mehr vom Himmel: unter einem Feld auf einer Verwerfung staut sich Jahr
    um Jahr Spannung, und an der Schwelle bricht sie (elastischer Rueckprall). Dieselbe
    Figur wie ueberall in dieser Welt — Aufbau, Schwelle, Entladung —, nur dass der Stau
    hier im Gestein sitzt. Gezogen wird allein die Geologie, und zwar im Worldgen: das
    Beben ist damit eine Anfangsbedingung, die faellig wird, kein Wurf des Jahres.

    Und seine FOLGEN laufen durch das Spannungssystem: es loest kein fertiges
    Gross-Ereignis aus, es SETZT Druck — der leere Schatz treibt den Fiskaldruck, die
    vernarbte Kapazitaet den Hunger und damit den Volksdruck. Was daraus wird (Bankrott,
    Aufstand, gar nichts), entscheidet die Lage der Nation, nicht das Beben.
    """
    for rid in sorted(world.regions):
        region = world.regions[rid]
        if region.seismicity <= 0.0:
            continue
        region.strain += region.seismicity * cfg.seismic_strain_rate
        if region.strain >= 1.0:
            _quake(world, region, cfg, log)
    return world


def _quake(world: World, region: Region, cfg: Config, log: EventLog) -> None:
    """Die Spannung im Gestein entlaedt sich: Narbe im Land, Schaden fuer den Besitzer."""
    strain_before = region.strain
    region.strain = 0.0
    cap_before = region.food_capacity
    region.food_capacity = cap_before * (1.0 - cfg.quake_capacity_scar)

    subjects: tuple[EntityId, ...] = (region.id,)
    effects = [Effect(region.id, "food_capacity", cap_before, region.food_capacity)]
    # Ein Beben im unbesiedelten Land vernarbt nur die Erde — es gibt niemanden, den es
    # trifft. Wer das Feld spaeter nimmt, erbt die Narbe.
    owner = region.owner
    if owner is not None and owner in world.polities:
        pol = world.polities[owner]
        gold_before = pol.stocks.gold
        pop_before = bevoelkerung(pol)
        pol.stocks = replace(pol.stocks, gold=gold_before * (1.0 - cfg.quake_wealth_loss))
        pol.strata = _scaled_strata(pol.strata, 1.0 - cfg.quake_pop_loss)
        subjects = (owner, region.id)
        effects += [
            Effect(owner, "gold", gold_before, pol.stocks.gold),
            Effect(owner, "population", pop_before, bevoelkerung(pol)),
        ]
    log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.ERDBEBEN,
            subjects=subjects,
            # Die Begruendung ist die aufgestaute Spannung selbst — kein "Zufall".
            factors=(Factor(FactorLabel.ERDSPANNUNG, strain_before),),
            effects=tuple(effects),
        )
    )


def epoch(world: World, rng: Stream, cfg: Config, log: EventLog) -> World:
    """Wendepunkt-Waechter: erkennt Bruechen in Trends und emittiert WENDEPUNKT-Events.

    Vier Trend-Waechter (Machtranking, Technologie-Aera, dominante Identitaet,
    langlebigstes Buendnis, Territoriums-Trajektorie) vergleichen den aktuellen
    Zustand gegen den erinnerten. Ein Bruch ⇒ ein benanntes Meta-Event mit Verweis
    auf die **nahe Ursache** aus dem Kausalgraphen. Machtwechsel und der erste
    industrielle Durchbruch begrenzen und benennen zudem ein Zeitalter.
    """
    _watch_hegemon(world, cfg, log)
    _watch_industrial(world, cfg, log)
    _watch_dominant_faith(world, cfg, log)
    _watch_alliance_collapse(world, cfg, log)
    _watch_territory_collapse(world, cfg, log)
    return world


def _begin_age(world: World) -> tuple[int, int]:
    """Ruecke ins naechste Zeitalter vor; gib (alter, neuer) Index zurueck."""
    prev = world.age_index
    world.age_index = prev + 1
    return prev, world.age_index


def _watch_hegemon(world: World, cfg: Config, log: EventLog) -> None:
    """Machtranking: ein neuer, klar ueberlegener Hegemon oeffnet ein neues Zeitalter."""
    powers = {pid: _power(world.polities[pid], cfg) for pid in sorted(world.polities)}
    if not powers:
        return
    top = max(sorted(powers), key=lambda p: (powers[p], -p))
    old = world.hegemon
    if old is None or old not in world.polities:
        world.hegemon = top
        return
    if top == old or powers[top] < powers[old] * cfg.turning_hegemon_margin:
        return

    cause = _recent_setback(world, old, cfg, log)
    if cause is None:
        cause = _recent_subject_event(
            log, world.year, EventKind.SCHLACHT, top, cfg.turning_cause_window
        )
    prev_age, new_age = _begin_age(world)
    world.hegemon = top
    log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.WENDEPUNKT,
            subjects=(top, old),
            factors=(Factor(FactorLabel.MACHTWECHSEL, powers[top] / max(powers[old], 1.0)),),
            causes=(cause,) if cause is not None else (),
            effects=(Effect(top, "age", prev_age, new_age),),
        )
    )


def _watch_industrial(world: World, cfg: Config, log: EventLog) -> None:
    """Technologie-Aera: der erste Aufstieg in die hoechste Tech-Stufe weltweit."""
    if world.industrial:
        return
    top_tier = len(cfg.tech_thresholds)
    advanced = [
        pid for pid in sorted(world.polities) if world.polities[pid].tech_level >= top_tier
    ]
    if not advanced:
        return
    world.industrial = True
    pid = advanced[0]
    cause = _recent_subject_event(
        log, world.year, EventKind.INNOVATION, pid, cfg.turning_cause_window
    )
    prev_age, new_age = _begin_age(world)
    log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.WENDEPUNKT,
            subjects=(pid,),
            factors=(Factor(FactorLabel.TECHNOLOGISCHER_DURCHBRUCH, 1.0),),
            causes=(cause,) if cause is not None else (),
            effects=(
                Effect(pid, "age", prev_age, new_age),
                Effect(pid, "age_kind", None, "industrial"),
            ),
        )
    )


def _watch_dominant_faith(world: World, cfg: Config, log: EventLog) -> None:
    """Dominante Identitaet: die territorial groesste Glaubensgemeinschaft wechselt."""
    territory: dict[EntityId, int] = {}
    for pid in sorted(world.polities):
        faith = world.polities[pid].identity_id
        if faith is None:
            continue
        territory[faith] = territory.get(faith, 0) + len(world.polities[pid].territory)
    if not territory:
        return
    top = max(sorted(territory), key=lambda f: (territory[f], -f))
    old = world.dominant_faith
    if old is None or old not in world.identities:
        world.dominant_faith = top
        return
    if top == old or territory[top] < territory.get(old, 0) * cfg.turning_faith_margin:
        return

    cause = _recent_faith_shift(world, top, cfg, log)
    world.dominant_faith = top
    log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.WENDEPUNKT,
            subjects=(top, old),
            factors=(Factor(FactorLabel.GLAUBENSWANDEL, float(territory[top])),),
            causes=(cause,) if cause is not None else (),
        )
    )


def _watch_alliance_collapse(world: World, cfg: Config, log: EventLog) -> None:
    """Langlebigstes Buendnis: zerbricht das aelteste (sehr alte) Buendnis ⇒ Wendepunkt."""
    max_standing = _max_standing_alliance_age(world, cfg, log)
    best_break: tuple[int, Event] | None = None
    for event in log.by_year(world.year):
        if event.kind != EventKind.BUENDNIS_BRUCH:
            continue
        a, b = event.subjects[0], event.subjects[1]
        formed = _alliance_formation_year(log, a, b, event.id)
        if formed is None:
            continue
        age = world.year - formed
        if age < cfg.turning_alliance_min_years or age < max_standing:
            continue
        if best_break is None or age > best_break[0]:
            best_break = (age, event)
    if best_break is None:
        return
    age, event = best_break
    log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.WENDEPUNKT,
            subjects=(event.subjects[0], event.subjects[1]),
            factors=(Factor(FactorLabel.BUENDNISZERFALL, float(age)),),
            causes=(event.id,),
        )
    )


def _watch_territory_collapse(world: World, cfg: Config, log: EventLog) -> None:
    """Territoriums-Trajektorie: ein Reich verliert einen Grossteil seines Hoechststands."""
    for pid in sorted(world.polities):
        pol = world.polities[pid]
        size = len(pol.territory)
        if size > pol.peak_territory:
            pol.peak_territory = size
            continue
        peak = pol.peak_territory
        if peak < cfg.turning_collapse_min_peak:
            continue
        if size > peak * cfg.turning_collapse_fraction:
            continue
        cause = _recent_setback(world, pid, cfg, log)
        log.append(
            EventDraft(
                year=world.year,
                kind=EventKind.WENDEPUNKT,
                subjects=(pid,),
                factors=(Factor(FactorLabel.GEBIETSKOLLAPS, float(peak - size)),),
                causes=(cause,) if cause is not None else (),
                effects=(Effect(pid, "peak_territory", peak, size),),
            )
        )
        # Zuruecksetzen: der Kollaps muss neu erwachsen, um erneut zu feuern.
        pol.peak_territory = size


def _recent_setback(
    world: World, pid: EntityId, cfg: Config, log: EventLog
) -> EventId | None:
    """Naheliegende Ursache eines Niedergangs: Schock > Niederlage > Abspaltung."""
    window = cfg.turning_cause_window
    disasters: list[EventId] = []
    defeats: list[EventId] = []
    splits: list[EventId] = []
    shock_kinds = {EventKind.ERDBEBEN}
    for event in log.by_subject(pid):
        if world.year - event.year > window:
            continue
        subjects = event.subjects
        if event.kind in shock_kinds:
            disasters.append(event.id)
        elif event.kind == EventKind.SCHLACHT and len(subjects) > 1 and subjects[1] == pid:
            defeats.append(event.id)
        elif event.kind == EventKind.ABSPALTUNG and len(subjects) >= 1 and subjects[0] == pid:
            splits.append(event.id)
    for bucket in (disasters, defeats, splits):
        if bucket:
            return bucket[-1]
    return None


def _recent_faith_shift(
    world: World, faith: EntityId, cfg: Config, log: EventLog
) -> EventId | None:
    """Naheliegende Ursache eines Glaubenswandels: jüngstes Schisma/jüngste Konversion."""
    window = cfg.turning_cause_window
    found: list[EventId] = []
    for event in log.by_subject(faith):
        if world.year - event.year > window:
            continue
        if event.kind in {EventKind.SCHISMA, EventKind.KONVERSION}:
            found.append(event.id)
    return found[-1] if found else None


def _max_standing_alliance_age(world: World, cfg: Config, log: EventLog) -> int:
    """Alter (Jahre) des aeltesten noch bestehenden Buendnisses (Status abgeleitet)."""
    best = 0
    pids = sorted(world.polities)
    for i, a in enumerate(pids):
        for b in pids[i + 1 :]:
            if not allied(world, a, b, cfg):
                continue
            formed = _alliance_formation_year(log, a, b, len(log))
            if formed is not None:
                best = max(best, world.year - formed)
    return best


def _alliance_formation_year(
    log: EventLog, a: EntityId, b: EntityId, before_id: EventId
) -> int | None:
    """Jahr des juengsten BUENDNIS-Schlusses zwischen a und b vor ``before_id``."""
    pair = {a, b}
    formed: int | None = None
    for event in log.by_kind(EventKind.BUENDNIS):
        if event.id >= before_id:
            break
        if pair <= set(event.subjects):
            formed = event.year
    return formed


# === Diplomatie-Helfer ======================================================

def _recompute_fear(
    world: World, pids: list[EntityId], powers: dict[EntityId, float], cfg: Config
) -> None:
    """Furcht je Nation vor jeder staerkeren anderen Nation; caution verstaerkt sie."""
    for pid in pids:
        pol = world.polities[pid]
        own = max(powers[pid], 1.0)
        caution = _effective_traits(world, pol).caution
        pol.fear = {}
        for other in pids:
            if other == pid:
                continue
            relative = powers[other] / own - 1.0
            if relative > 0.0:
                pol.fear[other] = min(relative * (1.0 + caution), cfg.fear_cap)


def _decay_favor(world: World, cfg: Config) -> None:
    """favor zerfaellt jedes Jahr Richtung 0 — die Vergebung des Gedaechtnisses.

    Kanten mit winzigem |favor| (und ruhender dependency) entfallen ganz, damit
    die Matrix sparse bleibt. Ausschliesslich nach (a_id, b_id) sortiert
    iterieren (Determinismus-Vertrag der Matrix).
    """
    for key in sorted(world.relations):
        rel = world.relations[key]
        faded = rel.favor * (1.0 - cfg.favor_decay)
        if abs(faded) < cfg.favor_prune_epsilon and rel.dependency == 0.0:
            del world.relations[key]  # neutrale Kante = keine Kante
        else:
            world.relations[key] = replace(rel, favor=faded)


def _drift_favor(world: World, cfg: Config) -> None:
    """Friedliche Nachbarschaft naehert langsam an; offener Groll blockiert das.

    Feindschaft muss erst verblassen (Zerfall ueber die Schwelle), bevor die
    Annaeherung wieder greift — alte Feinde werden erst neutral, dann Partner.
    Honor verstaerkt die Reziprozitaet.
    """
    for pid in sorted(world.polities):
        pol = world.polities[pid]
        honor = _effective_traits(world, pol).honor
        for other in _bordering_nations(world, pol):
            if hostile(world, pid, other, cfg):
                continue
            add_favor(world, pid, other, cfg.favor_drift * (0.5 + honor))


def _cooperate_against_hegemon(
    world: World, pids: list[EntityId], strongest: EntityId, cfg: Config
) -> None:
    """Balance of Power als **ambiente** favor-Quelle: gemeinsame Furcht verbindet.

    Nicht-staerkste Nationen, die denselben Hegemon fuerchten, ruecken jaehrlich
    ein Stueck zusammen; Diplomatie-Traits und gleicher Glaube verstaerken das.
    Das ist der Untergrund, aus dem Koalitionen wachsen — die *gezielte* Werbung
    einer Nation (Ziel VERBUENDEN, siehe ``_court``) legt sich darauf und
    entscheidet, welcher Pakt zuerst die Schwelle erreicht. Endet die gemeinsame
    Furcht, versiegt die Quelle und der Zerfall loest das Band.
    """
    for i, a in enumerate(pids):
        if a == strongest:
            continue
        pa = world.polities[a]
        fear_a = pa.fear.get(strongest, 0.0)
        if fear_a <= 0.0:
            continue
        for b in pids[i + 1 :]:
            if b == strongest:
                continue
            pb = world.polities[b]
            common_fear = min(fear_a, pb.fear.get(strongest, 0.0))
            if common_fear <= 0.0:
                continue
            boost = (
                _effective_traits(world, pa).diplomacy
                + _effective_traits(world, pb).diplomacy
            ) / 2.0
            # Affinitaet (Phase 4): gleicher Glaube stiftet ein festeres Band.
            if pa.identity_id is not None and pa.identity_id == pb.identity_id:
                boost += cfg.identity_alliance_bonus
            delta = cfg.favor_coop_rate * common_fear * (0.5 + boost)
            add_favor(world, a, b, delta)
            add_favor(world, b, a, delta)


def _logged_alliances(log: EventLog) -> set[tuple[EntityId, EntityId]]:
    """Paare, deren juengstes Buendnis-Event im Log ein Schluss (kein Bruch) ist.

    Der Log erinnert nur den zuletzt GEMELDETEN Status; der aktuelle Status
    selbst wird stets frisch aus favor abgeleitet (kein gespeichertes Feld).
    """
    latest: dict[tuple[EntityId, EntityId], tuple[EventId, bool]] = {}
    for kind, formed in ((EventKind.BUENDNIS, True), (EventKind.BUENDNIS_BRUCH, False)):
        for event in log.by_kind(kind):
            a, b = event.subjects[0], event.subjects[1]
            pair = (min(a, b), max(a, b))
            seen = latest.get(pair)
            if seen is None or event.id > seen[0]:
                latest[pair] = (event.id, formed)
    return {pair for pair, (_, formed) in latest.items() if formed}


def _emit_alliance_flips(
    world: World,
    pids: list[EntityId],
    strongest: EntityId,
    cfg: Config,
    log: EventLog,
) -> None:
    """Melde Wechsel des abgeleiteten Buendnis-Status als Events (Chronik-Anker)."""
    was_allied = _logged_alliances(log)
    for i, a in enumerate(pids):
        for b in pids[i + 1 :]:
            now = allied(world, a, b, cfg)
            if now == ((a, b) in was_allied):
                continue
            if now:
                _emit_alliance_formed(world, a, b, strongest, cfg, log)
            else:
                _emit_alliance_broken(world, a, b, cfg, log)


def _emit_alliance_formed(
    world: World,
    a: EntityId,
    b: EntityId,
    strongest: EntityId,
    cfg: Config,
    log: EventLog,
) -> None:
    """favor hat die Schwelle beidseitig ueberschritten: der Pakt wird geschlossen."""
    pa, pb = world.polities[a], world.polities[b]
    # Der Schluss selbst ist ein Gefallen: er hebt favor ueber die Schwelle
    # hinaus (natuerliche Hysterese gegen jaehrliches Flattern an der Kante).
    add_favor(world, a, b, cfg.favor_pact_bonus)
    add_favor(world, b, a, cfg.favor_pact_bonus)

    decision = Decision()
    decision.add(FactorLabel.VERTRAUEN, min(favor(world, a, b), favor(world, b, a)))
    common_fear = min(pa.fear.get(strongest, 0.0), pb.fear.get(strongest, 0.0))
    decision.add(
        FactorLabel.GEMEINSAMER_FEIND,
        common_fear,
        causes=_recent_subject_event_all(
            log, world.year, EventKind.BEVOELKERUNG_MEILENSTEIN, strongest,
            cfg.cause_window_years,
        ),
    )
    if pa.identity_id is not None and pa.identity_id == pb.identity_id:
        decision.add(FactorLabel.GLAUBENSAFFINITAET, cfg.identity_alliance_bonus)
    log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.BUENDNIS,
            subjects=(a, b, strongest),
            factors=decision.as_factors(),
            causes=decision.as_causes(),
        )
    )


def _emit_alliance_broken(
    world: World, a: EntityId, b: EntityId, cfg: Config, log: EventLog
) -> None:
    """favor ist unter die Schwelle gesunken: der Bruch wird gemeldet.

    Als Ursachen werden die naheliegenden favor-Zehrer im Fenster zitiert
    (Schlacht/Abspaltung zwischen den beiden, Schisma eines Partners); fehlen
    sie, war es der blosse Zerfall — die gemeinsame Furcht ist verblasst.
    """
    minfav = min(favor(world, a, b), favor(world, b, a))
    causes: set[EventId] = set()
    causes.update(
        _recent_pair_events(log, world.year, EventKind.SCHLACHT, a, b, cfg.cause_window_years)
    )
    causes.update(
        _recent_pair_events(log, world.year, EventKind.ABSPALTUNG, a, b, cfg.cause_window_years)
    )
    for pid in (a, b):
        schisma = _recent_subject_event(
            log, world.year, EventKind.SCHISMA, pid, cfg.cause_window_years
        )
        if schisma is not None:
            causes.add(schisma)
    log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.BUENDNIS_BRUCH,
            subjects=(a, b),
            factors=(
                Factor(FactorLabel.MISSTRAUEN, cfg.alliance_favor_threshold - minfav),
            ),
            causes=tuple(sorted(causes)),
        )
    )


# === reine Helfer ===========================================================

def _power(pol: Polity, cfg: Config) -> float:
    """Schlagkraft, abgeleitet aus Soldaten, Eisen und Gold, gehoben durch Tech.

    Soldaten sind die Basis; Eisen (Bewaffnung) und Gold (Sold) heben sie je bis zu
    einem gedeckelten Bonus — genug Eisen/Gold, um alle Soldaten zu ruesten/besolden,
    schoepft den Bonus voll aus. Ohne Soldaten keine Schlagkraft. Technologie bleibt
    ein Multiplikator (ein kleineres, fortgeschritteneres Reich kann ein groesseres
    schlagen). Konsistent mit "Schlagkraft ist abgeleitet".
    """
    soldiers = _stratum_size(pol, StratumKind.SOLDAT)
    if soldiers <= 0.0:
        return 0.0
    armed = min(1.0, pol.stocks.eisen / (soldiers * cfg.iron_per_soldier))
    paid = min(1.0, pol.stocks.gold / (soldiers * cfg.gold_per_soldier))
    equipment = 1.0 + cfg.power_equip_bonus * armed + cfg.power_pay_bonus * paid
    tech = 1.0 + pol.tech_level * cfg.tech_power_bonus
    return soldiers * tech * equipment


def _power_of(
    world: World, pid: EntityId, powers: dict[EntityId, float], cfg: Config
) -> float:
    """Macht aus dem Snapshot; faellt auf Live-Berechnung zurueck.

    Der Snapshot wird je System einmal gebildet; entsteht **innerhalb** des Ticks
    eine neue Nation (z. B. eine Abspaltung nach einem persoenlichen Krieg), fehlt
    sie im Snapshot — dann gilt ihre aktuelle Macht.
    """
    cached = powers.get(pid)
    return cached if cached is not None else _power(world.polities[pid], cfg)


def _effective_power(
    world: World, pid: EntityId, powers: dict[EntityId, float], cfg: Config
) -> float:
    """Eigene Macht plus anteiligen Beitrag der Verbuendeten (Koalition).

    Die Verbuendeten sind pro Tick aus der favor-Matrix abgeleitet, kein Feld.
    """
    total = _power_of(world, pid, powers, cfg)
    for ally in _allies_of(world, pid, cfg):
        total += _power_of(world, ally, powers, cfg) * cfg.ally_power_contribution
    return total


def _land_capacity(world: World, pol: Polity, cfg: Config) -> float:
    """Mittlere Jahres-Getreidekapazitaet des Territoriums (ohne Ernteschwankung)."""
    return (
        sum(world.regions[r].food_capacity for r in sorted(pol.territory))
        * cfg.grain_per_capacity
    )


def _bordering_nations(world: World, pol: Polity) -> list[EntityId]:
    """Stabil sortierte Liste der Nationen, die an ``pol`` angrenzen."""
    others: set[EntityId] = set()
    for rid in pol.territory:
        for neighbor in world.regions[rid].nachbarn:
            owner = world.regions[neighbor].owner
            if owner is not None and owner != pol.id:
                others.add(owner)
    return sorted(others)


def _free_neighbor(world: World, pol: Polity) -> EntityId | None:
    """Bestes freies Nachbarfeld: hoechste Nahrungskapazitaet, Gleichstand: kleinste id."""
    candidates: set[EntityId] = set()
    for region_id in pol.territory:
        for neighbor in world.regions[region_id].nachbarn:
            if world.regions[neighbor].owner is None:
                candidates.add(neighbor)
    if not candidates:
        return None
    return max(
        sorted(candidates),
        key=lambda rid: (world.regions[rid].food_capacity, -rid),
    )


def _contested_region(world: World, winner: EntityId, loser: EntityId) -> EntityId | None:
    """Eine nicht-Hauptstadt-Region des Verlierers an der Grenze zum Sieger."""
    pw = world.polities[winner]
    pl = world.polities[loser]
    winner_fields = set(pw.territory)
    candidates: list[EntityId] = []
    for rid in pl.territory:
        if rid == pl.capital:
            continue
        if winner_fields.intersection(world.regions[rid].nachbarn):
            candidates.append(rid)
    if not candidates:
        return None
    return max(candidates, key=lambda rid: (world.regions[rid].food_capacity, -rid))


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _recent_pair_events(
    log: EventLog,
    year: int,
    kind: EventKind,
    a: EntityId,
    b: EntityId,
    window: int,
) -> list[EventId]:
    """EventIds gegebener Art mit a UND b in ``subjects`` innerhalb des Fensters."""
    pair = {a, b}
    return [
        e.id
        for e in log.by_kind(kind)
        if year - e.year <= window and pair <= set(e.subjects)
    ]


def _recent_subject_event(
    log: EventLog, year: int, kind: EventKind, subject: EntityId, window: int
) -> EventId | None:
    """Juengste EventId gegebener Art mit ``subject`` innerhalb des Fensters."""
    found = _recent_subject_event_all(log, year, kind, subject, window)
    return found[-1] if found else None


def _recent_subject_event_all(
    log: EventLog, year: int, kind: EventKind, subject: EntityId, window: int
) -> list[EventId]:
    """Alle EventIds gegebener Art mit ``subject`` innerhalb des Fensters (id-sortiert)."""
    return [
        e.id
        for e in log.by_kind(kind)
        if year - e.year <= window and subject in e.subjects
    ]
