"""config — zentrale Stellschrauben (Magic Numbers) der Simulation.

Alle Tuning-Parameter leben hier in einer einzigen ``Config``-dataclass mit
Defaults. Keine versteckten Konstanten in Systemen. ``config_version`` ist Teil
der Reproduzierbarkeits-Identitaet ``(seed, years, config_version)``.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DEFAULT_CONFIG", "Config"]


@dataclass(frozen=True)
class Config:
    """Unveraenderliche Sammlung aller Stellschrauben.

    ``frozen``, damit ein Lauf nicht versehentlich seine eigene Konfiguration
    mutiert — die Config ist Teil der Lauf-Identitaet.
    """

    # Reproduzierbarkeits-Identitaet: bei jeder semantischen Aenderung der
    # Defaults erhoehen.
    config_version: int = 8

    # --- Weltgenerierung ---------------------------------------------------
    num_regions: int = 28
    num_nations: int = 6
    region_food_capacity_min: float = 8.0
    region_food_capacity_max: float = 22.0
    # Zusaetzliche Kanten ueber den verbindenden Ring hinaus (Grenzen).
    extra_edges: int = 16
    initial_population: int = 200
    # Anfangsbestaende (Getreide/Eisen/Gold) je Nation.
    initial_getreide: float = 80.0
    initial_eisen: float = 0.0
    initial_gold: float = 0.0

    # --- Schichtung: Anfangs-Zusammensetzung der Bevoelkerung --------------
    # Groessen-Anteile der drei Schichten (Arbeiter/Soldat/Elite), summieren zu 1.
    initial_worker_fraction: float = 0.75
    initial_soldier_fraction: float = 0.10
    initial_elite_fraction: float = 0.15
    # Anfaengliche Wohlstandsanteile (summieren zu 1): die Elite haelt ueber-
    # proportional viel — der eingebaute Keim des Volksdrucks (Verelendung).
    initial_worker_wealth: float = 0.35
    initial_soldier_wealth: float = 0.15
    initial_elite_wealth: float = 0.50

    # --- production: Territorium erzeugt die drei Bestaende -----------------
    # Getreide: Region-Kapazitaet -> Ernte (mit jaehrlicher Schwankung).
    grain_per_capacity: float = 1.0
    # Arbeiter erzeugen das Getreide: so viele Arbeiter voll auslasten eine Einheit
    # Landkapazitaet. Fehlen Arbeiter (starke Militarisierung), sinkt die Ernte
    # (Liebigsches Minimum) — die Guns-versus-Butter-Kopplung.
    workers_per_capacity: float = 5.0
    # Einfache Foerderung je beanspruchter Region: Eisen (Waffen/Werkzeug) und
    # Gold (Schatz). Bewusst schlicht — die reiche Kopplung folgt in spaeteren
    # Aenderungen (Handel, Schichtung).
    iron_per_region: float = 1.0
    gold_per_region: float = 2.0
    # Jaehrliche Ernteschwankung: +/- Anteil um die Kapazitaet (Hunger-Quelle).
    harvest_variance: float = 0.30

    # --- consumption: Bevoelkerung isst Getreide ---------------------------
    food_per_person: float = 0.04
    # Getreide ist schlecht lagerbar: Vorrat ist auf diesen Bruchteil einer
    # Jahreskapazitaet begrenzt, damit schlechte Ernten Hunger ausloesen.
    food_storage_factor: float = 0.35

    # --- Demografie: logistisches Wachstum je Schicht ----------------------
    growth_rate: float = 0.08
    # Tote pro Einheit Nahrungsdefizit bei Hungersnot (verteilt auf alle Schichten).
    famine_deaths_per_deficit: float = 8.0
    # Aufsteigende Schwellen fuer Bevoelkerungs-Meilensteine.
    population_milestones: tuple[int, ...] = (300, 600, 1200, 2400, 5000)
    # Rekrutierung Arbeiter -> Soldat: angestrebter Soldaten-Anteil und der Bruchteil
    # der Luecke, der pro Jahr geschlossen wird (homoeostatisch, ohne Zufall). Krieg
    # zehrt Soldaten, die Nachrekrutierung zieht Arbeiter aus der Getreideproduktion.
    target_soldier_fraction: float = 0.10
    recruit_rate: float = 0.10

    # --- Groll (grievance): baut sich auf, entlaedt sich noch nicht --------
    # Aufbau bei Getreidemangel (unter den unteren Schichten) und bei ungleichem
    # Wohlstandsanteil (haelt eine Schicht weniger als ihren Bevoelkerungsanteil).
    grievance_hunger_rate: float = 0.20
    grievance_inequality_rate: float = 0.30
    # Langsamer Zerfall Richtung 0, wenn kein Druck wirkt (Vergessen/Beschwichtigung).
    grievance_decay: float = 0.05
    # Obergrenze gegen Ausreisser (Kopfraum ueber dem Ungleichheits-Baseline, damit
    # der Mangel-Beitrag sich klar abhebt).
    grievance_cap: float = 8.0

    # --- expansion: Anspruch auf ein angrenzendes freies Feld --------------
    expand_gold_cost: float = 15.0
    # Entscheidungsschwelle fuer die (jetzt faktorbasierte) Expansionswahl.
    expand_threshold: float = 1.0

    # --- diplomacy: Furcht, Trust, Buendnisse (Balance of Power) -----------
    # Trust-Drift pro Jahr zwischen friedlichen Nachbarn (Kooperation).
    trust_drift: float = 0.02
    # Trust-Einbruch beim Angriff (Verrat); Honor des Opfers skaliert die Reaktion.
    trust_drop_on_attack: float = 0.6
    # Bezugsgroesse, um Machtdifferenzen in Furcht/Vorteil zu normieren. Die
    # Schlagkraft ruht jetzt auf Soldaten (statt roher Bevoelkerung), daher kleiner.
    power_reference: float = 300.0
    # Schlagkraft ist abgeleitet aus Soldaten, Eisen und Gold: Soldaten sind die
    # Basis, Bewaffnung (Eisen) und Sold (Gold) heben sie je bis zu einem Bonus.
    iron_per_soldier: float = 1.0
    gold_per_soldier: float = 2.0
    power_equip_bonus: float = 0.5
    power_pay_bonus: float = 0.5
    # Obergrenze fuer die pro Tick berechnete Furcht (verhindert Ausreisser).
    fear_cap: float = 3.0
    # Beitrag eines Verbuendeten zur effektiven Macht (Balance of Power wirkt im
    # Krieg: eine Koalition gegen den Staerksten kann ihn abschrecken/schlagen).
    ally_power_contribution: float = 0.6
    # Buendnis-Entscheidungsschwelle und Trust-Bruchschwelle.
    alliance_threshold: float = 1.0
    alliance_break_trust: float = -0.25
    # Trust-Gewinn beim Buendnisschluss.
    trust_gain_on_alliance: float = 0.3

    # --- war: Kriegswunsch als Faktorsumme ---------------------------------
    war_threshold: float = 1.2
    # Kriegsmuedigkeit: so viele Jahre kein neuer Krieg gegen dasselbe Ziel ...
    war_cooldown_years: int = 8
    # ... und ueberhaupt kein neuer Krieg (gegen irgendwen) so lange nach einem.
    war_global_cooldown_years: int = 4
    # Deckel auf den Militaervorteil-Faktor: rohe Staerke ist kein Freibrief.
    advantage_cap: float = 1.5
    # Gewicht der akkumulierten Grenzreibung im Kriegswunsch.
    war_friction_weight: float = 0.25
    # Ziel gilt als schwach, wenn seine Macht unter diesem Anteil des Angreifers liegt.
    weakness_power_ratio: float = 0.7
    weakness_bonus: float = 0.5
    # Zusatzgewicht, wenn das Ziel kuerzlich einen Verbuendeten verlor.
    ally_loss_bonus: float = 0.6
    # Jaehrlicher Zuwachs an Grenzreibung zwischen rivalisierenden Nachbarn.
    friction_growth: float = 0.15
    # Obergrenze der akkumulierten Reibung (sonst eskaliert sie unbegrenzt).
    friction_cap: float = 4.0
    # Schwelle, ab der akkumulierte Reibung ein GRENZREIBUNG-Event ausloest.
    friction_event_step: float = 1.0
    # Wie viele Jahre zurueck Krieg ausloesende Reibungs-/Buendnis-Events zitiert.
    cause_window_years: int = 12
    # Bevoelkerungsverlust des Verlierers/Gewinners als Anteil bei einer Schlacht.
    war_loser_losses: float = 0.12
    war_winner_losses: float = 0.04
    # Zufalls-Jitter im Machtvergleich der Schlacht (benannter Faktor "Zufall").
    battle_jitter: float = 0.15
    # Ein Krieg LOEST Spannung; danach bleibt nur dieser Groll-Restbetrag (Reibung
    # wird auf diesen Wert zurueckgesetzt, baut sich dann ueber Jahre neu auf).
    grudge_floor: float = 1.0

    # --- ruler: Herrscher als duenne Trait-Ueberlagerung -------------------
    # Lebensspanne (Jahre) und Alter beim Machtantritt, je deterministisch gezogen.
    ruler_lifespan_min: int = 45
    ruler_lifespan_max: int = 75
    ruler_accession_age_min: int = 18
    ruler_accession_age_max: int = 40
    # Sterbe-Hazard ist 0, bis das Alter diesen Anteil der Lebensspanne erreicht,
    # dann steigt er linear bis 0.5 an der Lebensspanne (danach sicher).
    ruler_mortality_onset: float = 0.6
    # Maximaler Betrag eines Herrscher-Trait-Deltas (+/-) auf die Basis-Traits.
    ruler_trait_delta: float = 0.30
    # Wahrscheinlichkeit, dass kein klarer Erbe existiert (Usurpation/Wahl statt Erbe).
    heir_uncertainty: float = 0.25
    # Anfangs-Legitimitaet je Machtantritt.
    legitimacy_inherited: float = 0.75
    legitimacy_elected: float = 0.55
    legitimacy_usurped: float = 0.30
    # Trait-Sprung-Schwelle (Summe der |Delta-Differenzen| ueber fuenf Traits,
    # Mittel ~1.0), ab der ein Machtwechsel als potenzieller Wendepunkt (Phase 5)
    # markiert wird. ~1.3 ⇒ nur das obere Fuenftel der Wechsel gilt als Bruch.
    turning_point_delta: float = 1.30

    # --- Sukzessionskrise & Fragmentierung ---------------------------------
    # Faktorbasierte Entscheidung; ueber der Schwelle spaltet sich ein Reichsteil ab.
    fragmentation_threshold: float = 1.20
    # Legitimitaets-Referenz: die Luecke darunter treibt die Fragmentierung.
    fragmentation_legit_ref: float = 0.60
    fragmentation_legit_weight: float = 2.0
    # Zusatzgewicht bei strittigem Machtantritt (Usurpation/Wahl).
    fragmentation_dispute_bonus: float = 0.5
    # Ab dieser Reichsgroesse zaehlt jede weitere Region als Ueberdehnung.
    overextension_size: int = 4
    fragmentation_size_weight: float = 0.30
    # Nur teilbar, wenn mindestens so viele Regionen vorhanden sind (Hauptstadt bleibt).
    secession_min_territory: int = 3
    # Anfangs-Misstrauen zwischen Abspaltung und Mutterland.
    secession_distrust: float = 0.30

    # --- persoenliche Rivalitaet (schlank) ---------------------------------
    # Ab dieser effektiven Aggression beider Herrscher gilt ein Krieg als persoenlich.
    personal_aggression_threshold: float = 0.60
    personal_rivalry_weight: float = 0.30
    # Wahrscheinlichkeit, dass ein persoenlicher Krieg den Herrscher des Verlierers toetet.
    personal_death_chance: float = 0.40

    # --- identity: EINE Identitaets-/Affinitaetsdimension (Phase 4) --------
    # Anzahl der Anfangs-Identitaeten (< num_nations ⇒ Nationen teilen Glauben).
    num_identities: int = 3
    # Affinitaet als benannter Faktor in bestehenden Entscheidungen: gleicher
    # Glaube erleichtert das Buendnis, fremder erleichtert den Krieg.
    identity_alliance_bonus: float = 0.5
    identity_war_friction: float = 0.4
    # Konversion: eine viel schwaechere Nation uebernimmt den Glauben eines
    # dominanten andersglaeubigen Nachbarn (dominante Nationen verbreiten Identitaet).
    conversion_power_ratio: float = 1.8  # Nachbar muss so viel maechtiger sein
    conversion_threshold: float = 1.0
    conversion_dominance_weight: float = 1.0
    conversion_dominance_cap: float = 2.5
    conversion_honor_resist: float = 1.0  # Ehre (Glaubenstreue) widersteht Konversion
    # Nach einer Konversion bleibt der neue Glaube so viele Jahre stabil (kein
    # jaehrliches Hin-und-Her eines Pufferstaats zwischen zwei Grossmaechten).
    conversion_cooldown_years: int = 12
    # Schisma: ein frisch aufgestiegener zelotischer Herrscher (oder schiere
    # Groesse der Identitaet) spaltet gelegentlich eine neue Identitaet ab. Der
    # Ausloeser ist an einen kuerzlichen Machtantritt gebunden ⇒ selten (an
    # Generationswechsel gekoppelt) und einmalig je Herrscher.
    schism_threshold: float = 1.2
    schism_min_followers: int = 2  # nur teilbare Identitaeten mit >=2 Nationen
    schism_size_weight: float = 0.5  # je weiterer Nation ueber eine hinaus
    schism_zeal_ref: float = 0.6  # effektive Ehre darueber zaehlt als Glaubenseifer
    schism_zeal_weight: float = 2.0
    # Nur so viele Jahre nach dem Machtantritt kann der neue Herrscher ein Schisma
    # ausloesen (kleines Fenster ⇒ ein Impuls je Thronwechsel, kein Dauerdruck).
    schism_window_years: int = 1

    # --- research/Tech: Wissen akkumuliert, Schwellen schalten Zeitalter frei ---
    # Grund-Wissenszuwachs je Jahr, durch den innovation-Trait und die Bevoelkerung
    # skaliert (grosse, erfinderische Reiche forschen schneller).
    research_base_rate: float = 1.0
    research_pop_scale: float = 800.0
    # Aufsteigende Wissens-Schwellen je Tech-Stufe; Ueberschreiten ⇒ INNOVATION.
    tech_thresholds: tuple[float, ...] = (40.0, 120.0, 280.0)
    # Namen der durch die Tech-Stufen erreichten Zeitalter (parallel dazu).
    tech_age_names: tuple[str, ...] = (
        "the Bronze Age",
        "the Iron Age",
        "the Industrial Age",
    )
    # Produktions- und Militaerbonus je erreichter Tech-Stufe.
    tech_production_bonus: float = 0.15
    tech_power_bonus: float = 0.25

    # --- disaster: stochastische Schocks, die Gleichgewichte stoeren -----------
    # Pest: trifft dichte (grosse) Reiche eher, kostet einen Bevoelkerungsanteil,
    # kann auf einen Nachbarn ueberspringen (Ansteckung).
    plague_base_chance: float = 0.010
    plague_density_scale: float = 2500.0
    plague_pop_loss: float = 0.30
    plague_spread_chance: float = 0.40
    # Erdbeben: zerstoert Wohlstand, etwas Bevoelkerung und vernarbt dauerhaft die
    # Nahrungskapazitaet der Hauptstadtregion (bleibende geografische Folge).
    quake_chance: float = 0.012
    quake_wealth_loss: float = 0.60
    quake_pop_loss: float = 0.05
    quake_capacity_scar: float = 0.15
    # Duerre: vernichtet den Nahrungsvorrat und kostet direkt Bevoelkerung.
    drought_chance: float = 0.015
    drought_pop_loss: float = 0.08

    # --- Wendepunkt-Erkennung & Zeitalter (Phase 5) ---------------------------
    # Machtranking: der neue Hegemon muss den alten um diese Marge uebertreffen
    # (Hysterese gegen Flattern bei knappen Machtverhaeltnissen).
    turning_hegemon_margin: float = 1.15
    # Dominante Identitaet: die neue Groesste muss die alte klar (um diese Marge)
    # schlagen — sonst flattert der "dominante Glaube" bei knappen Verhaeltnissen.
    turning_faith_margin: float = 1.6
    # Buendnis: nur der Bruch eines mindestens so langlebigen Buendnisses zaehlt.
    turning_alliance_min_years: int = 25
    # Territoriums-Kollaps: Verlust von mindestens diesem Anteil des Hoechststands.
    turning_collapse_fraction: float = 0.5
    turning_collapse_min_peak: int = 4
    # Fenster (Jahre) fuer die Suche nach der nahen Ursache eines Wendepunkts.
    turning_cause_window: int = 8

    # --- chronicle: kausale Zentralitaet als Wichtigkeits-Faktor --------------
    # Jede im Kausalgraphen erreichbare Folge hebt die Wichtigkeit eines Events
    # (hochzentrale Ereignisse praegen die Chronik), gedeckelt gegen Ausreisser.
    centrality_weight: float = 0.12
    centrality_cap: float = 3.0

    # --- chronicle: Wichtigkeits-Schwelle fuer die Text-Chronik ------------
    # Foundings/Expansionen/Meilensteine liegen darueber; kleine Hungersnoete
    # (geringe Verluste) fallen heraus — die Schwelle filtert echtes Rauschen.
    chronicle_min_importance: float = 2.0


# Ein einziger, geteilter Default. Driver verwendet ihn, wenn nichts uebergeben
# wird.
DEFAULT_CONFIG = Config()
