"""Server-only durable research command."""
import argparse
from datetime import UTC, datetime
from pathlib import Path

from engine.config import ResearchConfig
from engine.pipeline import run_research


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-root", type=Path, default=Path("data"))
    p.add_argument("--output-root", type=Path, default=Path("artifacts"))
    p.add_argument("--run-id", default=None)
    p.add_argument("--start", default="2016-07-01")
    p.add_argument("--end", default="2022-06-30")
    p.add_argument("--max-symbols", type=int, default=0)
    p.add_argument("--max-structures", type=int, default=4)
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--provider", choices=["manual", "llm", "hybrid"], default="manual")
    p.add_argument("--industry-policy", choices=["strict", "quarantine"], default="strict")
    p.add_argument("--industry-source", choices=["exact_intervals", "rqdata_daily"], default="exact_intervals")
    p.add_argument("--auction-policy", choices=["strict", "quarantine"], default=None)
    p.add_argument("--engineering", action="store_true")
    p.add_argument("--discovery", action="store_true")
    p.add_argument("--bayes", action="store_true")
    args = p.parse_args()
    config = ResearchConfig(start=args.start, end=args.end, max_symbols=args.max_symbols,
                            max_structures=args.max_structures, workers=args.workers,
                            provider=args.provider, industry_policy=args.industry_policy,
                            industry_source=args.industry_source, auction_policy=args.auction_policy,
                            mode="engineering" if args.engineering else "formal",
                            n_boot=100 if args.engineering else 1000,
                            n_placebo=99 if args.engineering else 500,
                            n_trees=30 if args.engineering else 500,
                            n_splits=2 if args.engineering else 20)
    run_id = args.run_id or datetime.now(UTC).strftime("run-%Y%m%dT%H%M%SZ")
    try:
        run_research(config, run_id, args.data_root, args.output_root, args.discovery, args.bayes)
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports a failed research run
        print(f"Research run blocked: {type(exc).__name__}: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
