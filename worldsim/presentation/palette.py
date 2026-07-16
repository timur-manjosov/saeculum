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

__all__ = ["NATURAL_EARTH", "REALM_LEAF", "ROSE_PINE_MOON", "Palette", "TerrainPalette"]


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


# Der sechste Landeston — das Gruen, das Rosé Pine nicht hat.
#
# Die Karte braucht sechs FLAECHENfarben, die einander und dem Meer fernbleiben; das
# offizielle Schema liefert davon nur fuenf. Sein einziger "gruener" Akzent (``pine``) ist
# naemlich ein Meeresblau: gemessen liegt ``#3e8fb0`` nur **24** von den Ozeanstufen
# entfernt (redmean, siehe ``worldmap._tone_distance``) — ein pine-farbenes Reich an der
# Kueste IST die See, und daran aendert kein Abdunkeln etwas, weil es der Farbton selbst
# ist. Gruen ist der eine Ton, den Wasser nie annimmt, und liegt zugleich von
# love/gold/iris/foam/text am weitesten weg: schlechtester Abstand **144** statt pine 24.
# In Saettigung und Helligkeit (S 0.50, V 0.90) sitzt er mitten im Fenster der uebrigen
# Akzente (love: S 0.53, V 0.92), faellt also nicht aus der Anmutung.
#
# Er traegt bewusst KEINE Bedeutung: die sechs Akzente oben stehen fuer Ereignisarten,
# dieser Ton ist reine Kartografie. Darum steht er NEBEN dem Schema und nicht darin —
# aus demselben Grund, aus dem :class:`TerrainPalette` getrennt liegt.
REALM_LEAF = "#7ce673"


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

    **Seit Schritt 4 sind die Wassertoene FLAECHEN, keine Glyphenfarben** (die See traegt
    kein Zeichen mehr, nur ihren Grund — siehe :mod:`worldsim.presentation.worldmap`). Ein
    Ton, der als duenne Glyphe auf dunklem Grund gerade richtig sass, ist als flaechiger
    Hintergrund viel zu laut: der alte Kuestensaum ``#6aa9c6`` lag bei Helligkeit 153 und
    haette damit jeden Saum so hell gemacht wie ein ganzes Reich. Das Meer liegt darum
    jetzt geschlossen **unter** dem Land (Helligkeit 26..86 gegen ~96 des freien Landes) —
    daher stammt die Lesbarkeit "das ist Wasser" auf den ersten Blick.
    """

    # Ozean in Tiefenstufen (dunkel = tief): das gibt der Karte raeumliche Tiefe.
    # Alle vier sind FLAECHEN und bewusst dunkler als jedes Land — die Stufen sind der
    # einzige Kontrast, den das Meer sich leistet.
    abyss: str      # Tiefseegraben — fast schwarzblau
    deep_sea: str   # offene Tiefsee
    shelf: str      # ersoffener Kontinentalsockel / flaches Randmeer
    coast: str      # der Kuestensaum: die hellste Wasserstufe, aber immer noch Wasser
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
    # Das Meer: vier Stufen zwischen Helligkeit 26 und 86 — eine geschlossene, dunkle
    # Flaeche unter allem Land. Der Abstand zwischen den Stufen traegt die Tiefe, der
    # Abstand zum Land traegt die Aussage "hier hoert die Welt auf".
    abyss="#131a2b",
    deep_sea="#1a2c4a",
    shelf="#234668",
    coast="#2f6187",
    # Packeis: der einzige Ton der Karte, der in eine LUECKE gezwaengt ist statt in ein Band.
    # Er muss nach oben vom weisslichen ``text``-Reich (225) und nach unten vom freien Land
    # (~102) wegbleiben, und beides zieht in verschiedene Richtungen. Gemessen (Abstand zum
    # naechsten Reich / freien Land / Ozean): das alte glaenzende ``#cddbe6`` kommt einem
    # ``text``-Reich auf 38 nahe, ein dunkles ``#6b7f96`` dem freien Polarland auf 33 —
    # beide Extreme verschmelzen mit etwas. Bei 175 Helligkeit haelt es zu allen dreien
    # Abstand (89 / 92 / 231) und liest sich immer noch als Eis.
    sea_ice="#9fb3c6",

    river="#5aa6d0",
    stream="#93d1e8",
    lake="#2f6f9b",  # Suesswasser: eine Spur heller und kuehler als das Randmeer
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
