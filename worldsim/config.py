"""config — zentrale Stellschrauben (Magic Numbers) der Simulation.

Alle Tuning-Parameter leben hier in einer einzigen ``Config``-dataclass mit
Defaults. Keine versteckten Konstanten in Systemen. ``config_version`` ist Teil
der Reproduzierbarkeits-Identitaet ``(seed, years, config_version)``.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DEFAULT_CONFIG", "DEFAULT_MAP_CONFIG", "Config", "MapConfig"]


@dataclass(frozen=True)
class Config:
    """Unveraenderliche Sammlung aller Stellschrauben.

    ``frozen``, damit ein Lauf nicht versehentlich seine eigene Konfiguration
    mutiert — die Config ist Teil der Lauf-Identitaet.
    """

    # Reproduzierbarkeits-Identitaet: bei jeder semantischen Aenderung der
    # Defaults erhoehen.
    config_version: int = 13

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
    # Gold (Schatz). Gold entsteht ueberall; Eisen nur in Regionen mit Vorkommen
    # (siehe ``Region.iron_rich``), daher hier je *eisenreicher* Region.
    # Die Gold-Foerderung ist mit Aenderung 6 angehoben, weil der Schatz seither
    # einen echten Abfluss hat (Sold + Nothilfe): ohne die Anhebung erstickte die
    # Expansion an ihrem Goldpreis.
    iron_per_region: float = 2.0
    gold_per_region: float = 4.0
    # Aenderung 5: Anteil der Regionen mit Eisenvorkommen (Eisen ist nicht ueberall
    # — die Quelle der Handelsabhaengigkeit). Der Foerdersatz oben ist erhoeht, damit
    # die Welt-Eisenmenge grob erhalten bleibt (nur die Verteilung wird ungleich).
    iron_region_fraction: float = 0.5
    # Aenderung 7: die jaehrliche Ernteschwankung ist FORT. Sie war ein Wuerfelwurf im
    # Ereignispfad — und zwar der folgenreichste: er erzeugte die Hungersnot und damit
    # den Volksdruck, also die halbe Spannungsmechanik. Der Hunger ist jetzt
    # malthusianisch: die Bevoelkerung waechst an die Tragfaehigkeit des Landes heran und
    # sitzt dort auf der Kante. Faellt das Land weg (Krieg, Abspaltung, Beben-Narbe),
    # bleiben die Muender — und das Reich hungert, bis es sich zurueckgehungert hat.
    # Gemessen: 96% aller Nahrungsdefizite kommen so zustande.

    # --- consumption: Bevoelkerung isst Getreide, der Staat zahlt Gold ------
    food_per_person: float = 0.04
    # Bezug der Hungers-Not (siehe systems._hunger): fehlt dieser Bruchteil des
    # Jahresbedarfs, gilt die Not als total (Signal auf 1.0 gesaettigt).
    famine_reference: float = 0.20
    # Getreide ist schlecht lagerbar: Vorrat ist auf diesen Bruchteil einer
    # Jahreskapazitaet begrenzt, damit schlechte Ernten Hunger ausloesen.
    food_storage_factor: float = 0.35
    # Aenderung 6: Gold ist jetzt ein echter Bestand MIT Abfluss. Vorher wuchs der
    # Schatz nur (ausser bei Erdbeben/Handel) — ein gold-basierter Druck waere tot
    # geboren gewesen. Der Staat zahlt jaehrlich seine Pflichten (siehe
    # ``systems._staatspflichten``): Sold je Soldat, Hof je Elite-Kopf, Nothilfe je
    # Einheit Getreidedefizit. Was er nicht zahlen kann, IST der Fiskaldruck.
    # Der Hof ist das entscheidende Glied: er waechst mit der Elite (Kriegsgewinner!),
    # die Foerderung nur mit dem Territorium — so holt die Rechnung die Kasse ein.
    gold_upkeep_per_soldier: float = 0.05
    elite_gold_claim: float = 0.045
    famine_relief_cost: float = 2.0
    # Ueber so viele Jahre ist der Staat bereit, seinen Schatz fuer die laufenden
    # Pflichten anzugreifen. Er bestimmt, wie viel Puffer eine gefuellte Kasse gegen
    # den Fiskaldruck bietet (ein Erdbeben, das den Schatz frisst, nimmt ihn weg).
    fiscal_buffer_years: float = 60.0

    # --- Demografie: logistisches Wachstum je Schicht ----------------------
    growth_rate: float = 0.08
    # Tote pro Einheit Nahrungsdefizit bei Hungersnot (verteilt auf alle Schichten).
    famine_deaths_per_deficit: float = 8.0
    # Aufsteigende Schwellen fuer Bevoelkerungs-Meilensteine.
    population_milestones: tuple[int, ...] = (300, 600, 1200, 2400, 5000)
    # Landnot (siehe systems._land_pressure): erst ab diesem Auslastungsgrad der
    # Tragfaehigkeit wird die Enge als Ressourcendruck spuerbar.
    land_pressure_onset: float = 0.70
    # Rekrutierung Arbeiter -> Soldat: angestrebter Soldaten-Anteil und der Bruchteil
    # der Luecke, der pro Jahr geschlossen wird (homoeostatisch, ohne Zufall). Krieg
    # zehrt Soldaten, die Nachrekrutierung zieht Arbeiter aus der Getreideproduktion.
    target_soldier_fraction: float = 0.10
    recruit_rate: float = 0.10
    # Wer das Ziel UEBERLEBEN verfolgt, schickt Soldaten zurueck aufs Feld: der
    # angestrebte Soldaten-Anteil sinkt auf diesen Bruchteil (guns versus butter).
    retrench_soldier_fraction: float = 0.5

    # --- Groll (grievance): baut sich auf, entlaedt sich noch nicht --------
    # Aufbau bei Getreidemangel (unter den unteren Schichten) und bei ungleichem
    # Wohlstandsanteil (haelt eine Schicht weniger als ihren Bevoelkerungsanteil).
    #
    # Die Hunger-Rate ist mit Aenderung 7 von 0.20 auf 2.0 gestiegen, und zwar NICHT,
    # weil der Hunger wichtiger geworden waere, sondern weil sein SIGNAL eine andere
    # Gestalt hat. Der alte Ernte-Wuerfel erzeugte akute, tiefe Einbrueche (ein Jahr,
    # bis zu -30% Ernte). Der malthusianische Hunger ist das Gegenteil: chronisch und
    # flach (gemessen: das Defizit betraegt im Hungerjahr im Median 1.8% des Bedarfs,
    # weil die Bevoelkerung sich an die Tragfaehigkeit zurueckhungert). Bei der alten
    # Rate trug er praktisch nichts mehr bei — schaltete man die Ungleichheit ab, gab
    # es NULL Aufstaende: die erste Schleife des Konzepts (§4, Mangel ⇒ Groll ⇒
    # Aufstand) war tot, und der Regler eine Attrappe. Bei 2.0 traegt ein DAUERHAFTES
    # Defizit den Groll auf ~2.0 (Ungleichheit traegt ihn auf ~1.5) — und damit steht
    # die richtige Ordnung wieder: Hunger toetet, Ungleichheit aergert nur.
    grievance_hunger_rate: float = 2.0
    grievance_inequality_rate: float = 0.30
    # Langsamer Zerfall Richtung 0, wenn kein Druck wirkt (Vergessen/Beschwichtigung).
    grievance_decay: float = 0.05
    # Obergrenze gegen Ausreisser (Kopfraum ueber dem Ungleichheits-Baseline, damit
    # der Mangel-Beitrag sich klar abhebt).
    grievance_cap: float = 8.0

    # --- goals: utility-basierte Zielwahl (Aenderung 4) --------------------
    # Kein Ziel hat mehr eine eigene Schwelle: die Ziele KONKURRIEREN. UEBERLEBEN
    # traegt als "abwarten"-Option den Grundnutzen (Beharrung) — jede Handlung
    # muss ihn schlagen. Damit ersetzt das Utility-argmax die alten reaktiven
    # Trait-Schwellen (``expand_threshold``/``war_threshold`` sind entfallen).
    goal_status_quo: float = 1.0
    # Situative Gewichte des Ueberlebens-Ziels. Alle situativen Groessen der
    # Zielbewertung sind auf 0..1 normiert, damit die Gewichte vergleichbar sind.
    # Der Hunger wiegt hier BEWUSST leichter als in RESSOURCE_SICHERN: dieselbe
    # Not treibt beide Ziele, die Differenz laesst sie zum Krieg kippen, sobald ein
    # schwacher, fruchtbarer Nachbar erreichbar ist.
    goal_hunger_weight: float = 0.6
    goal_unrest_weight: float = 0.8
    goal_fear_weight: float = 0.5
    goal_caution_weight: float = 0.6
    # RESSOURCE_SICHERN: eigener Mangel treibt, die erreichbare Beute lockt. Nur
    # waehlbar, wenn wirklich etwas fehlt (Land, Getreide oder Bewaffnung).
    # Der Haupttreiber ist die Landnot (siehe ``land_pressure_onset``), nicht die
    # Hungersnot: eine verhungernde Nation ist zum Erobern zu schwach.
    goal_seize_weight: float = 2.8
    goal_famine_weight: float = 0.8
    goal_iron_weight: float = 0.8
    goal_prize_weight: float = 0.4
    # Deckel auf die Fruchtbarkeit des erreichbaren Feldes (relativ zum eigenen Land).
    goal_prize_cap: float = 2.0
    # VERBUENDEN: die jaehrliche Werbung ist ein Gefallen an beide Kanten. Sie hat
    # die automatische Koalitions-Pumpe abgeloest — Buendnisse werden GEWAEHLT und
    # muessen gepflegt werden. ``goal_loyalty_weight`` bindet die Werbung an den
    # bisherigen Partner, traegt allein aber kein Buendnis (sonst waeren Pakte ewig).
    goal_coalition_weight: float = 1.4
    goal_courtship_favor: float = 0.10
    goal_loyalty_weight: float = 0.2

    # --- Aenderung 5: Handel und Abhaengigkeit -----------------------------
    # Benachbarte Nationen mit Ueberschuss/Defizit tauschen Getreide/Eisen/Gold
    # entlang der Beziehungskanten. Die Fluesse sind reine Umverteilung je
    # Ressource (Erhaltung: keine Erzeugung aus dem Nichts) — der Reichtum
    # entsteht aus dem Netz und der daraus wachsenden Abhaengigkeit, nicht aus
    # einem modellierten Preis (Ockham: kein Wirtschafts-Solver).
    # Anteil des passenden Ueberschuss/Defizit-Minimums, der je Jahr fliesst.
    trade_rate: float = 0.25
    # Reichweite in Grenz-Spruengen: 1 = nur direkte Nachbarn, 2 = ein Land
    # dazwischen (Gueter transitieren). Bindet Handel an die Adjazenz, nicht an
    # die (nur kosmetischen) Koordinaten.
    trade_max_distance: int = 2
    # Volumen-Daempfung je zusaetzlichem Sprung (Distanz 1 voll, 2 -> x decay).
    trade_distance_decay: float = 0.5
    # favor skaliert das Volumen (Handel bevorzugt bei positivem favor):
    # scale = clamp01(base + bias*favor). Offene Feinde (hostile) handeln nicht.
    # Die Praeferenz ist bewusst mild: auch neutrale und leicht verstimmte
    # Nachbarn handeln, sonst baute sich Abhaengigkeit nur zu Freunden auf (die
    # spaeter Verbuendete werden und nie angegriffen) — der gefaehrliche Fall ist
    # gerade die Abhaengigkeit von einem Rivalen (Konzept §4: "von Rivale").
    trade_favor_base: float = 0.6
    trade_favor_bias: float = 0.5
    # Fluesse unter dieser Schranke werden ignoriert (kein Rauschen).
    trade_min_flow: float = 1e-6
    # Gold ist Schatz, nicht bloss Ware: diese Reserve bleibt vom Handel
    # unberuehrt, damit der Expansions-Kriegskasten erhalten bleibt
    # (Handels-Bedarf an Gold = Sold der Soldaten + Reserve).
    trade_gold_reserve: float = 15.0
    # dependency (Anteil des von B gedeckten Bedarfs) steigt auf die aktuelle
    # Angewiesenheit und zerfaellt, sobald die Lieferung ausbleibt — so ueberlebt
    # eine gewachsene Abhaengigkeit das Kappen der Lieferung um einige Jahre: das
    # Fenster, in dem "Krieg aus Handelsabhaengigkeit" entsteht.
    dependency_decay: float = 0.10
    # Winzige dependency schnappt auf 0 (die sparse Matrix kann die Kante droppen).
    dependency_epsilon: float = 0.02
    # Utility (Aenderung 4): hohe Abhaengigkeit von einem feindlichen/instabilen
    # Lieferanten hebt das Ziel RESSOURCE_SICHERN (benannter Faktor
    # Handelsabhaengigkeit) — so wird der Handelskrieg emergent statt geskriptet.
    # Gewichtet so, dass eine ausgepraegte Abhaengigkeit (dep ~0.7) von einem
    # riskanten Lieferanten (risk ~0.4) die Wahl kippen kann, eine beilaeufige aber
    # nur mittraegt.
    goal_dependency_weight: float = 4.0

    # --- Aenderung 6: der Spannungszustand und seine Entladung --------------
    # Die Spannung einer Nation ist eine Summe von VIER benannten Druecken (je auf
    # 0..1 normiert, dann gewichtet) — die Faktorliste IST die Begruendung. Ihre
    # Gewichte legen fest, welcher Druck eine Nation eher zerreisst; ihre groesste
    # Komponente waehlt die Art der Entladung.
    # Was eine Elite traegt: Aemter (das Land) UND Pfruenden (die Mittel der Krone).
    # Es bindet die knappere Schranke (Liebigsches Minimum, wie in ``production``) —
    # die Elite braucht Rang UND Auskommen. Aemter je Region binden, wenn eine Nation
    # Land VERLIERT (die Elite bleibt, die Posten gehen ⇒ die geschlagene oder
    # gespaltene Nation bekommt prompt ihre Elitenkrise); die Pfruenden binden, wenn
    # der Adel schneller waechst als die Mittel — der Kriegsgewinner-Adel von §3.3.
    # Der Preis eines Kopfes ist ``elite_gold_claim`` (oben): dieselbe Zahl, die den
    # Hof in den Staatspflichten kostet — der Anspruch des Adels ist EINE Groesse,
    # nicht zwei.
    elite_posts_per_region: float = 75.0
    # Die Gewichte sind an den GEMESSENEN Spitzen der vier Rohdruecke geeicht (sie
    # haben sehr verschiedene natuerliche Spannweiten: der Elitendruck reicht bis 1.0,
    # der Aussendruck kaum ueber 0.5). Erst dadurch kann JEDER Druck die Dominanz
    # gewinnen — sonst entlueden sich alle Krisen als derselbe Typ.
    tension_volk_weight: float = 6.0  # Verelendung: Groll der unteren Schichten
    tension_elite_weight: float = 3.6  # Eliten-Ueberproduktion
    tension_fiskal_weight: float = 4.0  # Staatsfinanzen
    tension_aussen_weight: float = 4.6  # Abhaengigkeit + Einkreisung
    # Innerhalb des Aussendrucks: riskante Handels-Abhaengigkeit gegen Einkreisung
    # (Anteil der Nachbarn in offener Feindschaft). Die Anteile summieren zu 1.
    tension_dependency_share: float = 0.6
    tension_grudge_share: float = 0.4
    # Ab dieser Faktorsumme entlaedt sich die Spannung. Bewusst deutlich ueber dem
    # ruhigen Grundpegel (~1.5), damit Druck sich erst ueber Jahrzehnte aufbaut:
    # keine sofortige Explosion, aber auch keine flache Linie.
    tension_threshold: float = 2.6
    # Danach ist die Nation refraktaer: eine eben erschuetterte Gesellschaft bricht
    # nicht schon im naechsten Jahr erneut. Diese Sperre ist es, die aus dem Auf und Ab
    # einen ZYKLUS macht — ohne sie flackerte dieselbe Nation im Dreijahrestakt durch
    # Putsche, statt Druck ueber Jahrzehnte aufzubauen und ihn dann zu brechen.
    crisis_cooldown_years: int = 20

    # Kollaps: nur wenn die Spannung EXTREM ist UND mehrere Druecke zugleich
    # tragen (zusammengesetzte Krise) — dann waehlt keine einzelne Komponente mehr,
    # das Reich zerfaellt in Nachfolgestaaten. Ein Druck allein, so hoch er auch
    # steht, fuehrt nur zu seiner eigenen Entladung.
    collapse_threshold: float = 3.6
    collapse_component_floor: float = 0.15  # ab diesem ROHWERT traegt ein Druck mit
    collapse_min_components: int = 3
    collapse_max_successors: int = 2
    # Ein Kollaps darf ein KLEINERES Reich zerreissen als eine gewoehnliche Abspaltung
    # (``secession_min_territory``). Der Unterschied ist grundsaetzlich: eine Abspaltung
    # nimmt einem Reich ein STUECK (es muss also gross genug sein, eines zu verlieren),
    # ein Kollaps LOEST ES AUF — auch ein Zwei-Regionen-Staat kann in zwei zerfallen.
    # Ohne diese eigene Schranke waere der Kollaps unerreichbar: die zusammengesetzte
    # Extremkrise trifft gerade die kleinen, armen Reiche, nie die grossen bequemen.
    collapse_min_territory: int = 2

    # --- Entlastung und Folgewirkung je Entladung ---------------------------
    # Prinzip (Konzept §3.3): jede Entladung ENTLASTET ihren eigenen Druck, saet
    # aber einen anderen. So rotiert das System durch die Krisentypen (saekulare
    # Zyklen), statt in einen Fixpunkt zu laufen.
    #
    # AUFSTAND (Volksdruck): der Groll entlaedt sich und Wohlstand wird umverteilt
    # (das senkt auch die Ungleichheit, die den Groll naehrt) — aber der Schatz wird
    # gepluendert (⇒ Fiskaldruck) und Soldaten/Elite bluten (⇒ schwaches Reich, die
    # Nachbarn sehen die Bloesse).
    revolt_grievance_relief: float = 0.35  # Restanteil des Grolls nach dem Aufstand
    revolt_redistribution: float = 0.18  # Wohlstandsanteil, den die Elite abgibt
    revolt_gold_loss: float = 0.50
    revolt_elite_losses: float = 0.15
    revolt_soldier_losses: float = 0.08
    # PUTSCH (Elitendruck, unteilbares Reich): die siegreiche Faktion purgiert ihre
    # Rivalen (⇒ Elitendruck faellt) und greift nach dem Wohlstand (⇒ Ungleichheit
    # steigt ⇒ Volksdruck waechst). Der gestuerzte Herrscher stirbt; der Usurpator
    # hat schwache Legitimitaet — die Sukzessionskrise kann das Reich spalten
    # (Buergerkrieg), das erledigt die bestehende Fragmentierungs-Mechanik.
    coup_elite_purge: float = 0.25
    coup_wealth_grab: float = 0.04
    # ABSPALTUNG (Elitendruck, teilbares Reich): die ueberzaehlige Elite nimmt sich
    # ihren eigenen Staat. Sie ist unter den Auswanderern UEBERREPRAESENTIERT — genau
    # das entlastet den Elitendruck der Mutter (eine proportionale Teilung wuerde
    # Elite UND Aemter gleich halbieren und den Druck unveraendert lassen).
    secession_elite_bias: float = 1.8
    # BANKROTT (Fiskaldruck): der Staat entlaesst, was er nicht bezahlen kann — auf
    # BEIDEN Seiten der Rechnung. Die Soldaten kehren aufs Feld zurueck; und das
    # Gefolge, dessen Pfruende die Krone nicht mehr aufbringt, faellt aus dem Stand.
    # Das zweite Glied ist das entscheidende: der Hof ist der GROESSTE Posten der
    # Pflichten (rund die Haelfte), der Sold der kleinste (rund ein Zwoelftel) — ein
    # Bankrott, der nur das Heer verkleinert, senkt seine eigene Rechnung um wenige
    # Prozent und waere gar keine Entladung.
    bankruptcy_demobilization: float = 0.35
    bankruptcy_dismissal: float = 0.25  # Anteil des Hofes, der aus dem Stand faellt
    # Bezahlt wird der Rest mit Zwangsabgaben, die den Groll heben (⇒ Volksdruck) —
    # und mit einem entbloessten Heer (⇒ die Nachbarn wittern Beute).
    bankruptcy_levy_grievance: float = 1.2
    # KOLLAPS: das Reich zerfaellt; die alte Ordnung ist fort. Nachfolgestaaten und
    # Rumpfstaat starten mit gebrochener Elite und weitgehend entladenem Groll.
    collapse_grievance_relief: float = 0.25
    collapse_elite_purge: float = 0.35
    # KRIEG als Entladung des Aussendrucks: er ist die einzige Entladung, die nach
    # AUSSEN geht — deshalb hat er keine eigene Art, sondern laeuft ueber die
    # bestehende Zielwahl (Aenderung 4). Steht die Spannung ueber der Schwelle und
    # dominiert der Aussendruck, legt dieser Zuschlag als benannter Faktor
    # ``Aussendruck`` auf beide Kriegsziele — die Nation MUSS nach aussen handeln.
    goal_crisis_weight: float = 1.2
    # Kriegsgewinner-Eliten (Konzept §3.3): ein Sieg hebt Offiziere und Profiteure
    # aus den Arbeitern in die Elite. Der Krieg loest die Knappheit — und saet die
    # Eliten-Ueberproduktion, die als naechste Krise faellig wird. Es ist der einzige
    # Kanal, der den Elite-Anteil HEBT; ohne ihn bliebe er exakt konstant und der
    # Elitendruck eine flache Linie.
    war_elite_promotion: float = 0.015

    # --- expansion: Anspruch auf ein angrenzendes freies Feld --------------
    expand_gold_cost: float = 15.0

    # --- diplomacy: Furcht, favor-Matrix, abgeleitete Buendnisse ------------
    # Jaehrlicher Zerfall des favor Richtung 0 — die Vergebung. "Ueber
    # Jahrzehnte": bei 0.04 betraegt die Halbwertszeit ~17 Jahre.
    favor_decay: float = 0.04
    # Kleine jaehrliche Annaeherung friedlicher Nachbarn. Das Gleichgewicht
    # favor_drift/favor_decay bleibt bewusst unter der Buendnis-Schwelle:
    # Nachbarschaft allein stiftet kein Buendnis.
    favor_drift: float = 0.008
    # Gemeinsame Furcht vor dem Staerksten baut favor auf — Balance of Power als
    # ambiente favor-Quelle. Die *gezielte* Werbung einer Nation (Ziel VERBUENDEN)
    # legt sich darauf: hier waechst der Untergrund, dort waehlt jemand den Partner.
    favor_coop_rate: float = 0.10
    # Der Buendnisschluss selbst ist ein Gefallen: hebt favor ueber die Schwelle
    # hinaus (natuerliche Hysterese gegen jaehrliches Flattern).
    favor_pact_bonus: float = 0.20
    # favor-Einbruch beim Angriff (Verrat); Honor des Opfers skaliert die Reaktion.
    favor_drop_on_attack: float = 0.6
    # Abgeleitete Status-Schwellen (nichts davon wird gespeichert): Buendnis ab
    # beidseitigem favor >= ..., Feindschaft ab einseitigem favor <= ...
    alliance_favor_threshold: float = 0.5
    enmity_favor_threshold: float = -0.25
    # Kanten mit |favor| darunter (und ruhender dependency) entfallen — die
    # Matrix bleibt sparse, eine fehlende Kante ist neutral.
    favor_prune_epsilon: float = 0.005
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

    # --- war: Vollzug der Kriegsziele --------------------------------------
    # Kriegsmuedigkeit: so viele Jahre kein neuer Krieg gegen dasselbe Ziel ...
    # (seit Aenderung 3 laenger: Wohlwollen ZERFAELLT jetzt statt dauerhaft zu
    # saettigen, also fehlt der alte permanente Vertrauens-Daempfer — die
    # Kriegsfrequenz wird ueber die Muedigkeit neu geeicht).
    war_cooldown_years: int = 12
    # ... und ueberhaupt kein neuer Krieg (gegen irgendwen) so lange nach einem.
    war_global_cooldown_years: int = 6
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
    # Offene Feindschaft (abgeleitet aus Groll) laesst Reibung schneller wachsen.
    hostility_friction_bonus: float = 1.0
    # Obergrenze der akkumulierten Reibung (sonst eskaliert sie unbegrenzt).
    friction_cap: float = 4.0
    # Schwelle, ab der akkumulierte Reibung ein GRENZREIBUNG-Event ausloest.
    friction_event_step: float = 1.0
    # Wie viele Jahre zurueck Krieg ausloesende Reibungs-/Buendnis-Events zitiert.
    cause_window_years: int = 12
    # Bevoelkerungsverlust des Verlierers/Gewinners als Anteil bei einer Schlacht.
    war_loser_losses: float = 0.12
    war_winner_losses: float = 0.04
    # Ausruestungsverlust (Eisen) einer Schlacht: der EINZIGE Abfluss des
    # Eisenbestands. Ohne ihn saettigt die Bewaffnung dauerhaft und der Bestand
    # (samt Eisenbedarf-Faktor) waere behavioral tot. Der Sieger schont sein Eisen.
    war_iron_loss: float = 0.35
    war_winner_iron_share: float = 0.5
    # Zufalls-Jitter im Machtvergleich der Schlacht (benannter Faktor "Zufall").
    battle_jitter: float = 0.15
    # Ein Krieg LOEST Spannung; danach bleibt nur dieser Groll-Restbetrag (Reibung
    # wird auf diesen Wert zurueckgesetzt, baut sich dann ueber Jahre neu auf).
    grudge_floor: float = 1.0

    # --- ruler: Herrscher als duenne Trait-Ueberlagerung -------------------
    # Lebensspanne (Jahre) und Alter beim Machtantritt. Beide werden bei der GEBURT des
    # Herrschers gezogen — das ist seine Konstitution, eine Anfangsbedingung, kein
    # Ausloeser (Aenderung 7). Er stirbt dann NICHT mehr per jaehrlichem Hazard-Wurf,
    # sondern wenn sein Alter die Spanne erreicht: der Tod ist ab der ersten Stunde
    # terminiert, und das TOD_FIGUR-Event nennt als Faktor genau das (Alter/Spanne = 1).
    # Die Spannen sind gegenueber dem Hazard-Modell gesenkt, damit die mittlere
    # Regierungszeit gleich bleibt (der Hazard toetete im Mittel vor der Spanne).
    ruler_lifespan_min: int = 38
    ruler_lifespan_max: int = 62
    ruler_accession_age_min: int = 18
    ruler_accession_age_max: int = 40
    # Maximaler Betrag eines Herrscher-Trait-Deltas (+/-) auf die Basis-Traits.
    ruler_trait_delta: float = 0.30
    # Aenderung 7: der Machtantritt wird nicht mehr gewuerfelt (``heir_uncertainty`` ist
    # fort — ein Wurf entschied dort, ob ein Reich einen Usurpator bekommt und daran
    # zerbricht). Er folgt jetzt dem ELITENDRUCK der Nation: ein Adel, der mehr Anwaerter
    # hat als Aemter, streitet um den Thron. Unter der ersten Schwelle erbt die Dynastie;
    # darueber muss die Elite den Nachfolger aushandeln (Wahl); ueber der zweiten nimmt
    # sich eine Faktion die Macht (Usurpation). Damit ist die Sukzessionskrise — und die
    # Fragmentierung, die aus ihr folgt — endogen: sie hat eine Ursache in der Welt.
    accession_contested_threshold: float = 1.2  # Elitendruck (gewichtet) ⇒ Wahl
    accession_usurped_threshold: float = 2.2  # ⇒ Usurpation
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
    # Anfangs-Groll (negative favor-Kanten) zwischen Abspaltung und Mutterland.
    secession_distrust: float = 0.30

    # --- persoenliche Rivalitaet (schlank) ---------------------------------
    # Ab dieser effektiven Aggression beider Herrscher gilt ein Krieg als persoenlich.
    personal_aggression_threshold: float = 0.60
    personal_rivalry_weight: float = 0.30
    # Aenderung 7: hier stand eine Wahrscheinlichkeit (0.40, ein Wurf je persoenlichem
    # Krieg) — und sie entschied ueber Herrschertod ⇒ Sukzession ⇒ Abspaltung, also ueber
    # den Zerfall von Reichen. Jetzt entscheidet die Wucht der Niederlage: ab diesem
    # Militaervorteil des Siegers (dem Faktor, der ohnehin in der Schlacht-Begruendung
    # steht) bleibt der Verlierer-Herrscher auf dem Feld. Gemessen trifft das 36% der
    # Schlachten persoenlicher Kriege — praktisch die alte Rate, nur eben verdient.
    personal_death_margin: float = 0.20

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
    # Das Schisma ist ein Groll-Stoss auf die favor-Kanten zu den ehemaligen
    # Glaubensbruedern; ob ein Buendnis daran zerbricht, entscheidet der favor-Stand.
    schism_favor_drop: float = 0.5

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

    # --- tectonics: der EINE verbliebene exogene Schock (Aenderung 7) ----------
    # Pest und Duerre sind fort: sie waren reine Wuerfelwuerfe im Ereignispfad und
    # taten nichts, was die Welt nicht aus sich selbst tut (Bevoelkerung sterben lassen,
    # Vorraete vernichten). Das Erdbeben bleibt als einziger — weil es als einziges
    # KEINE soziale Ursache haben kann. Aber auch es wird nicht mehr gewuerfelt:
    # Gesteinsspannung baut sich Jahr um Jahr auf und entlaedt sich an einer Schwelle
    # (elastischer Rueckprall — dieselbe Figur wie die politische Spannung). Gezogen
    # wird allein die GEOLOGIE, und zwar im Worldgen: welche Felder auf einer Verwerfung
    # liegen und wie schnell sich dort Spannung staut. Der Ereignispfad wuerfelt nicht.
    seismic_region_fraction: float = 0.35  # Anteil der Felder auf einer Verwerfung
    # Spannungszuwachs je Jahr = seismicity (0..1) * dieser Satz. Ein voll seismisches
    # Feld bebt damit alle ~250 Jahre, ein schwach seismisches nie in einem Menschen-
    # alter — die "sehr niedrige Rate", die das Konzept verlangt.
    seismic_strain_rate: float = 0.004
    # Folgen des Bebens: Wohlstand, etwas Bevoelkerung, und eine DAUERHAFTE Narbe in der
    # Nahrungskapazitaet des Feldes. Die Narbe ist der Hebel, ueber den das Beben in das
    # Spannungssystem laeuft: zerstoerte Terrassen und Kanaele tragen weniger Muender
    # ⇒ Hunger ⇒ Volksdruck. Es loest kein fertiges Gross-Ereignis aus, es SETZT Druck —
    # was daraus wird (Aufstand, Bankrott, gar nichts), entscheidet die Lage der Nation.
    #
    # Die Narbe ist mit Aenderung 7 von 0.15 auf 0.45 gestiegen. Gemessen: bei 0.15 war
    # der Volksdruck der getroffenen Nation 15 Jahre spaeter unveraendert (0.90 -> 0.90)
    # — das Beben interagierte mit NICHTS und haette nach Ockham ersatzlos gestrichen
    # gehoert. Ein Beben, das alle paar Jahrhunderte einmal ein Feld trifft, darf dieses
    # Feld auch wirklich verwuesten: selten und schwer ist die richtige Gestalt (das
    # Konzept will "selten eine Lawine", §3.3), nicht haeufig und folgenlos.
    quake_wealth_loss: float = 0.60
    quake_pop_loss: float = 0.05
    quake_capacity_scar: float = 0.45

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


@dataclass(frozen=True)
class MapConfig:
    """Stellschrauben der Karten-Geologie (Praesentation).

    **Bewusst getrennt von** :class:`Config`: die Karte ist eine Ansicht, kein Teil
    der Simulation. Sie aendert nie, WELCHE Fakten entstehen, gehoert also nicht in
    die Lauf-Identitaet ``(seed, years, config_version)`` — wer hier dreht, bekommt
    eine andere Karte, aber dieselbe Geschichte.
    """

    # --- Tektonik: die grosse Struktur -------------------------------------
    # Handvoll Platten (Voronoi-Zellen um gestreute Keimpunkte). Keine echte
    # Plattensimulation, keine Drift ueber Zeit: EIN Standbild von Bewegungs-
    # richtungen, aus dem die Hoehenstruktur folgt.
    plate_count: int = 7
    # Anteil ozeanischer Platten. Sie sind dichter und tauchen daher unter
    # kontinentale ab — daraus entstehen Subduktion, Tiefseegraben, Inselbogen.
    # Mindestens eine Platte je Art ist garantiert (sonst gibt es keine Subduktion).
    oceanic_plate_fraction: float = 0.55
    # Amplitude der tektonischen Hoehenformung (Kollision, Kordillere, Graben, Rift).
    # Der eine Regler fuer "wie dramatisch ist diese Welt". Deutlich groesser als
    # ``noise_strength`` — und das ist der Punkt: die Tektonik traegt die Struktur, das
    # Rauschen nur die Rauheit. Umgekehrt (gemessen) ertrinken die Ketten im Rauschen.
    mountain_strength: float = 1.10
    # Breite des tektonisch geformten Saums beidseits einer Plattengrenze (in
    # Einheiten des Einheitsquadrats). Bestimmt, wie breit eine Gebirgskette wird.
    boundary_width: float = 0.13

    # --- Rauschen: die Detailrauheit ---------------------------------------
    # fBm ueber der Tektonik: mehrere Oktaven, jede halb so stark und doppelt so
    # fein. UEBERLAGERT die Tektonik, ersetzt sie nicht.
    noise_octaves: int = 5
    noise_strength: float = 0.22

    # --- Meeresspiegel ------------------------------------------------------
    # Als Ziel-Landanteil ausgedrueckt: die Schwelle wird je Welt als Quantil der
    # Hoehenverteilung gezogen. Ein fester Hoehenwert waere seed-abhaengig mal eine
    # Wasserwelt, mal ein Trockenplanet; so traegt jeder Seed grob dieselbe Kueste.
    land_fraction: float = 0.30

    # --- Klima: Temperatur --------------------------------------------------
    # Abnahme je Hoeheneinheit ueber der TYPISCHEN LANDHOEHE dieser Welt (nicht ueber dem
    # Meeresspiegel — der schwimmt, siehe ``climate._land_reference``). Sie traegt eine
    # Doppellast: gross genug, dass hohe Gipfel auch am AEQUATOR unter die Schneegrenze
    # fallen (deshalb braucht es keine eigene "Schnee-Hoehenzone" — der Gradient erzeugt
    # sie, breitenunabhaengig), aber nicht so gross, dass jede Kette vereist. Gemessen:
    # bei 0.70 trug kein einziger Tropengipfel Schnee, bei 1.15 frass das Eis den Fels.
    altitude_lapse: float = 1.00
    temp_noise: float = 0.05

    # --- Klima: Feuchtigkeit ------------------------------------------------
    # Reichweite (in Zellen), ueber die eine Luftmasse landeinwaerts austrocknet —
    # die Kontinentalitaet.
    moisture_range: float = 18.0
    # Regenschatten-Staerke: welcher Anteil der Restfeuchte je Zelle voller Steigung
    # abregnet. Hoch ⇒ scharfer Schatten hinter dem Kamm. (Bei 0.75 blieb hinter dem
    # ersten Kamm nichts mehr uebrig und der ganze Kontinent wurde Wueste.)
    rain_shadow_strength: float = 0.55
    # Steigung (Hoehe je Zelle), ab der eine Luftmasse voll orografisch abregnet.
    orographic_scale: float = 0.28
    # Rossbreiten (~27°): absinkende Luft ⇒ Trockenheit. Das ist der zweite Grund,
    # warum eine Wueste dort liegt, wo sie liegt (der erste ist der Regenschatten).
    horse_latitude_dryness: float = 0.55

    # --- Klimabaender: Schwellen (Temperatur und Feuchte je 0..1) -----------
    snow_temp: float = 0.08       # darunter: Gletscher/Eis (Pole UND hohe Gipfel)
    alpine_temp: float = 0.38     # darunter und hoch gelegen: alpiner Fels
    boreal_temp: float = 0.40     # darunter: Tundra/Taiga
    temperate_temp: float = 0.64  # darunter: gemaessigt; darueber: tropisch
    alpine_altitude: float = 0.45  # ab dieser Hoehe ueber dem Meer gilt "hochgelegen"
    arid_moisture: float = 0.22   # darunter: Wueste
    dry_moisture: float = 0.40    # darunter: Steppe (bzw. Tundra statt Taiga)
    humid_moisture: float = 0.55  # darueber: geschlossener Wald / Regenwald


DEFAULT_MAP_CONFIG = MapConfig()
