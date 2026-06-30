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
