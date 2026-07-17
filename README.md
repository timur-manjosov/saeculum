# History Machine

**A world that writes its own history.**

`saeculum` is a small, headless, fully deterministic world simulation. Dumb, trait-driven
nations rise, expand, war, ally, convert, schism, and collapse — and every meaningful change
emits a **causal event** carrying the *named factors that produced it*. The product isn't the
map or the score (there is none); it's the **chronicle**: a readable, navigable, causally
linked history you can replay in seconds and interrogate with "why?".

> Less *Dwarf-Fortress micro-simulation*, more *Legends Mode as a first-class citizen* — the
> generated, causally traceable chronicle **is** the game.

---

## Showcase

<!-- TODO: animated GIF of a run — the rise and fall of powers across the ages.
     Record with: saeculum replay --seed 42 --years 200  (on a real terminal)
     then capture to docs/rise-and-fall.gif and embed below. -->

![rise and fall of empires — replay (placeholder)](docs/rise-and-fall.gif)

### A real chronicle (excerpt, `saeculum export --seed 42 --years 200`)

```text
History Machine — seed 42, 200 years (config v6)

=== the First Expansion ===
Year 0: Quenougar was founded in the upper forests.
Year 0: Lysetor was founded in the northern marches.
Year 0: Quenougar and Lysetor allied against Elytor.
Year 1: a plague struck Oreisa, killing 65.
Year 7: Ralaeric succeeded to the throne of Wynadan (inherited). A turning point.
Year 11: Lysetor expanded into the western forests.
Year 12: a plague spread to Elytor, killing 99.

=== the Age of Lysetor (from year 12) ===
Year 12: the plague that had weakened Elytor allowed Lysetor to rise to dominance — a turning point.
Year 13: Elytor and Oreisa allied against Lysetor.
Year 16: the Goraedor faith became the dominant creed — a turning point.
Year 26: the Draowen faith schismed from the Goraedor faith within Lysetor.
Year 26: the schism of the Goraedor faith shattered the alliance between Lysetor and Oririk.

=== the Age of Oreisa (from year 26) ===
    … generations of war, plague, conversion and succession …
Year 61: the plague that had weakened Oreisa allowed Wynadan to rise to dominance — a turning point.

------------------------------------------------------------
seed 42 · 200 years · config v6 · 10 nations · 21 faiths · 85 disasters · 13 turning points · 709 events
reproduce this world:  saeculum export --seed 42 --years 200
```

Nothing above is hand-written prose stored in the save. Each line is *derived* from a structured
event and its named factors — the same factors that drove the decision. Ask the machine *why*
a power fell and it walks the causal graph back to the root:

```text
$ saeculum export --seed 42 --years 200 --why 30
Why did Lysetor suffer? — Year 26: Lysetor collapsed, losing much of its realm — a turning point.
  └─ Year 19: Elytor defeated Lysetor and annexed the western forests. [Zufall -0.11, Militaervorteil -0.03]
      └─ Year 19: Lysetor declared a war of faith on Elytor, driven by Aggression (+0.82), Vorsicht (-0.44), Glaubensgraben (+0.40).
```

---

## Install

Python **3.11+**. The **core** knows nothing about the display: it depends on `numpy` and
`opensimplex` for the geography (the simulation runs *on* the map), and on nothing else —
`simulate(seed, years)` never loads a line of rendering code. Colour, the map, the live view
and the replay live in the presentation layer and pull in `rich`.

```bash
# clone, then from the repo root:
python -m venv .venv && source .venv/bin/activate

# headless core only (worldgen + simulation, no rendering):
pip install .

# everything you can look at (watch / replay / explore / map / stats):
pip install ".[presentation]"

# for development (tests + linter):
pip install ".[dev]"
```

## Run

Just run it:

```bash
saeculum
```

That's the whole thing. A random world, live, from the first founding to the last collapse —
the plain call **is** the beautiful mode. The seed is printed at the end, with the line that
brings the world back.

```bash
saeculum -s 42 -y 400              # watch that exact world, a little longer
saeculum watch -s 42 --speed 4     # slowly, in peace
saeculum replay -s 42              # the finished history, fast-forwarded from the log
saeculum explore -s 42             # ask the causal graph: why did this nation fall?
saeculum export -s 42 > world.txt  # save the chronicle as text
```

Redirect or pipe the plain call and it falls back to the text chronicle, so
`saeculum > world.txt` stays sensible — nobody wants a dashboard in a file.

| Command | What it does |
| --- | --- |
| `watch` | the live view — the default on a terminal |
| `replay` | the whole history, fast-forwarded from the event log |
| `explore` | walk the causal graph: `why <nation>`, `who <id>`, `into <id>` |
| `export` | the chronicle as text — the default when piped |

The same flags mean the same thing everywhere:

| Flag | Meaning |
| --- | --- |
| `-s, --seed N` | the shareable identity of a world (default: random, shown at the end) |
| `-y, --years N` | years to simulate (default `300`) |
| `--speed N` | years per second in `watch`/`replay` (also `+`/`-` while it runs) |
| `--view {political,terrain}` | politics as area, or geography in full colour (also `m` while it runs) |
| `--no-map` | hide the map in `watch`/`replay` — a quieter view |
| `--stats` | end-of-run population/power/activity sparklines + summary |
| `--map` | print the world map (`export`) |
| `--why ENTITY` / `--why-event ID` | walk the causal graph back from a setback (`export`) |
| `--explain N` | factor breakdown of the first `N` wars (`export`) — the reasoning is the numbers |

In `watch` and `replay`: space pauses, `n` steps a single year, `+`/`-` change the tempo, `m`
switches the map, `q` leaves. Both need a real terminal to animate and fall back to snapshot
frames when piped. `saeculum <command> --help` explains each one.

**Save = Seed**: a run is fully determined by `(seed, years, config_version)`, so sharing the
seed shares the world. Every run ends with the exact line that reproduces it:

```text
------------------------------------------------------------
seed 838345 · 400 years · config v15 · 9 nations · 14 faiths · 31 disasters · 8 turning points · 2104 events
reproduce this world:  saeculum watch --seed 838345 --years 400
```

---

## How it works (architecture)

One-way layered dependencies — nothing depends upward:

```
config, rng  →  models  →  events  →  systems  →  driver
                                                     │
                              chronicle  →  presentation  →  main
```

- **State is pure data** (`dataclasses`); **behaviour lives in systems** (pure functions).
  `simulate(seed, years) -> (World, EventLog)` is a pure function of its input.
- **The causal event graph is the backbone.** Every significant change emits an `Event` that
  carries (a) named `(label, weight)` **factors** and (b) `causes` — references to the events
  that led to it. Decisions are computed as a **sum of named factors**; *the factors are the
  reasoning* — never an opaque formula with a pretty explanation bolted on afterwards.
- **Determinism is an invariant.** One seeded master RNG fans out into named sub-streams;
  decision paths iterate only over stably sorted collections; cosmetic randomness uses a
  separate stream that never touches the master. Same input ⇒ identical world *and* identical
  event ids.
- **Dumb agents, rich interaction.** No search, no planning, no back-induction — local,
  trait-weighted choices. Complexity emerges from the interplay of a few systems (subsistence,
  economy, diplomacy, war, rulers, identity/faith, disasters, technology), not from clever
  single algorithms.
- **Ockham.** No physics engine, no ECS, no save system (the seed *is* the save), no victory
  condition and no score — **observation is the primary mode**.

The presentation layer is strictly **read-only** over the world and log: a single
event→visual mapping drives *both* the live view and the replay, and the replay reconstructs
the observable state **from the log alone** (no re-simulation).

The binding specifications live in [`docs/`](docs/):
[`architektur-welt-simulation.md`](docs/architektur-welt-simulation.md) (what is simulated and
how the world evolves) and [`architektur-history-machine.md`](docs/architektur-history-machine.md)
(the canonical causal event model — it dominates on conflict).

---

## Development

```bash
pip install ".[dev]"
ruff check .      # lint
pytest            # tests (headless core + presentation)
```

A dedicated test asserts that running `simulate` never pulls `rich` into `sys.modules`, keeping
the layering honest: the core may know the geography, but never the display.
