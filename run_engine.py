"""Server-only durable research command."""
import argparse
from datetime import UTC, datetime
from pathlib import Path

from engine.config import ResearchConfig
from engine.pipeline import run_research


def main() -> int:
    """Run a frozen A-segment batch from CLI arguments.

    Returns:
        int: Zero for completion, two for a blocked run; assumes local data paths.
    """
    p = argparse.ArgumentParser()
    p.add_argument("--data-root", type=Path, default=Path("data"))
    p.add_argument("--output-root", type=Path, default=Path("artifacts"))
    p.add_argument("--run-id", default=None)
    p.add_argument("--start", default="2016-07-01")
    p.add_argument("--end", default="2022-06-30")
    p.add_argument("--max-symbols", type=int, default=0)
    p.add_argument("--max-structures", type=int, default=4)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--nuisance-backend", choices=["cpu", "cuda"], default="cpu")
    p.add_argument("--discovery-splits", type=int, default=None)
    p.add_argument("--provider", choices=["manual", "llm", "hybrid"], default="manual")
    p.add_argument("--industry-policy", choices=["strict", "quarantine"], default="strict")
    p.add_argument("--industry-source", choices=["exact_intervals", "rqdata_daily"], default="exact_intervals")
    p.add_argument("--auction-policy", choices=["strict", "quarantine"], default=None)
    p.add_argument("--data-profile", choices=["full", "daily"], default="full")
    p.add_argument("--no-auto-evolve", action="store_true")
    p.add_argument("--engineering", action="store_true")
    p.add_argument("--fast", action="store_true", help="Exploratory evolution: 19 diagnostic shuffles; no IAAFT or Bayesian sampling")
    p.add_argument("--discovery", action="store_true")
    p.add_argument("--bayes", action="store_true")
    p.add_argument("--full-grid", action="store_true",
                   help="Budget initial components and prioritize heterogeneous evolution")
    p.add_argument("--llm-max-calls", type=int, default=None)
    p.add_argument("--evolution-budget", type=int, default=140)
    p.add_argument("--continue-from", default=None)
    args = p.parse_args()
    if args.fast and args.engineering:
        p.error("choose either --fast or --engineering")
    if args.full_grid:
        from engine.cycle import initial_tasks
        args.provider = "llm"
        if args.evolution_budget < 0:
            p.error("evolution budget must be nonnegative")
        args.max_structures = len(initial_tasks()) + (0 if args.no_auto_evolve else args.evolution_budget)
        if not args.no_auto_evolve:
            args.discovery = args.bayes = True
        print(f"Full grid: {len(initial_tasks())} cells; total attempt budget {args.max_structures}",
              flush=True)
    if args.fast:
        args.discovery = True
        args.bayes = False
    args.llm_max_calls = args.llm_max_calls or (min(10000, 20 * args.max_structures) if args.full_grid else 200)
    if args.provider == "manual" and args.max_structures > 4:
        p.error("manual supports only four seeds; use --full-grid or --provider llm/hybrid")
    config = ResearchConfig(start=args.start, end=args.end, max_symbols=args.max_symbols,
                            max_structures=args.max_structures, workers=args.workers,
                            provider=args.provider, llm_max_calls=args.llm_max_calls,
                            nuisance_backend=args.nuisance_backend,
                            continue_from=args.continue_from,
                            industry_policy=args.industry_policy,
                            industry_source=args.industry_source, auction_policy=args.auction_policy,
                            data_profile=args.data_profile, auto_evolve=not args.no_auto_evolve,
                            mode="fast" if args.fast else "engineering" if args.engineering else "formal",
                            n_boot=100 if args.fast else 200 if args.engineering else 1000,
                            n_placebo=19 if args.fast else 150 if args.engineering else 500,
                            n_trees=30 if args.fast else 50 if args.engineering else 500,
                            n_splits=args.discovery_splits or (2 if args.fast else 5 if args.engineering else 20))
    run_id = args.run_id or datetime.now(UTC).strftime("run-%Y%m%dT%H%M%SZ")
    try:
        run_research(config, run_id, args.data_root, args.output_root, args.discovery, args.bayes)
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports a failed research run
        print(f"Research run blocked: {type(exc).__name__}: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
