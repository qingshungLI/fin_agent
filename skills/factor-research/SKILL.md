---
name: aurora-factor-research
description: Run AURORA RSI Alpha Research Harness on user-owned daily CSV, Parquet, or pandas panels with bounded DSL expressions, falsification, evolution, audit artifacts, and reproducible reports.
---

# AURORA Factor Research Skill

RSI means **Recursive Self-Improvement**. The model proposes and critiques research candidates; the deterministic harness freezes inputs, measures candidates, records evidence, and uses only training evidence to schedule the next mutation.

## Install

```bash
git clone https://github.com/qingshungLI/fin_agent.git
cd fin_agent
pip install -e .
```

Optional local backtest support:

```bash
pip install -e ".[backtest]"
pip install -e backtest/rqalpha_mod_local_rqdata
```

## Data contract

Provide a daily panel with required columns:

- `date`: trading date
- `symbol`: instrument identifier
- `open`, `close`: adjusted prices available at the decision time

Optional fields are validated and never silently imputed. Keep output directories new and immutable.

## SDK entrypoint

```python
from research_sdk import CellSpec, ExperimentSpec, dataset_summary, run_experiment

summary = dataset_summary(panel)
report = run_experiment(
    panel,
    ExperimentSpec(
        name="short_reversal",
        cells=[CellSpec(
            name="short_reversal",
            mechanism="short-term price shock reverts",
            expression="neg(ts_z(ret_1d, 20))",
            horizon=5,
        )],
        profile="fast",
        evolve=True,
    ),
    "artifacts/my-run",
)
```

The portable SDK uses deterministic training-only mutations and records `llm_used: false`; DeepSeek-driven hypothesis generation belongs to the full research engine.

Expressions use the bounded factor DSL. Do not use `eval` or arbitrary Python. Inspect `report.json`, candidate lineage, validation intervals, missing-return warnings, double-cost return, and the final confirmation state before using any factor.

## API entrypoints

The local dashboard exposes:

- `POST /api/studio/datasets`
- `POST /api/studio/experiments`
- `GET /api/studio/experiments/{id}`
- `GET /api/control/skill`
- `GET /api/control/skill-manifest`

The control console also supports pause, resume, stop, and checkpoint restart through `POST /api/control/runs/{run_id}/action`.

## Research rules

1. Select candidates on training data only.
2. Preserve parent IDs and mutation operators for every evolved structure.
3. Treat fast and exploratory results as non-formal until independent confirmation.
4. Preserve missing returns, coverage failures, placebo failures, and rejected priors in the report.
5. Never claim a formal PASS from positive IC or descriptive return alone.
