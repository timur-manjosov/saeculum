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
    config_version: int = 4

    # --- Weltgenerierung ---------------------------------------------------
    num_regions: int = 28
    num_nations: int = 6
    region_food_capacity_min: float = 8.0
    region_food_capacity_max: float = 22.0
    # Zusaetzliche Kanten ueber den verbindenden Ring hinaus (Grenzen).
    extra_edges: int = 16
    initial_population: int = 200
    initial_nahrung: float = 80.0
    initial_wohlstand: float = 0.0

    # --- production: Territorium erzeugt Ressourcen ------------------------
    food_per_capacity: float = 1.0
    wealth_per_region: float = 2.0
    # Jaehrliche Ernteschwankung: +/- Anteil um die Kapazitaet (Hunger-Quelle).
    harvest_variance: float = 0.30

    # --- consumption: Bevoelkerung verbraucht Nahrung ----------------------
    food_per_person: float = 0.04
    # Nahrung ist schlecht lagerbar: Vorrat ist auf diesen Bruchteil einer
    # Jahreskapazitaet begrenzt, damit schlechte Ernten Hunger ausloesen.
    food_storage_factor: float = 0.35

    # --- population: logistisches Wachstum zur Tragfaehigkeit --------------
    growth_rate: float = 0.08
    # Tote pro Einheit Nahrungsdefizit bei Hungersnot.
    famine_deaths_per_deficit: float = 8.0
    # Aufsteigende Schwellen fuer Bevoelkerungs-Meilensteine.
    population_milestones: tuple[int, ...] = (300, 600, 1200, 2400, 5000)

    # --- expansion: Anspruch auf ein angrenzendes freies Feld --------------
    expand_wealth_cost: float = 15.0
    # Entscheidungsschwelle fuer die (jetzt faktorbasierte) Expansionswahl.
    expand_threshold: float = 1.0

    # --- diplomacy: Furcht, Trust, Buendnisse (Balance of Power) -----------
    # Trust-Drift pro Jahr zwischen friedlichen Nachbarn (Kooperation).
    trust_drift: float = 0.02
    # Trust-Einbruch beim Angriff (Verrat); Honor des Opfers skaliert die Reaktion.
    trust_drop_on_attack: float = 0.6
    # Bezugsgroesse, um Machtdifferenzen in Furcht/Vorteil zu normieren.
    power_reference: float = 1500.0
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

    # --- chronicle: Wichtigkeits-Schwelle fuer die Text-Chronik ------------
    # Foundings/Expansionen/Meilensteine liegen darueber; kleine Hungersnoete
    # (geringe Verluste) fallen heraus — die Schwelle filtert echtes Rauschen.
    chronicle_min_importance: float = 2.0


# Ein einziger, geteilter Default. Driver verwendet ihn, wenn nichts uebergeben
# wird.
DEFAULT_CONFIG = Config()
