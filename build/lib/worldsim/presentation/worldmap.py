"""worldmap — optionale prozedurale Karte: opensimplex-Rauschen ⇒ Biome.

Reine **Visualisierung ueber dem Adjazenzgraphen** (die Regionen tragen keine
Koordinaten; die Simulation kennt keine Karte). Wir legen die Regionen
deterministisch auf ein Gitter, sampeln ``opensimplex``-Rauschen fuer ihr Biom
(ueber Schwellen) und faerben belegte Felder in der Farbe ihrer Nation ein.

Read-only, kein RNG des Kerns, keine Simulationslogik: die Karte ist eine reine
Ansicht des (ggf. aus dem Log rekonstruierten) Besitzstands.
"""

from __future__ import annotations

import math

import numpy as np
from opensimplex import OpenSimplex
from rich.panel import Panel
from rich.text import Text

from worldsim.models import EntityId, World

__all__ = ["biome_grid", "render_map"]

# Biom-Schwellen ueber dem Rauschwert (-1..1) ⇒ (Name, Glyphe, Farbe).
_BIOMES: tuple[tuple[float, str, str, str], ...] = (
    (-0.35, "water", "≈", "blue"),
    (-0.10, "coast", "~", "cyan"),
    (0.15, "plains", ".", "green"),
    (0.40, "forest", "♣", "dark_green"),
    (0.70, "hills", "n", "yellow"),
    (1.01, "mountains", "▲", "grey70"),
)

# Nations-Farbpalette (stabil nach Rang vergeben).
_NATION_COLORS = (
    "bright_red", "bright_green", "bright_yellow", "bright_blue",
    "bright_magenta", "bright_cyan", "red", "green", "yellow", "blue",
    "magenta", "cyan", "orange3", "purple", "spring_green2", "deep_pink3",
)


def _grid_dims(n: int) -> tuple[int, int]:
    """Kompakte, deterministische Gittermasse fuer ``n`` Regionen."""
    cols = max(1, math.ceil(math.sqrt(n)))
    rows = max(1, math.ceil(n / cols))
    return cols, rows


def _biome_of(value: float) -> tuple[str, str, str]:
    """Ordne einem Rauschwert (-1..1) ein Biom (Name, Glyphe, Farbe) zu."""
    for threshold, name, glyph, color in _BIOMES:
        if value < threshold:
            return name, glyph, color
    return _BIOMES[-1][1:]


def biome_grid(world: World, seed: int) -> np.ndarray:
    """Deterministische Biom-Karte je Region als Rauschwerte (-1..1).

    Jede Region liegt fest auf ``(id % cols, id // cols)``; das Rauschen wird
    dort gesampelt. Reproduzierbar fuer gleichen ``seed`` und gleiche Regionszahl.
    """
    ids = sorted(world.regions)
    cols, _ = _grid_dims(len(ids))
    gen = OpenSimplex(seed)
    values = np.empty(len(ids), dtype=float)
    for i, _rid in enumerate(ids):
        x, y = i % cols, i // cols
        values[i] = gen.noise2(x * 0.6, y * 0.6)
    return values


def _nation_color(pid: EntityId, order: dict[EntityId, int]) -> str:
    return _NATION_COLORS[order.get(pid, 0) % len(_NATION_COLORS)]


def render_map(
    world: World,
    seed: int = 0,
    owners: dict[EntityId, EntityId] | None = None,
) -> Panel:
    """Rendere die prozedurale Karte als ``rich``-Panel.

    ``owners`` erlaubt es dem Replay, den **rekonstruierten** Besitzstand eines
    beliebigen Zeitpunkts zu zeigen; ohne Angabe wird der aktuelle Weltzustand
    gezeigt. Belegte Felder erscheinen als farbiger Nationsbuchstabe ueber dem
    Biom, freie Felder als gedaempftes Biom-Symbol.
    """
    ids = sorted(world.regions)
    cols, rows = _grid_dims(len(ids))
    noise = biome_grid(world, seed)
    owner_of = owners if owners is not None else {
        rid: r.owner for rid, r in world.regions.items() if r.owner is not None
    }
    order = {pid: i for i, pid in enumerate(sorted(world.polities))}

    text = Text()
    for row in range(rows):
        for col in range(cols):
            i = row * cols + col
            if i >= len(ids):
                text.append("  ")
                continue
            rid = ids[i]
            _name, glyph, biome_color = _biome_of(float(noise[i]))
            pid = owner_of.get(rid)
            if pid is not None:
                color = _nation_color(pid, order)
                letter = world.polities[pid].name[:1] if pid in world.polities else "?"
                text.append(letter, style=f"bold {color}")
                text.append(glyph, style=biome_color)
            else:
                text.append(glyph, style=f"dim {biome_color}")
                text.append(" ")
        text.append("\n")
    return Panel(text, title=f"world map (seed {seed})", border_style="grey50")
