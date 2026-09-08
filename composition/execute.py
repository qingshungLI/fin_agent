"""组合执行管线：读取冻结的目标持仓，使用原本地 RQAlpha 公司行为账本逐日 T+1 执行。"""

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from composition.replay import extend_execution_calendar, ROOT

from backtest.execute_research_target import run_target


def main() -> int:
    """解析目标与输出目录；无额外择优或再排序，返回实际执行退出码。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target = pd.read_parquet(args.target)
    with duckdb.connect(str(ROOT / "artifacts/backtest/exploration.duckdb"), read_only=True) as connection:
        calendar = pd.DatetimeIndex(connection.execute(
            "SELECT DISTINCT date FROM v_trading_calendar WHERE date <= '2022-06-30' ORDER BY date"
        ).fetchdf()["date"])
    target = extend_execution_calendar(target, calendar)
    # 仅从引擎订阅列表移除全程零持仓证券，不改变任何目标权重与调仓日。
    target = target.loc[:,target.gt(0).any()]
    if target.empty:
        raise ValueError("组合全程空仓，无实际执行对象")
    print(run_target(target, args.output, holding_days=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())