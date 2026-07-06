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

__all__ = ["ROSE_PINE_MOON", "Palette"]


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
