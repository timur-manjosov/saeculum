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

from worldsim.config import Config
from worldsim.events import (
    Decision,
    Effect,
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
    Identity,
    NationTraits,
    Polity,
    Ruler,
    Stockpile,
    World,
)
from worldsim.names import make_name
from worldsim.rng import Stream

__all__ = [
    "System",
    "consumption",
    "diplomacy",
    "expansion",
    "forge_ruler",
    "founding",
    "friction",
    "identity",
    "population",
    "production",
    "ruler",
    "war",
]

# Ein System ist eine reine Funktion mit fester Signatur.
System = Callable[[World, Stream, Config, EventLog], World]


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
        death_event = _age_and_maybe_die(world, pol, rng, cfg, log)
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
    """Territorium erzeugt Ressourcen; die Nahrungsernte schwankt jaehrlich."""
    low, high = 1.0 - cfg.harvest_variance, 1.0 + cfg.harvest_variance
    for pid in sorted(world.polities):
        pol = world.polities[pid]
        harvest = rng.uniform(low, high)
        pol.stockpiles.nahrung += _land_capacity(world, pol, cfg) * harvest
        pol.stockpiles.wohlstand += len(pol.territory) * cfg.wealth_per_region
    return world


def consumption(world: World, rng: Stream, cfg: Config, log: EventLog) -> World:
    """Bevoelkerung verbraucht Nahrung; ueberschuessiger Vorrat verdirbt (gedeckelt)."""
    for pid in sorted(world.polities):
        pol = world.polities[pid]
        need = pol.population * cfg.food_per_person
        if pol.stockpiles.nahrung >= need:
            pol.stockpiles.nahrung -= need
            pol.food_deficit = 0.0
        else:
            pol.food_deficit = need - pol.stockpiles.nahrung
            pol.stockpiles.nahrung = 0.0
        storage_cap = cfg.food_storage_factor * _land_capacity(world, pol, cfg)
        pol.stockpiles.nahrung = min(pol.stockpiles.nahrung, storage_cap)
    return world


def population(world: World, rng: Stream, cfg: Config, log: EventLog) -> World:
    """Logistisches Wachstum zur Tragfaehigkeit; Hunger schrumpft die Bevoelkerung."""
    for pid in sorted(world.polities):
        pol = world.polities[pid]
        before = pol.population

        if pol.food_deficit > 0.0:
            deaths = min(before, int(pol.food_deficit * cfg.famine_deaths_per_deficit))
            if deaths > 0:
                pol.population = before - deaths
                log.append(
                    EventDraft(
                        year=world.year,
                        kind=EventKind.HUNGERSNOT,
                        subjects=(pid,),
                        factors=(Factor(FactorLabel.NAHRUNGSDEFIZIT, pol.food_deficit),),
                        effects=(Effect(pid, "population", before, pol.population),),
                    )
                )
            continue

        capacity = _land_capacity(world, pol, cfg) / cfg.food_per_person
        if capacity <= 0:
            continue
        growth = int(before * cfg.growth_rate * (1.0 - before / capacity))
        if growth <= 0:
            continue
        after = before + growth
        pol.population = after

        crossed = [m for m in cfg.population_milestones if pol.peak_population < m <= after]
        if after > pol.peak_population:
            pol.peak_population = after
        for _ in crossed:
            log.append(
                EventDraft(
                    year=world.year,
                    kind=EventKind.BEVOELKERUNG_MEILENSTEIN,
                    subjects=(pid,),
                    factors=(Factor(FactorLabel.BEVOELKERUNGSWACHSTUM, float(growth)),),
                    effects=(Effect(pid, "population", before, after),),
                )
            )
    return world


def expansion(world: World, rng: Stream, cfg: Config, log: EventLog) -> World:
    """Faktorbasierte Entscheidung, ein freies Nachbarfeld zu beanspruchen."""
    for pid in sorted(world.polities):
        pol = world.polities[pid]
        if pol.food_deficit > 0.0:
            continue
        affordable = pol.stockpiles.wohlstand - cfg.expand_wealth_cost
        if affordable < 0.0:
            continue
        target = _free_neighbor(world, pol)
        if target is None:
            continue

        capacity = _land_capacity(world, pol, cfg)
        surplus = pol.stockpiles.nahrung / capacity if capacity > 0 else 0.0
        traits = _effective_traits(world, pol)
        decision = Decision()
        decision.add(FactorLabel.EXPANSIONSDRANG, traits.expansion)
        decision.add(FactorLabel.NAHRUNGSUEBERSCHUSS, surplus)
        decision.add(FactorLabel.WOHLSTAND, min(affordable / cfg.expand_wealth_cost, 1.0))
        decision.add(FactorLabel.VORSICHT, -traits.caution * 0.5)
        if not decision.passes(cfg.expand_threshold):
            continue

        pol.stockpiles.wohlstand -= cfg.expand_wealth_cost
        world.regions[target].owner = pid
        pol.territory = tuple(sorted((*pol.territory, target)))
        log.append(
            EventDraft(
                year=world.year,
                kind=EventKind.EXPANSION,
                subjects=(pid, target),
                factors=decision.as_factors(),
                causes=decision.as_causes(),
                effects=(Effect(target, "owner", None, pid),),
            )
        )
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
            if other in pol.allies:
                continue
            before = pol.friction.get(other, 0.0)
            after = min(before + cfg.friction_growth * pressure, cfg.friction_cap)
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
    """Furcht neu berechnen, Trust fortschreiben, Buendnisse bilden/brechen.

    Kern-Regel "verbuende dich gegen den Staerksten" (Balance of Power):
    nicht-staerkste Nationen, die denselben Hegemon fuerchten und einander trauen,
    schliessen ein Buendnis. Es bricht bei Trust-Verfall oder wenn der gemeinsame
    Feind seine Vormacht verliert.
    """
    pids = sorted(world.polities)
    powers = {pid: _power(world.polities[pid]) for pid in pids}
    strongest = max(pids, key=lambda p: (powers[p], -p))

    _recompute_fear(world, pids, powers, cfg)
    _drift_trust(world, cfg)
    # Bestehende Buendnisse zuerst pruefen, damit ein frisch geschlossenes nicht
    # im selben Tick wieder zerbricht.
    _break_alliances(world, pids, cfg, log)
    _form_alliances(world, pids, powers, strongest, cfg, log)
    return world


def war(world: World, rng: Stream, cfg: Config, log: EventLog) -> World:
    """Kriegswunsch je Nachbar als Faktorsumme; ueber Schwelle ⇒ Krieg + Schlacht.

    Pro Tick fuehrt eine Nation hoechstens einen Krieg; ein bereits beteiligter
    Gegner wird in diesem Tick nicht erneut verwickelt.
    """
    pids = sorted(world.polities)
    powers = {pid: _power(world.polities[pid]) for pid in pids}
    busy: set[EntityId] = set()

    for x in pids:
        if x in busy:
            continue
        pol = world.polities[x]
        # Globale Kriegsmuedigkeit: nach einem Krieg ruht die Nation eine Weile.
        if pol.last_war and world.year - max(pol.last_war.values()) < cfg.war_global_cooldown_years:
            continue
        best_target: EntityId | None = None
        best_score = cfg.war_threshold
        best_decision: Decision | None = None

        for y in _bordering_nations(world, pol):
            if y in pol.allies or y in busy:
                continue
            # Kriegsmuedigkeit: nach einem Krieg eine Weile kein neuer gegen Y.
            if world.year - pol.last_war.get(y, -10_000) < cfg.war_cooldown_years:
                continue
            decision = _war_desire(world, x, y, powers, cfg, log)
            if decision.score > best_score:
                best_score = decision.score
                best_target = y
                best_decision = decision

        if best_target is not None and best_decision is not None:
            _wage_war(world, x, best_target, best_decision, rng, cfg, log)
            busy.add(x)
            busy.add(best_target)
    return world


def _war_desire(
    world: World,
    x: EntityId,
    y: EntityId,
    powers: dict[EntityId, float],
    cfg: Config,
    log: EventLog,
) -> Decision:
    """Baue den Kriegswunsch von X gegen Y als benannte Faktorsumme."""
    px = world.polities[x]
    et_x = _effective_traits(world, px)
    decision = Decision()

    # Effektive Macht schliesst Verbuendete ein (Balance of Power); der Faktor
    # ist gedeckelt, damit rohe Ueberlegenheit kein endloser Kriegsgrund ist.
    advantage = (_effective_power(world, x, powers, cfg) - _effective_power(world, y, powers, cfg))
    advantage = _clamp(advantage / cfg.power_reference, -cfg.advantage_cap, cfg.advantage_cap)
    decision.add(FactorLabel.MILITAERVORTEIL, advantage)
    decision.add(FactorLabel.AGGRESSION, et_x.aggression)

    # Affinitaet (Phase 4): fremder Glaube rechtfertigt den Krieg leichter. Wird
    # dieser Faktor zum Hauptantrieb, gilt der Krieg als Glaubenskrieg (chronicle).
    py_ident = world.polities[y].identity_id
    if py_ident is not None and py_ident != px.identity_id:
        decision.add(FactorLabel.GLAUBENSGRABEN, cfg.identity_war_friction)

    # Persoenliche Rivalitaet: zwei aggressive Herrscher heizen den Krieg an.
    et_y = _effective_traits(world, world.polities[y])
    if (
        et_x.aggression >= cfg.personal_aggression_threshold
        and et_y.aggression >= cfg.personal_aggression_threshold
    ):
        decision.add(FactorLabel.PERSOENLICHE_RIVALITAET, cfg.personal_rivalry_weight)

    friction_events = _recent_pair_events(
        log, world.year, EventKind.GRENZREIBUNG, x, y, cfg.cause_window_years
    )
    decision.add(
        FactorLabel.GRENZREIBUNG,
        px.friction.get(y, 0.0) * cfg.war_friction_weight,
        causes=friction_events,
    )

    if px.food_deficit > 0.0:
        decision.add(FactorLabel.RESSOURCENDRUCK, 1.0)

    weakness = 0.0
    weakness_causes: list[EventId] = []
    if _power_of(world, y, powers) < _power_of(world, x, powers) * cfg.weakness_power_ratio:
        weakness += cfg.weakness_bonus
    ally_loss = _recent_subject_event(
        log, world.year, EventKind.BUENDNIS_BRUCH, y, cfg.cause_window_years
    )
    if ally_loss is not None:
        weakness += cfg.ally_loss_bonus
        weakness_causes.append(ally_loss)
    decision.add(FactorLabel.ZIEL_SCHWAECHE, weakness, causes=weakness_causes)

    trust = px.relations.get(y, 0.0)
    if trust < 0.0:
        decision.add(FactorLabel.MISSTRAUEN, -trust)
    else:
        decision.add(FactorLabel.VERTRAUEN, -trust * 0.5)

    decision.add(FactorLabel.FURCHT, -px.fear.get(y, 0.0))
    decision.add(FactorLabel.VORSICHT, -et_x.caution)
    return decision


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
    powers = {p: _power(world.polities[p]) for p in sorted(world.polities)}
    jitter = rng.uniform(-cfg.battle_jitter, cfg.battle_jitter)
    margin = (
        _effective_power(world, x, powers, cfg) - _effective_power(world, y, powers, cfg)
    ) / cfg.power_reference + jitter
    winner, loser = (x, y) if margin >= 0.0 else (y, x)
    pw, pl = world.polities[winner], world.polities[loser]

    loser_before = pl.population
    pl.population = max(0, loser_before - int(loser_before * cfg.war_loser_losses))
    pw.population = max(0, pw.population - int(pw.population * cfg.war_winner_losses))

    effects: list[Effect] = []
    region = _contested_region(world, winner, loser)
    if region is not None:
        world.regions[region].owner = winner
        pl.territory = tuple(r for r in pl.territory if r != region)
        pw.territory = tuple(sorted((*pw.territory, region)))
        effects.append(Effect(region, "owner", loser, winner))
    effects.append(Effect(loser, "population", loser_before, pl.population))

    win_margin = (_power(pw) - _power(pl)) / cfg.power_reference
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

    # Nachklang: Trust sinkt, Groll bleibt. Honor des Opfers skaliert die Reaktion.
    px.relations[y] = _clamp(px.relations.get(y, 0.0) - cfg.trust_drop_on_attack)
    honor_y = _effective_traits(world, py).honor
    py.relations[x] = _clamp(
        py.relations.get(x, 0.0) - cfg.trust_drop_on_attack * (0.5 + honor_y)
    )
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
        _maybe_personal_death(world, loser, battle_id, rng, cfg, log)


def _maybe_personal_death(
    world: World,
    loser: EntityId,
    battle_id: EventId,
    rng: Stream,
    cfg: Config,
    log: EventLog,
) -> None:
    """In einem persoenlichen Krieg faellt der Herrscher des Verlierers mit Chance.

    Der Tod wird kausal an die Schlacht gehaengt; die Sukzession erfolgt noch im
    selben Tick (der ``ruler``-Lauf ist bereits vorbei) ueber den ``war``-Strom,
    damit kein Tick mit totem Herrscher endet.
    """
    pol = world.polities[loser]
    rid = pol.leader
    if rid is None:
        return
    fallen = world.rulers.get(rid)
    if fallen is None or not fallen.alive:
        return
    if rng.random() >= cfg.personal_death_chance:
        return
    fallen.alive = False
    death_id = log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.TOD_FIGUR,
            subjects=(loser, rid),
            factors=(Factor(FactorLabel.PERSOENLICHE_RIVALITAET, 1.0),),
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
    mode: AccessionMode | None = None,
) -> Ruler:
    """Erzeuge einen Herrscher deterministisch aus dem Strom (feste Ziehreihenfolge).

    Auch von ``worldgen`` fuer die Anfangsherrscher genutzt, damit Anfangs- und
    Nachfolge-Herrscher dieselbe Konstruktion teilen. ``mode=None`` zieht den
    Machtantritt (Erbe/Wahl/Usurpation); sonst wird er vorgegeben.
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
    if mode is None:
        mode = _draw_accession(rng, cfg)
    name = make_name(rng)
    return Ruler(
        id=ruler_id,
        name=name,
        trait_deltas=deltas,
        age=age,
        lifespan=lifespan,
        accession=mode,
        legitimacy=_legitimacy_for(mode, cfg),
    )


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
    world: World, pol: Polity, rng: Stream, cfg: Config, log: EventLog
) -> EventId | None:
    """Altere den Herrscher um ein Jahr; bei Hazard-Treffer Tod-Event emittieren."""
    rid = pol.leader
    if rid is None:
        return None
    r = world.rulers.get(rid)
    if r is None or not r.alive:
        return None
    r.age += 1
    if rng.random() >= _death_probability(r, cfg):
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


def _death_probability(r: Ruler, cfg: Config) -> float:
    """Sterbe-Hazard: 0 bis zum Onset, dann linear bis 0.5, ab Lebensspanne sicher."""
    if r.age >= r.lifespan:
        return 1.0
    onset = r.lifespan * cfg.ruler_mortality_onset
    if r.age < onset:
        return 0.0
    return 0.5 * (r.age - onset) / (r.lifespan - onset)


def _succeed(
    world: World,
    pol: Polity,
    rng: Stream,
    cfg: Config,
    log: EventLog,
    cause: EventId | None,
) -> tuple[EventId, Ruler]:
    """Setze einen Nachfolger ein und emittiere das SUKZESSION-Event (caused-by Tod)."""
    old = world.rulers.get(pol.leader) if pol.leader is not None else None
    new = forge_ruler(world.next_id, rng, cfg)
    world.next_id += 1
    # Wendepunkt-Flag: grosser Trait-Sprung gegenueber dem Vorgaenger.
    new.turning_point = (
        old is not None and _delta_distance(old, new) >= cfg.turning_point_delta
    )
    world.rulers[new.id] = new
    pol.leader = new.id

    # Die Faktoren beschreiben das Fundament der neuen Herrschaft (kein Gate).
    factors = [Factor(FactorLabel.LEGITIMITAET, new.legitimacy)]
    if new.accession == AccessionMode.INHERITED:
        factors.append(Factor(FactorLabel.ERBFOLGE, 1.0))
    else:
        factors.append(Factor(FactorLabel.THRONSTREIT, 1.0))
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


def _draw_accession(rng: Stream, cfg: Config) -> AccessionMode:
    """Ziehe den Machtantritt: meist Erbe, bei Unsicherheit Usurpation/Wahl."""
    if rng.random() < cfg.heir_uncertainty:
        return AccessionMode.USURPED if rng.random() < 0.5 else AccessionMode.ELECTED
    return AccessionMode.INHERITED


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
    """Gruende die Abspaltung als neue Nation (eigene id, eigener Herrscher)."""
    total_regions = len(parent.territory)
    k = len(blob)
    blob_set = set(blob)

    new_pid = world.next_id
    world.next_id += 1
    new_ruler = forge_ruler(world.next_id, rng, cfg, mode=AccessionMode.USURPED)
    world.next_id += 1
    world.rulers[new_ruler.id] = new_ruler

    new_capital = max(blob, key=lambda r: (world.regions[r].food_capacity, -r))
    for r in blob:
        world.regions[r].owner = new_pid

    # Bevoelkerung und Lager anteilig nach Regionszahl aufteilen.
    moved_pop = int(parent.population * k / total_regions)
    pop_before = parent.population
    parent.population = max(1, parent.population - moved_pop)
    parent.peak_population = max(parent.peak_population, parent.population)
    moved_food = parent.stockpiles.nahrung * k / total_regions
    moved_wealth = parent.stockpiles.wohlstand * k / total_regions
    parent.stockpiles.nahrung -= moved_food
    parent.stockpiles.wohlstand -= moved_wealth
    parent.territory = tuple(sorted(r for r in parent.territory if r not in blob_set))

    new_pol = Polity(
        id=new_pid,
        name=make_name(rng),
        capital=new_capital,
        territory=tuple(sorted(blob)),
        founded_year=world.year,
        population=max(1, moved_pop),
        peak_population=max(1, moved_pop),
        stockpiles=Stockpile(nahrung=moved_food, wohlstand=moved_wealth),
        # Kulturelle Kontinuitaet: gleiche Basis-Traits, abweichender Herrscher.
        traits=parent.traits,
        leader=new_ruler.id,
        # Glaubens-Kontinuitaet: die Abspaltung teilt zunaechst die Identitaet.
        identity_id=parent.identity_id,
    )
    # Gegenseitiges Misstrauen und frischer Groll zwischen Tochter und Mutterland.
    parent.relations[new_pid] = -cfg.secession_distrust
    new_pol.relations[parent.id] = -cfg.secession_distrust
    parent.friction[new_pid] = cfg.grudge_floor
    new_pol.friction[parent.id] = cfg.grudge_floor
    world.polities[new_pid] = new_pol

    effects = [Effect(r, "owner", parent.id, new_pid) for r in sorted(blob)]
    effects.append(Effect(parent.id, "population", pop_before, parent.population))
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
            subjects=(parent.id, new_pid, new_capital),
            factors=decision.as_factors(),
            causes=causes,
            effects=tuple(effects),
        )
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
    powers = {pid: _power(world.polities[pid]) for pid in sorted(world.polities)}
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
    world.identities[new_id] = Identity(id=new_id, name=make_name(rng), parent=old_faith)
    pol.identity_id = new_id

    # Ehemalige Glaubensbrueder unter den Verbuendeten: das Band zerbricht.
    broken = [a for a in pol.allies if world.polities[a].identity_id == old_faith]
    effects = [Effect(pid, "identity_id", old_faith, new_id)]
    for ally in broken:
        effects.append(Effect(pid, "ally_lost", ally, None))
    schisma_id = log.append(
        EventDraft(
            year=world.year,
            kind=EventKind.SCHISMA,
            subjects=(pid, new_id, old_faith),
            factors=decision.as_factors(),
            causes=(accession,),
            effects=tuple(effects),
        )
    )
    for ally in broken:
        pol.allies = tuple(a for a in pol.allies if a != ally)
        other = world.polities[ally]
        other.allies = tuple(a for a in other.allies if a != pid)
        log.append(
            EventDraft(
                year=world.year,
                kind=EventKind.BUENDNIS_BRUCH,
                subjects=(min(pid, ally), max(pid, ally)),
                factors=(Factor(FactorLabel.GLAUBENSSPALTUNG, 1.0),),
                causes=(schisma_id,),
            )
        )


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


def _drift_trust(world: World, cfg: Config) -> None:
    """Friedliche Nachbarschaft baut Trust langsam auf; Honor verstaerkt Reziprozitaet."""
    for pid in sorted(world.polities):
        pol = world.polities[pid]
        honor = _effective_traits(world, pol).honor
        for other in _bordering_nations(world, pol):
            current = pol.relations.get(other, 0.0)
            drift = cfg.trust_drift * (0.5 + honor)
            pol.relations[other] = _clamp(current + drift)


def _form_alliances(
    world: World,
    pids: list[EntityId],
    powers: dict[EntityId, float],
    strongest: EntityId,
    cfg: Config,
    log: EventLog,
) -> None:
    """Bilde Buendnisse zweier nicht-staerkster Nationen gegen den Hegemon."""
    for i, a in enumerate(pids):
        for b in pids[i + 1 :]:
            if a == strongest or b == strongest:
                continue
            pa, pb = world.polities[a], world.polities[b]
            if b in pa.allies:
                continue
            # Buendnis nur bei echtem gemeinsamem Feind: beide muessen den
            # Hegemon tatsaechlich fuerchten (sonst zerbraeche es sofort wieder).
            common_fear = min(pa.fear.get(strongest, 0.0), pb.fear.get(strongest, 0.0))
            if common_fear <= 0.0:
                continue

            decision = Decision()
            decision.add(
                FactorLabel.VERTRAUEN,
                (pa.relations.get(b, 0.0) + pb.relations.get(a, 0.0)) / 2.0,
            )
            decision.add(
                FactorLabel.GEMEINSAMER_FEIND,
                common_fear,
                causes=_recent_subject_event_all(
                    log, world.year, EventKind.BEVOELKERUNG_MEILENSTEIN, strongest,
                    cfg.cause_window_years,
                ),
            )
            decision.add(
                FactorLabel.DIPLOMATIE,
                (
                    _effective_traits(world, pa).diplomacy
                    + _effective_traits(world, pb).diplomacy
                )
                / 2.0,
            )
            # Affinitaet (Phase 4): gleicher Glaube stiftet ein festeres Band.
            if pa.identity_id is not None and pa.identity_id == pb.identity_id:
                decision.add(FactorLabel.GLAUBENSAFFINITAET, cfg.identity_alliance_bonus)
            if not decision.passes(cfg.alliance_threshold):
                continue

            pa.allies = tuple(sorted({*pa.allies, b}))
            pb.allies = tuple(sorted({*pb.allies, a}))
            pa.relations[b] = _clamp(pa.relations.get(b, 0.0) + cfg.trust_gain_on_alliance)
            pb.relations[a] = _clamp(pb.relations.get(a, 0.0) + cfg.trust_gain_on_alliance)
            log.append(
                EventDraft(
                    year=world.year,
                    kind=EventKind.BUENDNIS,
                    subjects=(a, b, strongest),
                    factors=decision.as_factors(),
                    causes=decision.as_causes(),
                )
            )


def _break_alliances(
    world: World, pids: list[EntityId], cfg: Config, log: EventLog
) -> None:
    """Loese Buendnisse bei Trust-Verfall oder wenn der Hegemon nicht mehr droht."""
    powers = {pid: _power(world.polities[pid]) for pid in pids}
    strongest = max(pids, key=lambda p: (powers[p], -p))

    for a in pids:
        pa = world.polities[a]
        for b in list(pa.allies):
            if b <= a:  # jeden Bruch nur einmal behandeln (von der kleineren id aus)
                continue
            pb = world.polities[b]
            trust = min(pa.relations.get(b, 0.0), pb.relations.get(a, 0.0))
            no_common_threat = (
                pa.fear.get(strongest, 0.0) <= 0.0 and pb.fear.get(strongest, 0.0) <= 0.0
            )
            if trust >= cfg.alliance_break_trust and not no_common_threat:
                continue

            pa.allies = tuple(x for x in pa.allies if x != b)
            pb.allies = tuple(x for x in pb.allies if x != a)
            log.append(
                EventDraft(
                    year=world.year,
                    kind=EventKind.BUENDNIS_BRUCH,
                    subjects=(a, b),
                    factors=(Factor(FactorLabel.MISSTRAUEN, -trust + 0.5),),
                )
            )


# === reine Helfer ===========================================================

def _power(pol: Polity) -> float:
    """Schlagkraft (Phase 2 abgeleitet aus Bevoelkerung; Tech/Oekonomie folgen)."""
    return float(pol.population)


def _power_of(world: World, pid: EntityId, powers: dict[EntityId, float]) -> float:
    """Macht aus dem Snapshot; faellt auf Live-Berechnung zurueck.

    Der Snapshot wird je System einmal gebildet; entsteht **innerhalb** des Ticks
    eine neue Nation (z. B. eine Abspaltung nach einem persoenlichen Krieg), fehlt
    sie im Snapshot — dann gilt ihre aktuelle Macht.
    """
    cached = powers.get(pid)
    return cached if cached is not None else _power(world.polities[pid])


def _effective_power(
    world: World, pid: EntityId, powers: dict[EntityId, float], cfg: Config
) -> float:
    """Eigene Macht plus anteiligen Beitrag der Verbuendeten (Koalition)."""
    pol = world.polities[pid]
    total = _power_of(world, pid, powers)
    for ally in pol.allies:
        total += _power_of(world, ally, powers) * cfg.ally_power_contribution
    return total


def _land_capacity(world: World, pol: Polity, cfg: Config) -> float:
    """Mittlere Jahres-Nahrungskapazitaet des Territoriums (ohne Ernteschwankung)."""
    return (
        sum(world.regions[r].food_capacity for r in sorted(pol.territory))
        * cfg.food_per_capacity
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
