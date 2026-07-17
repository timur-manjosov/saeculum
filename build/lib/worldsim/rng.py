"""rng — deterministische Zufalls-Infrastruktur.

EIN Master-RNG wird aus dem ``seed`` erzeugt. Daraus werden **benannte
Sub-Stroeme** stabil abgeleitet: gleicher Name ⇒ gleicher Strom. Systeme greifen
nie auf einen globalen RNG zu; der Driver reicht den Sub-Strom explizit durch.

Die Ableitung benutzt ``hashlib`` (nicht das eingebaute, prozess-gesalzene
``hash()``), damit Sub-Seeds ueber Laeufe und Maschinen hinweg identisch sind.

Semantischer und kosmetischer Zufall leben in **getrennten Namensraeumen**.
Da jeder Strom eine eigene, unabhaengig geseedete :class:`random.Random`-Instanz
ist, kann der Verbrauch des einen niemals den anderen beeinflussen — kosmetische
Aenderungen koennen die semantische Reproduzierbarkeit also nicht stoeren.

Der Zufalls-Vertrag (Aenderung 7, Konzept §0)
---------------------------------------------

**Der Zufall entscheidet nie, OB etwas geschieht.** Er ist vom *Ausloeser von
Ereignissen* zur *Quelle der Anfangsbedingungen* herabgestuft. Damit hat der
Kausalgraph keine Stelle mehr, an der "weil der Wuerfel es sagte" steht: jedes
Ereignis kommt aus dem Zustand der Welt.

Es bleiben genau drei erlaubte Rollen:

1. **Worldgen** — die Anfangsbedingungen der Welt: Geografie und Adjazenz,
   Nahrungskapazitaeten, Eisenvorkommen, Verwerfungen (``Region.seismicity``),
   Hauptstaedte, Nationstraits. Der ganze Reichtum der Welt kommt aus dem Seed.
2. **Die Konstitution einer neu GEBORENEN Entitaet** — ein Herrscher kommt mit
   Charakter (Trait-Deltas), Lebensspanne und Antrittsalter zur Welt
   (``forge_ruler``). Das ist kein Ausloeser: der Wuerfel sagt nicht, DASS etwas
   geschieht, sondern womit ein neues Subsystem ausgestattet ist — genau wie im
   Worldgen. Wann dieser Herrscher stirbt, steht damit ab seiner ersten Stunde
   fest (kein jaehrlicher Sterbe-Wurf mehr).
3. **Ein benannter Jitter, der Gleichstaende bricht** — der ``Zufall``-Faktor der
   Schlacht. Er ist der EINZIGE Wuerfel im Entscheidungspfad, und er steht als
   Faktor in der Begruendung des Events, das er beeinflusst: der Graph zeigt
   selbst an, wo er mitgesprochen hat.

Was dafuer weichen musste (alles gestrichen oder endogenisiert): das
Katastrophen-System (Pest/Duerre/Erdbeben als Wuerfe), die jaehrliche
Ernteschwankung (sie erzeugte die Hungersnot — und damit den halben
Spannungsapparat), der Sterbe-Hazard des Herrschers, der Erbfolge-Wurf
(``heir_uncertainty``) und die Todes-Chance des geschlagenen Herrschers.

Der Vertrag ist nicht bloss dokumentiert, er ist **gezaehlt**: siehe
``tests/test_kausalitaet.py`` — in einem Jahr ohne Geburt und ohne Schlacht wird
kein einziges Mal gewuerfelt, obwohl in ihm Hungersnoete, Aufstaende, Putsche,
Bankrotte und Beben geschehen.
"""

from __future__ import annotations

import hashlib
from random import Random

__all__ = ["Rng", "Stream", "derive_sub_seed"]

# Typ-Alias: ein Sub-Strom ist eine geseedete Standard-RNG-Instanz.
Stream = Random

_SEMANTIC_NS = "semantic"
_COSMETIC_NS = "cosmetic"


def derive_sub_seed(master_seed: int, namespace: str, name: str) -> int:
    """Leite deterministisch ein 64-Bit-Sub-Seed ab.

    Stabil ueber Prozesse/Plattformen, weil SHA-256 statt des gesalzenen
    eingebauten ``hash()`` verwendet wird.
    """
    key = f"{namespace}|{master_seed}|{name}".encode()
    digest = hashlib.sha256(key).digest()
    return int.from_bytes(digest[:8], "big")


class Rng:
    """Master-RNG. Faechert in benannte, deterministische Sub-Stroeme auf."""

    __slots__ = ("_seed",)

    def __init__(self, seed: int) -> None:
        self._seed = seed

    @property
    def seed(self) -> int:
        return self._seed

    def stream(self, name: str) -> Stream:
        """Semantischer Sub-Strom (Entscheidungspfad).

        Beispiel-Namen: ``"worldgen"``, ``"subsistenz:0"`` (Schema
        ``f"{system_id}:{year}"``). Gleicher Name ⇒ identische Sequenz.
        """
        return Random(derive_sub_seed(self._seed, _SEMANTIC_NS, name))

    def cosmetic_stream(self, name: str) -> Stream:
        """Kosmetischer Sub-Strom (Namensgebung, Flavour).

        Getrennter Namensraum vom semantischen Pfad; beeinflusst nie, *welche*
        Fakten entstehen.
        """
        return Random(derive_sub_seed(self._seed, _COSMETIC_NS, name))
