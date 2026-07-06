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
     Record with: worldsim --seed 42 --years 200 --mode replay  (on a real terminal)
     then capture to docs/rise-and-fall.gif and embed below. -->

![rise and fall of empires — replay (placeholder)](docs/rise-and-fall.gif)

### A real chronicle (excerpt, `--seed 42 --years 200`)

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
share this world:  worldsim --seed 42 --years 200
```

Nothing above is hand-written prose stored in the save. Each line is *derived* from a structured
event and its named factors — the same factors that drove the decision. Ask the machine *why*
a power fell and it walks the causal graph back to the root:

```text
$ worldsim --seed 42 --years 200 --why 30
Why did Lysetor suffer? — Year 26: Lysetor collapsed, losing much of its realm — a turning point.
  └─ Year 19: Elytor defeated Lysetor and annexed the western forests. [Zufall -0.11, Militaervorteil -0.03]
      └─ Year 19: Lysetor declared a war of faith on Elytor, driven by Aggression (+0.82), Vorsicht (-0.44), Glaubensgraben (+0.40).
```

---

## Install

Python **3.11+**. The simulation **core** has *zero* runtime dependencies — plain standard
library. Colour, the map, the live dashboard and replay live in the presentation layer and
pull in `rich`, `numpy` and `opensimplex` only when you use them.

```bash
# clone, then from the repo root:
python -m venv .venv && source .venv/bin/activate

# headless core only (no dependencies):
pip install .

# with the presentation layer (watch / replay / map / stats):
pip install ".[presentation]"

# for development (tests + linter):
pip install ".[dev]"
```

## Run

`worldsim` (or `python -m worldsim`) simulates a world and shows it. **Save = Seed**: a run is
fully determined by `(seed, years, config_version)`, so sharing the seed shares the world.

```bash
worldsim --seed 42 --years 200                 # headless text chronicle (default)
worldsim --seed 42 --years 200 --mode watch    # live dashboard while history unfolds
worldsim --seed 42 --years 200 --mode replay   # the whole history, fast-forwarded from the log
```

| Option | Meaning |
| --- | --- |
| `--seed N` | master seed (the shareable identity of a world) |
| `--years N` | years to simulate (default `200`) |
| `--mode {headless,watch,replay}` | text chronicle · live dashboard · time-lapse replay |
| `--stats` | end-of-run population/power/activity sparklines + summary |
| `--map` | procedural biome & territory map |
| `--why ENTITY` / `--why-event ID` | walk the causal graph back from a setback |
| `--explain N` | factor breakdown of the first `N` wars (the reasoning is the numbers) |

`watch` and `replay` need a real terminal to animate (they fall back to snapshot frames when
piped); `headless` prints plain text and works anywhere, dependency-free.

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

The headless core is tested without any presentation dependency; a dedicated test asserts that
importing the core pulls in no `rich`/`numpy`/`opensimplex`, keeping the layering honest.
