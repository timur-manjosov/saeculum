"""Aenderung 7: der Kausalgraph ist lueckenlos — kein Ereignis kommt mehr aus dem Wuerfel.

Vorher hatte der Graph an genau einer Stelle ein "weil der Wuerfel es sagte": die externen
Trigger (Pest, Duerre, Erdbeben, der Sterbe-Hazard des Herrschers, der Erbfolge-Wurf, die
Ernteschwankung). Diese Datei sichert den Vertrag, der an ihre Stelle tritt:

    Der Zufall entscheidet nie, OB etwas geschieht.

Er hat nur noch zwei Rollen (Konzept §0):

* **Anfangsbedingungen** — die Welt (Geografie, Kapazitaeten, Eisen, Verwerfungen, Traits)
  und die Konstitution einer neu GEBORENEN Entitaet (ein Herrscher kommt mit Charakter und
  Lebensspanne zur Welt; wann er stirbt, steht damit von der ersten Stunde an fest).
* **benannter Jitter**, der einen Gleichstand bricht — der ``Zufall``-Faktor der Schlacht,
  der in ihrer Begruendung STEHT und sich damit selbst anzeigt.

Der Beweis dafuer ist ``test_a_quiet_year_draws_no_randomness_at_all``: in einem Jahr ohne
Geburt und ohne Schlacht bleibt der Zufallsstrom unberuehrt. Ein Ereignis kann dann nicht
mehr aus ihm stammen — es muss aus dem Zustand der Welt kommen.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from random import Random

from worldsim.config import DEFAULT_CONFIG, Config
from worldsim.driver import SYSTEMS, simulate, worldgen
from worldsim.events import EventKind, EventLog, FactorLabel
from worldsim.rng import Rng

# Ereignisse, bei denen eine neue Entitaet GEBOREN wird (ein Herrscher wird geschmiedet)
# — und damit die einzigen, in denen ein Zufall Anfangsbedingungen ziehen darf.
_BIRTHS = (
    EventKind.SUKZESSION,  # neuer Herrscher
    EventKind.ABSPALTUNG,  # neue Nation + ihr Herrscher
    EventKind.KOLLAPS,  # Nachfolgestaaten + ihre Herrscher
)
# Die Schlacht ist der einzige Ort, an dem ein Wuerfel eine ENTSCHEIDUNG mitbestimmt —
# und er tut es als benannter Faktor, der in der Begruendung steht.
_JITTER = EventKind.SCHLACHT


class _CountingStream(Random):
    """Ein Zufallsstrom, der mitzaehlt, wie oft aus ihm gezogen wurde."""

    def __init__(self, seed: int, tally: Counter[str], key: str) -> None:
        super().__init__(seed)
        self._tally = tally
        self._key = key

    def random(self) -> float:
        self._tally[self._key] += 1
        return super().random()

    def getrandbits(self, k: int) -> int:
        # randint/randrange/choice/shuffle/sample laufen ALLE hierueber.
        self._tally[self._key] += 1
        return super().getrandbits(k)


def _run_counting(seed: int, years: int, cfg: Config = DEFAULT_CONFIG):
    """Fahre den echten Tick-Loop und zaehle je Jahr, wie oft gewuerfelt wurde."""
    master = Rng(seed)
    log = EventLog()
    world = worldgen(master, cfg)
    per_year: dict[int, int] = {}
    per_system: Counter[str] = Counter()
    for year in range(years):
        world = replace(world, year=year)
        tally: Counter[str] = Counter()
        for sid, system in SYSTEMS:
            stream = _CountingStream(master.stream(f"{sid}:{year}").getrandbits(64), tally, sid)
            world = system(world, stream, cfg, log)
        per_year[year] = sum(tally.values())
        per_system.update(tally)
    return world, log, per_year, per_system


def test_a_quiet_year_draws_no_randomness_at_all() -> None:
    """DER Nachweis (Aufgabe 3): ohne Geburt und ohne Schlacht bleibt der Wuerfel liegen.

    Wenn in einem Jahr, in dem etwas geschieht — Hungersnoete, Aufstaende, Putsche,
    Bankrotte, Beben, Konversionen, Buendnisse —, kein einziges Mal gewuerfelt wird, dann
    kann keines dieser Ereignisse aus dem Wuerfel stammen. Sie kommen aus dem Zustand der
    Welt. Genau das ist die Zusage von Aenderung 7, und sie ist hier nicht behauptet,
    sondern gezaehlt.
    """
    _, log, per_year, _ = _run_counting(seed=42, years=250)

    by_year: dict[int, set[EventKind]] = {}
    for e in log:
        by_year.setdefault(e.year, set()).add(e.kind)

    quiet_but_busy = 0
    for year, draws in per_year.items():
        kinds = by_year.get(year, set())
        if any(k in kinds for k in _BIRTHS) or _JITTER in kinds:
            continue  # eine Geburt oder eine Schlacht darf ziehen
        assert draws == 0, f"Jahr {year} wuerfelte {draws}x ohne Geburt und ohne Schlacht"
        if kinds:
            quiet_but_busy += 1

    # Und diese Jahre sind nicht etwa leer: in ihnen geschieht Geschichte — ganz ohne Wuerfel.
    assert quiet_but_busy > 40


def test_the_systems_that_decide_never_roll() -> None:
    """Kein System, das ueber Ereignisse ENTSCHEIDET, zieht ueberhaupt Zufall.

    Die Liste ist der Determinismus-Vertrag in Prosa: Produktion (die Ernte wird nicht
    mehr gewuerfelt), Demografie und Groll (die Hungersnot ist eine Bilanz), Reibung und
    Diplomatie, die Spannung mit ihren Entladungen, die Identitaet (Konversion/Schisma
    waren schon endogen) — und die Tektonik, in der das letzte Erdbeben sitzt. Sie alle
    lesen den Zustand und rechnen; keines von ihnen wuerfelt.
    """
    _, _, _, per_system = _run_counting(seed=7, years=200)
    stumm = (
        "founding",
        "research",
        "production",
        "trade",
        "consumption",
        "demografie",
        "grievance",
        "friction",
        "diplomacy",
        "identity",
        "tectonics",
        "epoch",
    )
    for sid in stumm:
        assert per_system[sid] == 0, f"System '{sid}' zieht noch Zufall"
    # Bleiben genau zwei: der Herrscher-Lauf (Geburt eines Herrschers) und die Zielwahl
    # (Schlacht-Jitter + Geburt bei einer Abspaltung). Die Spannung zieht nur, wenn eine
    # Entladung eine neue Nation gebiert — sonst nie.
    assert per_system["ruler"] > 0
    assert per_system["goals"] > 0


def test_every_event_carries_its_reason() -> None:
    """Kein Ereignis ohne Begruendung: jedes traegt Faktoren ODER Ursachen.

    Das Gegenstueck zum Wuerfel-Verbot. Ein Ereignis, das weder benannte Faktoren noch
    Ursachen traegt, waere ein Ereignis ohne Warum — und genau die gibt es nicht mehr.
    """
    _, log = simulate(seed=42, years=300)
    assert list(log)
    for e in log:
        assert e.factors or e.causes, f"{e.kind} in Jahr {e.year} hat kein Warum"


def test_the_battle_jitter_is_the_only_die_and_it_names_itself() -> None:
    """Der einzige Wuerfel im Entscheidungspfad steht in der Begruendung, die er beeinflusst.

    Er bricht den Gleichstand zweier vergleichbarer Heere — genau die Rolle, die Konzept §0
    dem Zufall noch zugesteht ("kleiner benannter Jitter beim Brechen von Gleichstaenden").
    Weil er als Faktor ``Zufall`` im SCHLACHT-Event steht, luegt der Kausalgraph nicht: er
    zeigt selbst an, wo der Wuerfel mitgesprochen hat.
    """
    _, log = simulate(seed=42, years=250)
    battles = log.by_kind(EventKind.SCHLACHT)
    assert battles
    for e in battles:
        labels = [f.label for f in e.factors]
        assert FactorLabel.ZUFALL.value in labels
        jitter = next(f.weight for f in e.factors if f.label == FactorLabel.ZUFALL.value)
        assert abs(jitter) <= DEFAULT_CONFIG.battle_jitter

    # Und ausserhalb der Schlacht taucht "Zufall" in KEINER Begruendung auf.
    for e in log:
        if e.kind is EventKind.SCHLACHT:
            continue
        assert FactorLabel.ZUFALL.value not in [f.label for f in e.factors]


def test_the_ruler_dies_of_his_own_lifespan_not_of_a_roll() -> None:
    """Der Tod eines Herrschers ist ab seiner ersten Stunde terminiert.

    Der Sterbe-Hazard (ein Wurf pro Jahr) ist fort: die Lebensspanne wird bei der Geburt
    gezogen — eine Anfangsbedingung —, und der Herrscher stirbt, wenn er sie erreicht. Der
    Faktor des Todes-Events sagt genau das: Alter/Spanne = 1.

    Ein Herrscher stirbt auf genau drei Arten, und keine ist ein Wurf:

    * **Alter** — er hat seine Lebensspanne erreicht (hier);
    * **Elitendruck** — ein Putsch stuerzt ihn (Aenderung 6);
    * **Militaervorteil** — er faellt in einer vernichtend verlorenen Schlacht
      (Aenderung 7; hier stand vorher eine 40%-Chance).

    Jede dieser drei Arten traegt ihren Grund als benannten Faktor. Der Test verlangt
    genau das: kein Todes-Event ohne einen dieser drei Gruende.
    """
    world, log = simulate(seed=42, years=300)
    deaths = log.by_kind(EventKind.TOD_FIGUR)
    assert deaths
    gruende = {
        FactorLabel.ALTER.value,
        FactorLabel.ELITENDRUCK.value,
        FactorLabel.MILITAERVORTEIL.value,
    }
    natural = 0
    for e in deaths:
        labels = {f.label for f in e.factors}
        assert labels & gruende, f"Herrschertod ohne Grund in Jahr {e.year}"
        if FactorLabel.ALTER.value not in labels:
            continue  # gestuerzt oder gefallen, nicht gealtert
        ruler = world.rulers[e.subjects[1]]
        alter = next(f.weight for f in e.factors if f.label == FactorLabel.ALTER.value)
        assert alter >= 1.0  # er hat seine Spanne erreicht — auf das Jahr genau
        assert ruler.age >= ruler.lifespan
        natural += 1
    assert natural  # den Alterstod gibt es, und er ist exakt terminiert


def test_determinism_survives_the_removal_of_the_dice() -> None:
    """Gleicher Seed ⇒ identische Welt und identischer Log (der Vertrag bleibt)."""
    wa, la = simulate(seed=123, years=200)
    wb, lb = simulate(seed=123, years=200)
    assert wa == wb
    assert [e.__dict__ for e in la] == [e.__dict__ for e in lb]


def test_the_cosmetic_name_never_touches_the_semantic_stream() -> None:
    """Flavour darf die Fakten nicht verschieben (Determinismus-Vertrag, CLAUDE.md).

    Bis Aenderung 7 zog ``make_name`` aus dem SEMANTISCHEN Strom des Systems: der Name
    eines Herrschers verschob damit alle folgenden Ziehungen. Haette jemand die Silbenliste
    geaendert, waere eine andere Geschichte herausgekommen. Der Beleg, dass das vorbei ist:
    andere Silben, dieselbe Welt.
    """
    import worldsim.names as names

    original = names._ONSETS
    try:
        names._ONSETS = tuple("Zz" + o for o in original)  # rein kosmetische Aenderung
        world_a, log_a = simulate(seed=42, years=150)
    finally:
        names._ONSETS = original
    world_b, log_b = simulate(seed=42, years=150)

    # Die Namen sind andere ...
    assert [p.name for p in world_a.polities.values()] != [
        p.name for p in world_b.polities.values()
    ]
    # ... die Geschichte ist dieselbe: gleiche Ereignisse, gleiche Faktoren, gleiche Ursachen.
    assert [(e.year, e.kind, e.subjects, e.factors, e.causes) for e in log_a] == [
        (e.year, e.kind, e.subjects, e.factors, e.causes) for e in log_b
    ]
