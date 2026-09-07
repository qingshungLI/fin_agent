"""研究主入口：执行验证、A 段最小研究批次、审计与 JSON 产物。

默认严格模式会在源数据违反 M1 契约时退出；engineering 模式仅用于开发诊断，不能生成正式 PASS。
"""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import traceback

from engine.audit import AuditStore, write_json
from engine.catalog import build_map, seed_structure, register_cell, freeze_cuts
from engine.config import ResearchConfig
from engine.data import build_panel
from engine.metrics import measure_panel, power_budget
from engine.blades import run_blades


def main() -> int:
    """运行一个可审计研究批次；返回进程码，错误写入 failure.json 后退出非零。"""
    parser = argparse.ArgumentParser(description="AutoAlpha Harness")
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--output-root", type=Path, default=Path("artifacts"))
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default="2020-12-31")
    parser.add_argument("--max-symbols", type=int, default=0)
    parser.add_argument("--engineering", action="store_true")
    args = parser.parse_args()
    run_id = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ")
    output = args.output_root
    try:
        config = ResearchConfig(start=args.start, end=args.end, max_symbols=args.max_symbols,
                                mode="engineering" if args.engineering else "formal",
                                n_boot=100 if args.engineering else 1000,
                                n_placebo=99 if args.engineering else 500,
                                n_trees=30 if args.engineering else 500,
                                n_splits=2 if args.engineering else 20, max_structures=4)
        panel = build_panel(args.data_root, config)
        overview = {"run_id": run_id, "status": "MEASURED", "config": config.model_dump(),
                    "report": panel.report, "dates": len(panel.dates),
                    "symbols": len(panel.fields["close"].columns), "map": build_map()}
        structure_rows, library = [], []
        first = seed_structure(0, run_id)
        # 注册表达式前冻结切点；合法性检查不触碰未来标签。
        cuts = freeze_cuts(panel.fields, ["ret_5d", "turnover_today", "market_cap", "avg_trade_size"], config.seed)
        for expression in first.operational:
            register_cell(expression, panel.fields, cuts)
        bets = {assertion.id: {"probability": assertion.prior_p, "created_at": datetime.now(timezone.utc).isoformat()}
                for assertion in first.assertions}
        store = AuditStore(output)
        frozen_hash = store.freeze(run_id, first.model_dump(), bets)
        measured, stored = measure_panel(first, panel, config, cuts)
        blades = run_blades(first, panel, measured, stored, library, config)
        structure_rows.append({"id": first.id, "name": first.name, "family": first.family, "form": first.form,
                               "hash": frozen_hash, "measurement": measured, "blades": blades,
                               "verdict": blades["verdict"], "formal": False})
        overview["status"] = "RESEARCH_ONLY"
        overview["power"] = power_budget(next((row["n_eff"] for row in measured["curves"]
                                                if row["expression"] == 1 and row["horizon"] == 5), 1), 0.65, 0.05)
        overview["audit"] = store.verify()
        write_json(output / "overview.json", overview)
        write_json(output / "structures.json", structure_rows)
        return 0
    except Exception as exc:  # 保留错误证据，禁止静默降级。
        output.mkdir(parents=True, exist_ok=True)
        write_json(output / "failure.json", {"run_id": run_id, "error": str(exc),
                                              "type": type(exc).__name__, "traceback": traceback.format_exc()})
        print(f"研究批次阻断: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
