from __future__ import annotations

import os
from pathlib import Path

import rqalpha


def init(context):
    context.started = True


def handle_bar(context, bar_dict):
    pass


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    bundle_path = project_root / "data"
    rqdatac_uri = os.environ.get("RQDATAC2_CONF", "")

    config = {
        "base": {
            "start_date": "2024-01-02",
            "end_date": "2024-01-05",
            "frequency": "1d",
            "accounts": {"stock": 100000},
            "data_bundle_path": str(bundle_path),
            "capital_gain_tax_rate": 0,
        },
        "extra": {
            "log_level": "error",
        },
        "mod": {"sys_analyser": {"enabled": True}},
    }

    print(f"rqalpha={rqalpha.__version__}")
    print(f"bundle_path={bundle_path}")
    try:
        rqalpha.run_func(config=config, init=init, handle_bar=handle_bar)
    except Exception as exc:
        print(f"backtest_status=blocked_by_bundle:{type(exc).__name__}:{exc}")
        return 3

    print("backtest_status=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
