"""组合执行重放：核验已冻结持仓，在原 A 日历上追加执行/清仓日，独立保存每次执行结果。

修复执行适配器后重放不得覆盖旧失败证据，也不改变持仓选择。三种组合顺序执行，某种
组合拒单不会阻止其他组合生成执行报告；失败仍保留，不改成可成交。
"""
import argparse
import json
from pathlib import Path

import pandas as pd

from engine.audit import now, write_json
from engine.cache import file_hash
from backtest.execute_research_target import run_target

ROOT = Path(__file__).resolve().parents[1]


def extend_execution_calendar(target: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """追加两个真实交易日以执行最后信号和清仓；输入目标/日历，返回补零的执行矩阵。"""
    if not target.index.isin(calendar).all():
        raise ValueError("组合信号日期不在执行日历")
    tail = calendar[calendar > target.index[-1]][:2]
    if len(tail) != 2 or tail[-1] > pd.Timestamp("2022-06-30"):
        raise ValueError("A 段剩余日历不足以完成最后目标执行和清仓")
    return target.reindex(target.index.append(tail), fill_value=0.)


def main() -> int:
    """Replay frozen composition targets with local market data and write an audit report.

    Returns:
        int: Zero when every composition execution completes; otherwise two.
    Raises:
        ModuleNotFoundError: If the optional DuckDB/RQAlpha execution stack is unavailable.
    """
    try:
        import duckdb
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "DuckDB is required for composition replay; install the project backtest extra"
        ) from exc
    """从命令行选择组合和新执行 ID；返回 0 仅当三种目标都完成真实执行。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--execution-id", required=True)
    args = parser.parse_args()
    import re
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value) for value in (args.batch_id,args.execution_id)):
        raise ValueError("执行批次 ID 非法")
    source = ROOT / "artifacts/compositions" / args.batch_id
    frozen = json.loads((source / "frozen.json").read_text(encoding="utf-8"))
    hashes = json.loads((source / "artifact-hashes.json").read_text(encoding="utf-8"))
    output = ROOT / "artifacts/composition-executions" / args.execution_id
    output.mkdir(parents=True, exist_ok=False)
    warehouse = ROOT / "artifacts/backtest/exploration.duckdb"
    with duckdb.connect(str(warehouse), read_only=True) as connection:
        calendar = pd.DatetimeIndex(connection.execute("SELECT DISTINCT date FROM v_trading_calendar WHERE date <= '2022-06-30' ORDER BY date").fetchdf()["date"])
    report = {"execution_id":args.execution_id, "batch_id":args.batch_id, "status":"RUNNING", "created_at":now(),
        "formal":False, "source_run":frozen["source_run"], "variants":{}, "rebalance_days":1,
        "adapter_hash":file_hash(ROOT / "backtest/execute_research_target.py"),
        "replay_hash":file_hash(Path(__file__)), "terminal_rule":"two reserved A trading days: final signal execution then zero-target liquidation"}
    write_json(output / "report.json", report)
    for name in ("parallel", "conflict_cash", "consensus"):
        path = source / name / "target.parquet"
        key = str(path.relative_to(source))
        if hashes.get(key) != file_hash(path):
            raise ValueError("冻结组合目标已被修改")
        target = pd.read_parquet(path)
        target = extend_execution_calendar(target, calendar)
        target = target.loc[:,target.gt(0).any()]
        report["variants"][name] = {"status":"RUNNING", "target_hash":hashes[key]}
        write_json(output / "report.json", report)
        print(f"execution {name}: {len(target)} dates, {len(target.columns)} traded-universe securities", flush=True)
        try:
            result = run_target(target, output / name, holding_days=1)
            report["variants"][name].update(status="COMPLETED", result=result)
        except Exception as exc:
            report["variants"][name].update(status="FAILED", reason=str(exc))
        write_json(output / "report.json", report)
        print(f"execution {name}: {report['variants'][name]['status']}", flush=True)
    success = all(item["status"] == "COMPLETED" for item in report["variants"].values())
    report.update(status="COMPLETED" if success else "COMPLETED_WITH_FAILURES", finished_at=now())
    write_json(output / "report.json", report)
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())