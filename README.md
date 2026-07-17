<div align="center">

# Saeculum

***A terminal where a world simulates itself — and writes its own history.***

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

</div>

---

No two worlds are alike, and none of them were designed. Continents come from tectonics, rain
from the winds that cross them, rivers from the rain — and where a river meets good soil, someone
builds a capital. Nothing in the history that follows is scripted: nations are run by dumb,
trait-driven rulers who cannot plan, only react to what is next to them. Ambition meets a weak
neighbour and becomes a war. Hunger meets a proud elite and becomes a coup. There are no random
catastrophes, no dice rolled behind your back to make things interesting — a realm falls apart
because of pressures it built up itself, and the chronicle can tell you which ones.

The product isn't the map, and there is no score to win. It's the **chronicle**: a readable,
causally linked history you can replay in seconds and interrogate with *why?* — every event
carries the named factors that produced it and the events that caused it. And all of it is a pure
function of one number. Share the seed, share the world, down to the last event id.

## A world, unabridged

This is not a mock-up. It is the opening of seed `5`, exactly as the machine wrote it — a nation
called Fenoric wins a war of faith, and for thirty-six years it is the world:

```text
──────────────────── the First Expansion  ·  from year 0 ────────────────────
⌂ Year 0:  Thalator was founded in the upper highlands.
⌂ Year 0:  Halemir was founded in the northern steppe.
⌂ Year 0:  Arisa was founded in the central valley.
⌂ Year 0:  Thalohan was founded in the lower coast.
⌂ Year 0:  Fenoric was founded in the inner highlands.
⌂ Year 0:  Maruneth was founded in the far moors.
⚔ Year 11:  Fenoric declared a war of faith on Thalohan, driven by Aggression (+0.75),
            Glaubensgraben (+0.40), Wegekosten (+0.40).
× Year 11:  Fenoric defeated Thalohan and annexed the western delta.

───────────────────── the Age of Fenoric  ·  from year 14 ─────────────────────
★ Year 14:  Fenoric supplanted Thalohan as the dominant power — a turning point.
      Machtwechsel: +1.2
      ↳ Year 11: Fenoric defeated Thalohan and annexed the western delta.
═ Year 16:  Thalator and Halemir allied against Fenoric.
═ Year 17:  Arisa and Maruneth allied against Fenoric.
═ Year 19:  Thalator and Arisa allied against Fenoric.

   […  twenty-eight years: six more alliances, four wars, and Fenoric holds  …]

⚔ Year 47:  Thalohan sought escape from its mounting crisis in war on Fenoric, driven by
            Aussendruck (+2.21), Furcht (-1.86), Grenzreibung (+1.00).
× Year 47:  Thalohan defeated Fenoric and annexed the outer steppe.
⚔ Year 48:  Tarovos declared war on Fenoric, driven by Grenzreibung (+1.00),
            Aggression (+0.94), Misstrauen (+0.61).
× Year 48:  Tarovos defeated Fenoric and annexed the lower forests.
★ Year 48:  Fenoric collapsed, losing much of its realm — a turning point.
      Gebietskollaps: +5.0
      ↳ Year 48: Tarovos defeated Fenoric and annexed the lower forests.

────────────────────── the Age of Arisa  ·  from year 50 ──────────────────────
★ Year 50:  Arisa supplanted Fenoric as the dominant power — a turning point.
      Machtwechsel: +1.2
      ↳ Year 48: Tarovos defeated Fenoric and annexed the lower forests.
```

Nobody taught the world about the balance of power. Fenoric grew from one region to ten, and one
by one its neighbours found each other: of the fourteen alliances sworn in those first fifty
years, **twelve named Fenoric as the enemy**. Read year 47 closely — Thalohan attacks the
strongest realm on the map while `Furcht (-1.86)`, fear, argues against it, and loses that
argument to `Aussendruck (+2.21)`, the pressure of its own unsolved crisis. It was not brave. It
was cornered.

And then the punchline nobody wrote: **Arisa inherits the world without winning a battle.** It
sat on exactly one region — the valley it was founded in — for forty-six years, the whole Age of
Fenoric. Then, as the hegemon was carved up, it took four more in four years.

> **Reproduce this world:** `saeculum watch --seed 5 --years 800`

<details>
<summary><b>▸ Why did Arisa rise? Ask the machine.</b> — <i>the causal graph, walked backwards</i></summary>

<br>

Every line above is *derived* from a structured event — never prose stored in a save file. So the
chronicle can be interrogated. Arisa became the dominant power in year 50; here is the machine's
own answer for how it got there:

```console
$ saeculum export --seed 5 --years 800 --why-event 139

Why? — Year 50: Arisa supplanted Fenoric as the dominant power — a turning point.
  └─ Year 48: Tarovos defeated Fenoric and annexed the lower forests. [Zufall -0.12, Militaervorteil -0.06]
      └─ Year 48: Tarovos declared war on Fenoric, driven by Grenzreibung (+1.00), Aggression (+0.94), Misstrauen (+0.61). [Grenzreibung +1.00, Aggression +0.94, Misstrauen +0.61]
          └─ Year 40: border tension rose between Fenoric and Tarovos. [Grenzreibung +2.20]
          └─ Year 43: border tension rose between Fenoric and Tarovos. [Grenzreibung +3.10]
          └─ Year 47: border tension rose between Fenoric and Tarovos. [Grenzreibung +4.00]
```

Read it bottom-up and the age turns on a border: friction between Fenoric and Tarovos rises for
seven years — **+2.20 → +3.10 → +4.00** — until it outweighs Tarovos's caution and becomes a war.
Tarovos wins, Fenoric breaks, and the age passes to **Arisa — who is nowhere in this chain.** The
question was "why did Arisa rise?" and the honest answer is a quarrel it had no part in.

Those numbers are not a story told about the decision afterwards. They *are* the decision: the
same weighted factors were summed to choose the war, then saved onto the event. If a factor
didn't move the outcome, it cannot appear here; if it did, it must.

Walk it yourself — `saeculum explore --seed 5 --years 800`, then `why Arisa`, `into 139`.

</details>

## Quickstart

Python **3.11+**.

```bash
git clone git@github.com:timur-manjosov/saeculum.git && cd saeculum
python -m venv .venv && source .venv/bin/activate

pip install ".[presentation]"   # everything you can look at
```

Then just run it:

```bash
saeculum
```

That's the whole thing — a random world, live, from the first founding to the last collapse. The
seed is printed at the end, with the line that brings the world back.

```bash
saeculum -s 5 -y 800                 # watch that exact world
saeculum watch -s 5 --speed 4        # slowly, in peace
saeculum replay -s 5                 # the finished history, fast-forwarded from the log
saeculum explore -s 5                # ask the causal graph: why did this nation fall?
saeculum export -s 5 > world.txt     # the chronicle as text
```

| Command | What it does |
| --- | --- |
| `watch` | the live view — the default on a terminal |
| `replay` | the whole history, fast-forwarded from the event log |
| `explore` | walk the causal graph: `why <nation>`, `who <id>`, `into <id>` |
| `export` | the chronicle as text — the default when piped |

Shared flags: `-s/--seed`, `-y/--years`, `--speed` (years per second), `--view political|terrain`.
While watching: `space` pauses, `n` steps a year, `+`/`-` change tempo, `m` switches the map, `q`
quits. Pipe the plain call and it falls back to text — nobody wants a dashboard in a file.

`pip install .` alone gets you the headless core, with no rendering stack at all.

## Highlights

- **History nobody wrote.** Wars, schisms, coups and collapses are outcomes, not scripted
  content. A realm falls because of pressure it accumulated — never a random catastrophe.
- **Every event answers "why?".** The causal graph is the backbone: each event carries the named
  factors that produced it and links to the events that caused it. Ask why a power fell and the
  machine walks the chain back to a border quarrel forty years earlier.
- **Earth-like worlds from process.** Tectonics → climate → rivers, not noise dressed up as a
  map. The simulation runs *on* that geography: mountains and open sea are expensive, rivers and
  coasts are cheap, so terrain becomes barrier and corridor without a single pathfinding rule.
- **Determinism you can share.** Save = seed. One number reproduces the world exactly, down to
  identical event ids. There is no save system, because there is nothing to save.
- **Two views of the same truth.** The map carries politics as area and terrain as glyph
  (`m` toggles) — one canonical geography, never a second version of the facts.

## How it works

Every meaningful change emits an immutable **event** carrying `(label, weight)` factors and
references to its causes — decisions are computed as a *sum of named factors*, so the reasoning
and the calculation are the same object; there is no pretty explanation bolted on afterwards.
Nations don't plan: they react locally, weighted by their rulers' traits, and the interesting
behaviour falls out of a handful of systems (subsistence, economy, diplomacy, war, faith, rulers)
pulling on each other — hunger feeds unrest, unrest erodes legitimacy, and a realm that has run
out of internal answers goes looking for an external one. Geography is the ground truth
underneath all of it, derived once per world and read by simulation and map alike.

The binding specifications live in [`docs/`](docs/): [`architektur-welt-simulation.md`](docs/architektur-welt-simulation.md)
(what is simulated and how the world evolves) and [`architektur-history-machine.md`](docs/architektur-history-machine.md)
(the causal event model — it wins on conflict).

## Built with

[Python](https://www.python.org/) · [rich](https://github.com/Textualize/rich) for the terminal ·
[numpy](https://numpy.org/) and [opensimplex](https://github.com/lmas/opensimplex) for the
geography. The core knows the geography but never the display — a test pins that `simulate()`
never pulls `rich` into `sys.modules`.

```bash
pip install ".[dev]"
ruff check .      # lint
pytest            # tests
```

## License

[MIT](LICENSE) © Timur Manjosov

<!--
  Optional media — record on a real terminal and drop the files in docs/, then uncomment.

  HERO-REPLAY   — the rise and fall of Fenoric, ages flashing past:
                  saeculum replay --seed 5 --years 800 --speed 30
  ![the rise and fall of powers across the ages](docs/hero-replay.gif)

  MAP-OVERLAY   — the political layer over the terrain layer, toggled with `m`:
                  saeculum watch --seed 5 --view political   (then press m)
  ![political and terrain views of the same world](docs/map-overlay.png)

  EXPLORE       — walking the causal graph back from Arisa's rise:
                  saeculum explore --seed 5 --years 800   (then: why Arisa · into 139)
  ![walking the causal graph](docs/explore.gif)
-->
