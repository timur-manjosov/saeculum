"""flow — Abflussmodell: wohin Wasser laeuft, wenn man es auf ein Hoehenfeld giesst.

Reine Numerik ueber einem Hoehengitter, **ohne** jede Weltkenntnis: kein Biom, keine
Platte, kein Seed, kein Zufall. Genau deshalb steht das Modul unter Terrain und Klima —
die Geologie braucht es fuer die Erosion, die Hydrologie fuer die Fluesse, und ohne diese
Trennung muesste eines der beiden vom anderen abhaengen (Zirkel).

Der Kern sind drei Schritte, die zusammen das ganze Modell sind:

1. :func:`fill_depressions` — **Priority-Flood**. Vom Meer aus wird das Gelaende
   geflutet: eine Senke fuellt sich, bis sie ueberlaeuft. Danach hat *jede* Zelle einen
   Weg nach unten (keine Sackgassen mehr), und die Fuellhoehe ueber dem Boden ist genau
   der **See**, der dort steht.
2. :func:`downstream_links` — **steilster Abstieg** auf der gefuellten Oberflaeche. Auf
   der Seeflaeche selbst ist sie flach; dort greift der Flutbaum (jede Zelle wurde von
   der Nachbarzelle aus erreicht, die naeher am Ueberlauf liegt), sodass der Abfluss
   auch durch einen See hindurch zum Ausfluss findet.
3. :func:`accumulate` — **Flow Accumulation**. Jede Zelle sammelt den Niederschlag
   aller Zellen, die zu ihr abfliessen. Das ist die eine Zahl, aus der alles Weitere
   folgt: ein Fluss ist eine Zelle mit viel Durchfluss, ein Strom eine mit sehr viel.

Die Reihenfolge, in der der Priority-Flood die Zellen abarbeitet, traegt das Ganze: sie
steigt monoton mit der Fuellhoehe, also fliesst jede Zelle **nur an frueher abgearbeitete
Zellen** ab. Rueckwaerts durchlaufen heisst damit: bachaufwaerts zuerst — die Akkumulation
ist ein einziger linearer Durchgang ohne Rekursion, und ein Kreislauf ist per Konstruktion
unmoeglich.
"""

from __future__ import annotations

import heapq
import math

import numpy as np

__all__ = [
    "Drainage",
    "accumulate",
    "downstream_links",
    "fill_depressions",
    "steepest_descent",
]

# Acht Nachbarn (D8), in fester Reihenfolge — Gleichstaende entscheidet damit immer
# derselbe Nachbar, und die Karte bleibt reproduzierbar.
NEIGHBOURS: tuple[tuple[int, int], ...] = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
)
# Schrittweite je Nachbar. Die diagonale ist laenger — sonst bevorzugte der steilste
# Abstieg die Diagonalen und die Fluesse liefen alle schraeg.
_STEPS: tuple[float, ...] = tuple(math.hypot(dr, dc) for dr, dc in NEIGHBOURS)


class Drainage:
    """Das Ergebnis des Priority-Flood: gefuellte Oberflaeche, Reihenfolge, Flutbaum."""

    __slots__ = ("filled", "order", "parent", "shape")

    def __init__(
        self, filled: np.ndarray, order: np.ndarray, parent: np.ndarray
    ) -> None:
        self.filled = filled  # (H, W): Hoehe der Wasseroberflaeche ueber dem Boden
        self.order = order    # (H*W,): Abarbeitungsreihenfolge, aufsteigend in filled
        self.parent = parent  # (H*W,): von welcher Zelle aus wurde geflutet (-1 = Quelle)
        self.shape = filled.shape

    def depth(self, ground: np.ndarray) -> np.ndarray:
        """Wie hoch das Wasser ueber dem Boden steht (0 ⇒ keine Senke ⇒ kein See)."""
        return np.maximum(self.filled - ground, 0.0)

    @property
    def upstream_first(self) -> np.ndarray:
        """Die Flutreihenfolge rueckwaerts: bachaufwaerts zuerst (fuer :func:`accumulate`)."""
        return self.order[::-1]


def fill_depressions(ground: np.ndarray, outlets: np.ndarray) -> Drainage:
    """Flute das Gelaende von den ``outlets`` (dem Meer) aus — Priority-Flood.

    Immer die *tiefste* noch offene Zelle wird als naechste abgearbeitet. Eine Zelle,
    die tiefer liegt als der Pass, ueber den man sie erreicht hat, steht damit unter
    Wasser: ihre Fuellhoehe ist die des Passes. Das ist die klassische Depressions-
    fuellung — und der See faellt als Nebenprodukt heraus, ohne dass ihn jemand gesucht
    haette.
    """
    height, width = ground.shape
    filled = np.array(ground, dtype=float)
    visited = np.zeros((height, width), dtype=bool)
    parent = np.full(height * width, -1, dtype=np.int64)
    order: list[int] = []

    # Der Rand des Flutens: das offene Meer. Ohne Meer (theoretisch) der tiefste Punkt —
    # irgendwohin muss das Wasser laufen.
    heap: list[tuple[float, int]] = []
    seeds = np.flatnonzero(outlets.ravel())
    if seeds.size == 0:
        seeds = np.array([int(np.argmin(ground))], dtype=np.int64)
    for idx in seeds:
        index = int(idx)
        visited.ravel()[index] = True
        heapq.heappush(heap, (float(filled.ravel()[index]), index))

    while heap:
        # Der Index bricht Gleichstaende — kein Zufall, keine Menge, kein Flattern.
        level, index = heapq.heappop(heap)
        order.append(index)
        row, col = divmod(index, width)
        for drow, dcol in NEIGHBOURS:
            nrow, ncol = row + drow, col + dcol
            if not (0 <= nrow < height and 0 <= ncol < width) or visited[nrow, ncol]:
                continue
            visited[nrow, ncol] = True
            # DAS ist die Fuellung: liegt der Nachbar tiefer als der Pass, ueber den wir
            # zu ihm kommen, steht er unter Wasser — bis zur Passhoehe.
            filled[nrow, ncol] = max(float(ground[nrow, ncol]), level)
            neighbour = nrow * width + ncol
            parent[neighbour] = index
            heapq.heappush(heap, (float(filled[nrow, ncol]), neighbour))

    return Drainage(filled, np.array(order, dtype=np.int64), parent)


def downstream_links(drainage: Drainage, outlets: np.ndarray) -> np.ndarray:
    """Fuer jede Zelle die Zelle, in die sie abfliesst (flacher Index; ``-1`` = Meer).

    Steilster Abstieg auf der **gefuellten** Oberflaeche. Wo es nicht abwaerts geht —
    auf der spiegelglatten Flaeche eines Sees —, uebernimmt der Flutbaum: er zeigt
    definitionsgemaess Richtung Ueberlauf. Beides zusammen ist kreisfrei, denn keine der
    beiden Regeln laeuft je aufwaerts, und innerhalb einer Seeflaeche folgt sie der
    Flutreihenfolge.
    """
    filled = drainage.filled
    height, width = filled.shape
    down = np.full(height * width, -1, dtype=np.int64)

    for row in range(height):
        for col in range(width):
            if outlets[row, col]:
                continue  # das Meer ist die Senke der Welt: hier endet der Weg
            here = float(filled[row, col])
            best, best_slope = -1, 0.0
            for (drow, dcol), step in zip(NEIGHBOURS, _STEPS, strict=True):
                nrow, ncol = row + drow, col + dcol
                if not (0 <= nrow < height and 0 <= ncol < width):
                    continue
                slope = (here - float(filled[nrow, ncol])) / step
                if slope > best_slope:  # strikt ⇒ der erste Nachbar gewinnt den Gleichstand
                    best, best_slope = nrow * width + ncol, slope
            index = row * width + col
            down[index] = best if best >= 0 else drainage.parent[index]
    return down


def steepest_descent(
    ground: np.ndarray, outlets: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Abfluss OHNE Fuellung ⇒ ``(down, upstream_first)``. Eine Senke schluckt ihr Wasser.

    Der Gegenentwurf zu :func:`fill_depressions`: hier laeuft das Wasser nur bergab, und
    wo es nicht mehr bergab geht, bleibt es liegen (``down = -1``) — eine **abflusslose
    Senke**, aus der es verdunstet, statt ueber den Pass zu schwappen.

    Genau das braucht die Erosion. Fuellt man erst und laesst dann alles ueber den Pass
    laufen, traegt der Pass den gesamten Abfluss des Beckens, wird zerschnitten — und das
    Becken laeuft leer. Gemessen: die Erosion loeschte damit die Haelfte aller Seen der
    Welt, obwohl sie sie doch gerade in Ruhe lassen sollte. Ein abflussloses Becken hat
    keinen Abfluss; sein Pass sieht kein Wasser und wird nicht durchgesaegt.

    Die Reihenfolge ist hier trivial: absteigend nach Hoehe. Weil jeder Schritt echt
    bergab geht, ist jede Zelle vor ihrem Ziel dran.
    """
    height, width = ground.shape
    down = np.full(height * width, -1, dtype=np.int64)
    for row in range(height):
        for col in range(width):
            if outlets[row, col]:
                continue
            here = float(ground[row, col])
            best, best_slope = -1, 0.0
            for (drow, dcol), step in zip(NEIGHBOURS, _STEPS, strict=True):
                nrow, ncol = row + drow, col + dcol
                if not (0 <= nrow < height and 0 <= ncol < width):
                    continue
                slope = (here - float(ground[nrow, ncol])) / step
                if slope > best_slope:
                    best, best_slope = nrow * width + ncol, slope
            down[row * width + col] = best  # -1 ⇒ Senke: das Wasser bleibt hier
    order = np.argsort(ground, axis=None, kind="stable")[::-1]  # hoch ⇒ tief
    return down, order


def accumulate(
    down: np.ndarray, upstream_first: np.ndarray, precipitation: np.ndarray
) -> np.ndarray:
    """Sammle den Niederschlag bergab auf: der Durchfluss jeder Zelle.

    Ein einziger Durchgang, bachaufwaerts zuerst — ``upstream_first`` garantiert, dass
    jede Zelle vor ihrem Abflussziel abgearbeitet wird, ihr eigener Zufluss also
    vollstaendig ist. Weder Rekursion noch Iteration, und ein Kreislauf ist ausgeschlossen.
    """
    flow = np.array(precipitation, dtype=float).ravel()
    for index in upstream_first:
        target = int(down[index])
        if target >= 0:
            flow[target] += flow[index]
    return flow.reshape(precipitation.shape)
