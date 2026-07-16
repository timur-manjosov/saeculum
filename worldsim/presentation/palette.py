"""palette — die zentrale Farbdefinition der Praesentation (Rosé Pine Moon).

**Ein** Ort fuer alle Farben: das offizielle Rosé-Pine-Moon-Schema als benannte
Rollen. Nirgendwo sonst im Code stehen Hex-Werte — Ereignisfarben, Chrome (Regeln,
Rahmen) und die Bilanztafel leiten ihre Toene **hier** ab. So bleibt die visuelle
Sprache kohaerent und an einer Stelle aenderbar.

Bewusst **abhaengigkeitsfrei** (reine Strings, keine ``rich``-Bindung): die Werte
sind ``rich``-kompatible Hex-Strings, die die Renderer als Stil deuten. Die sechs
Akzente tragen **Bedeutung** (Krieg, Not, Wachstum, …); die Neutraltoene tragen die
Struktur (Text, Linien, Rahmen).
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["NATURAL_EARTH", "ROSE_PINE_MOON", "Palette", "TerrainPalette"]


@dataclass(frozen=True)
class Palette:
    """Ein benanntes Farbschema — Neutraltoene (Struktur) und Akzente (Bedeutung).

    Feldnamen folgen dem Rosé-Pine-Kanon, damit die Zuordnung nachvollziehbar
    bleibt. Werte sind Hex-Strings (``#rrggbb``), direkt als ``rich``-Stil nutzbar.
    """

    # Neutraltoene: Grund, Flaechen, Linien, Text — sie tragen die Struktur.
    base: str
    surface: str
    overlay: str
    muted: str
    subtle: str
    text: str
    # Akzente: sie tragen die Bedeutung (Ereignisarten, hervorgehobene Werte).
    love: str  # Rot: Krieg, Schlacht, Bruch
    gold: str  # Bernstein: Hungersnot, Spannung
    rose: str  # Koralle: akute Katastrophe
    pine: str  # Gruen/Teal: Gruendung, Expansion, Buendnis, Wachstum
    foam: str  # Cyan: Innovation/Werk
    iris: str  # Violett: Sukzession, Abspaltung, Glaube
    # Hervorhebungs-Toene (Rosé-Pine ``highlight``): dezente Flaechen/Trenner.
    highlight_low: str
    highlight_med: str
    highlight_high: str


# Rosé Pine Moon — die gedaempfte Nacht-Variante des Schemas (offizielle Hex-Werte).
ROSE_PINE_MOON = Palette(
    base="#232136",
    surface="#2a273f",
    overlay="#393552",
    muted="#6e6a86",
    subtle="#908caa",
    text="#e0def4",
    love="#eb6f92",
    gold="#f6c177",
    rose="#ea9a97",
    pine="#3e8fb0",
    foam="#9ccfd8",
    iris="#c4a7e7",
    highlight_low="#2a283e",
    highlight_med="#44415a",
    highlight_high="#56526e",
)


@dataclass(frozen=True)
class TerrainPalette:
    """Die **natuerlichen** Toene der Karte — Erde, Wasser, Vegetation.

    Bewusst getrennt von :class:`Palette`: das Rosé-Pine-Schema traegt die *Bedeutung*
    (Chrome, Rahmen, Ereignisarten, Polity-Akzente), diese Toene tragen die *Welt*. So
    kann das Land in echten Erdfarben liegen, ohne dass die sechs Akzente ihre semantische
    Rolle verlieren — ein Reich hebt sich weiterhin **kraeftig** von der gedaempften Natur
    ab. Auch hier: **ein** Ort, ``#rrggbb``-Strings, direkt als ``rich``-Stil nutzbar.

    Die Toene sind so gewaehlt, dass sie auf dem dunklen Rosé-Pine-Grund lesbar liegen und
    unter der Hoehenschattierung (:func:`worldmap._hillshade`) sowohl abdunkeln als auch
    aufhellen koennen, ohne zu kippen.
    """

    # Ozean in Tiefenstufen (dunkel = tief): das gibt der Karte raeumliche Tiefe.
    abyss: str      # Tiefseegraben — fast schwarzblau
    deep_sea: str   # offene Tiefsee
    shelf: str      # ersoffener Kontinentalsockel / flaches Randmeer
    coast: str      # der helle Kuestensaum
    sea_ice: str    # gefrorener Polarozean (Packeis) — die sichtbare Polkappe
    # Suesswasser (heller, kuehler als das Meer ⇒ es liest sich als anderes Wasser).
    river: str
    stream: str     # der grosse Strom — heller/breiter
    lake: str
    # Vegetation, nach Feuchte/Waerme gestaffelt (dunkelgruen = ueppig).
    rainforest: str
    forest: str     # geschlossener gemaessigter Wald
    taiga: str      # kuehler Nadelwald
    grassland: str
    wetland: str
    # Trockenland (Sand- und Bernsteintoene).
    savanna: str
    steppe: str
    desert: str
    # Kalt und Fels (Grau bis Schnee-Weiss).
    tundra: str
    alpine: str     # nackter Hochgebirgsfels
    snow: str       # Gletscher/Schnee


# Erdtoene, abgestimmt auf den Rosé-Pine-Grund: gedaempft genug, dass die Polity-Akzente
# hervortreten, gesaettigt genug, dass Ozean, Wueste und Wald klar auseinanderfallen.
NATURAL_EARTH = TerrainPalette(
    abyss="#141d33",
    deep_sea="#1e3a63",
    shelf="#2f6488",
    coast="#6aa9c6",
    sea_ice="#cddbe6",  # blasses Eisblau-Weiss: kalt, aber vom Schnee-Weiss des Landes lesbar

    river="#5aa6d0",
    stream="#93d1e8",
    lake="#3d7ba8",
    rainforest="#2f6b39",
    forest="#4c8a48",
    taiga="#3d7d64",
    grassland="#8aad52",
    wetland="#4f9c86",
    savanna="#b39a51",
    steppe="#c3ac66",
    desert="#dac384",
    tundra="#8f9a88",
    alpine="#9b96a1",
    snow="#e7edf2",
)
