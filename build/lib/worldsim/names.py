"""names — ein einfacher, deterministischer, silbenbasierter Namensgenerator.

Geteilt von Nationen und Herrschern (Aufgabe 3). Ein Name verbraucht eine
**feste** Zahl von Ziehungen (drei ``choice``-Aufrufe), unabhaengig vom Inhalt
der Silbenlisten — so verschiebt das Editieren der Listen den speisenden Strom
nicht und die Reproduzierbarkeit bleibt erhalten.

Nationen ziehen ihren Namen aus einem **kosmetischen** Strom (reines Flavour).
Herrscher sind semantische Entitaeten (ihre Trait-Deltas steuern Verhalten);
ihr Name wird daher beim Erschaffen aus demselben **semantischen** Strom gezogen
wie ihre uebrigen Eigenschaften.
"""

from __future__ import annotations

from worldsim.rng import Stream

__all__ = ["make_name"]

# Silbenbausteine. Bewusst klein gehalten; die Kombinatorik reicht fuer Vielfalt.
_ONSETS = (
    "Ar", "Bel", "Cor", "Dra", "El", "Fen", "Gor", "Hal", "Is", "Kor",
    "Lys", "Mar", "Nor", "Or", "Pel", "Quen", "Ral", "Sel", "Tar", "Val",
    "Wyn", "Yr", "Az", "Thal",
)
_MIDS = ("a", "e", "i", "o", "u", "ae", "ia", "ou", "y", "ei")
_CODAS = (
    "ric", "dan", "mir", "thas", "wen", "dor", "gar", "lin", "vos", "mund",
    "rik", "sa", "neth", "tor", "val", "ys", "han", "mar",
)


def make_name(stream: Stream) -> str:
    """Erzeuge einen Namen aus drei Silben (feste Ziehzahl, deterministisch)."""
    onset = stream.choice(_ONSETS)
    mid = stream.choice(_MIDS)
    coda = stream.choice(_CODAS)
    return (onset + mid + coda).capitalize()
