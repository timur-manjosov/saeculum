"""worldmap — die prozedurale Karte: opensimplex-Terrain + politische Territorien.

Reine **Visualisierung ueber dem Adjazenzgraphen**. Die Regionen tragen seit dem
Karten-Ausbau eine geografische Koordinate (aus worldgen, Determinismus-Vertrag);
hier wird daraus eine Ansicht:

1. ein statisches Terrain-Feld aus ``opensimplex``-Rauschen (Biome ueber Schwellen),
   gedaempft gerendert, damit es zuruecktritt;
2. die Regionen per Koordinate darauf verortet; jede Landzelle faellt an die
   **naechstgelegene** Region (Voronoi ueber dem Graphen);
3. gehoert diese Region einer Polity, faerbt sich die Zelle **kraeftig** in deren
   Farbe. So werden Territorien als zusammenhaengende Flaechen sichtbar und ihre
   Grenzen wandern, wenn Polities expandieren, annektieren oder zerfallen.

Farben aus der Rosé-Pine-Moon-Palette: Terrain in gedaempften Neutraltoenen, die
Polity-Akzente treten als kraeftige Flaechen hervor. Read-only, kein Kern-RNG,
keine Simulationslogik, **keine** Tile-Mikrosimulation oder Geografie-Physik.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from opensimplex import OpenSimplex
from rich.panel import Panel
from rich.text import Text

from worldsim.models import EntityId, World
from worldsim.presentation.palette import ROSE_PINE_MOON as P

__all__ = ["biome_grid", "render_map"]

_MAP_W = 52  # Kartenbreite in Zeichen
_MAP_H = 17  # Kartenhoehe in Zeilen
_NOISE_SCALE = 3.4  # Feature-Groesse des Rauschens (kleiner ⇒ groessere Kontinente)

# Biom-Schwellen ueber dem Rauschwert (-1..1) ⇒ (Glyphe, gedaempfter Terrain-Ton).
# Die ersten ``_WATER_LEVELS`` sind Wasser (nie Territorium — Ozeane trennen Land).
_BIOMES: tuple[tuple[float, str, str], ...] = (
    (-0.28, "≈", P.pine),    # tiefe See
    (-0.08, "~", P.foam),    # Kueste / flaches Wasser
    (0.20, "·", P.muted),    # Ebene
    (0.52, "^", P.subtle),   # Huegel
    (1.01, "▲", P.text),     # Gebirge
)
_WATER_LEVELS = 2

# Polity-Farben (kraeftig) aus der Palette. Zuerst die terrain-fremden Akzente,
# damit die groessten Polities klar unterscheidbar bleiben; dann der Rest.
_POLITY_TONES: tuple[str, ...] = (P.love, P.gold, P.iris, P.rose, P.foam, P.pine, P.text)


@lru_cache(maxsize=8)
def biome_grid(seed: int, width: int = _MAP_W, height: int = _MAP_H) -> np.ndarray:
    """Das statische Terrain-Rauschfeld ``(height, width)`` in ``-1..1``.

    Reine Funktion von ``(seed, width, height)`` — das Terrain gehoert zum Seed,
    nicht zum jeweiligen Weltzustand. Gecacht (das Rauschen aendert sich nie) und
    schreibgeschuetzt zurueckgegeben.
    """
    gen = OpenSimplex(seed)
    field = np.empty((height, width), dtype=float)
    for r in range(height):
        for c in range(width):
            field[r, c] = gen.noise2(c / width * _NOISE_SCALE, r / height * _NOISE_SCALE)
    field.setflags(write=False)  # gecacht ⇒ nicht mutieren
    return field


def _biome_style(value: float) -> tuple[str, str, bool]:
    """Ordne einem Rauschwert (Glyphe, Terrain-Ton, ``is_water``) zu."""
    for level, (threshold, glyph, color) in enumerate(_BIOMES):
        if value < threshold:
            return glyph, color, level < _WATER_LEVELS
    return _BIOMES[-1][1], _BIOMES[-1][2], False


def _polity_tone(pid: EntityId, order: dict[EntityId, int]) -> str:
    """Stabile Polity-Farbe nach Rang (gleiche Polity ⇒ immer dieselbe Farbe)."""
    return _POLITY_TONES[order.get(pid, 0) % len(_POLITY_TONES)]


def _nearest_region(coords: np.ndarray, width: int, height: int) -> np.ndarray:
    """Fuer jede Zelle den Index der naechstgelegenen Region (Voronoi ueber Koordinaten)."""
    xs = (np.arange(width) + 0.5) / width
    ys = (np.arange(height) + 0.5) / height
    gx, gy = np.meshgrid(xs, ys)  # (H, W)
    dx = gx[..., None] - coords[:, 0]  # (H, W, N)
    dy = gy[..., None] - coords[:, 1]
    return (dx * dx + dy * dy).argmin(axis=2)  # (H, W) ⇒ Index in coords


def render_map(
    world: World,
    seed: int = 0,
    owners: dict[EntityId, EntityId] | None = None,
    *,
    width: int = _MAP_W,
    height: int = _MAP_H,
) -> Panel:
    """Rendere die Karte als ``rich``-Panel: Terrain plus politische Territorien.

    ``owners`` erlaubt es dem Replay, einen **rekonstruierten** Besitzstand zu
    zeigen; ohne Angabe gilt der aktuelle Weltzustand (so wandern im Watch-Mode die
    Grenzen Jahr fuer Jahr). Landzellen faerben sich in der Farbe der Polity, der
    ihre naechste Region gehoert; Wasser bleibt Wasser; Hauptstaedte tragen die
    Initiale ihrer Polity.
    """
    rids = sorted(world.regions)
    if not rids:
        return Panel(Text("(no regions)", style=P.muted), title=f"world map · seed {seed}")

    coords = np.array([world.regions[rid].coord for rid in rids], dtype=float)
    field = biome_grid(seed, width, height)
    nearest = _nearest_region(coords, width, height)
    owner_of = (
        owners
        if owners is not None
        else {rid: r.owner for rid, r in world.regions.items() if r.owner is not None}
    )
    order = {pid: i for i, pid in enumerate(sorted(world.polities))}

    # Hauptstadt-Marker: nur wo die Polity ihren Sitz aktuell auch haelt.
    cap_cell: dict[tuple[int, int], EntityId] = {}
    for pid in sorted(world.polities):
        cap = world.polities[pid].capital
        if cap is not None and cap in world.regions and owner_of.get(cap) == pid:
            cx, cy = world.regions[cap].coord
            col = min(width - 1, int(cx * width))
            row = min(height - 1, int(cy * height))
            cap_cell[(row, col)] = pid

    text = Text()
    for row in range(height):
        for col in range(width):
            pid = cap_cell.get((row, col))
            if pid is not None:
                letter = (world.polities[pid].name[:1] or "?")
                text.append(letter, style=f"bold {_polity_tone(pid, order)}")
                continue
            glyph, terrain, is_water = _biome_style(float(field[row, col]))
            if not is_water:
                owner = owner_of.get(rids[int(nearest[row, col])])
                if owner is not None:
                    text.append(glyph, style=f"bold {_polity_tone(owner, order)}")
                    continue
            text.append(glyph, style=f"dim {terrain}")
        if row != height - 1:
            text.append("\n")
    return Panel(text, title=f"world map · seed {seed}", title_align="left", border_style=P.muted)
