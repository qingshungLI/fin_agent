"""完整批次收尾管线：等待研究与验证，生成报告，检查 B/H 资格并记录执行结果。

A 和合成验证可独立运行。真实确认只接收当前批次的新结构；继承记录不算独立重复。
工程执行选择首个完成结构、固定权重规则及完整 A 段，不按收益择优或替换失败目标。
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from engine.audit import now, write_json
from engine.config import ResearchConfig
from engine.confirmation import confirm_once
from server_jobs import process_alive
from scripts.summarize_research import summarize

ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict[str, Any]:
    """读取原子 JSON 产物；参数为已存在路径，返回对象，损坏时明确报错。"""
    return json.loads(path.read_text(encoding="utf-8"))


def finish(run_id: str, research_pid: int, validation_pid: int) -> int:
    """等待已启动任务并驱动后续阶段。

    Args:
        run_id: 当前研究批次 ID。
        research_pid: 研究启动进程 PID。
        validation_pid: 验证启动进程 PID。
    Returns:
        int: 全部适用阶段通过为 0；存在失败或正式晋级阻塞为 2。
    """
    if not run_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in run_id):
        raise ValueError("Invalid run ID")
    folder = ROOT / "artifacts" / run_id
    output = ROOT / "artifacts" / (run_id + "-pipeline")
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"run_id": run_id, "status": "RUNNING", "started_at": now(),
                              "stages": {}, "B_read": False, "H_read": False}
    while process_alive(research_pid) or process_alive(validation_pid):
        checkpoint = folder / "checkpoint.json"
        if checkpoint.exists():
            state = read_json(checkpoint)
            report["stages"]["research"] = {"status": state["status"],
                "attempts": state.get("attempts", 0), "new_measured": len(state["completed"]),
                "budget": state["identity"]["config"]["max_structures"]}
        validation = ROOT / "artifacts/validation/full-validation.json"
        if validation.exists():
            record = read_json(validation)
            report["stages"]["validation"] = {"status": record["status"], "steps": record["steps"]}
        write_json(output / "pipeline.json", report)
        time.sleep(15)
    state = read_json(folder / "checkpoint.json")
    (output / "research-summary.md").write_text(summarize(folder), encoding="utf-8")
    report["stages"].setdefault("research", {})["status"] = state["status"]
    validation = read_json(ROOT / "artifacts/validation/full-validation.json")
    report["stages"]["validation"] = {"status": validation["status"], "steps": validation["steps"]}
    eligible = state.get("confirmation", {}).get("eligible_ids", [])
    calibration = read_json(ROOT / "artifacts/validation/calibration.json")
    blocked = []
    if state["status"] != "COMPLETED":
        blocked.append("A research did not complete")
    if not eligible:
        blocked.append("No newly measured structure is eligible for confirmation")
    if not calibration.get("passed"):
        blocked.append("Statistical calibration did not pass")
    if blocked:
        report["stages"]["B"] = {"status": "BLOCKED", "reasons": blocked}
        report["stages"]["H"] = {"status": "BLOCKED", "reason": "Requires B-confirmed structures"}
        report["stages"]["formal_portfolio"] = {"status": "BLOCKED", "reason": "No independent confirmed portfolio"}
    else:
        config = ResearchConfig.model_validate(state["identity"]["config"])
        try:
            result_b = confirm_once(config, run_id, eligible, data_root=ROOT / "data")
            report["B_read"] = True
            report["stages"]["B"] = {"status": "COMPLETED", "results": result_b}
            passing = [r["id"] for r in result_b if r["formal"]]
            if passing:
                result_h = confirm_once(config, run_id, passing, data_root=ROOT / "data", segment="H")
                report["H_read"] = True
                report["stages"]["H"] = {"status": "COMPLETED", "results": result_h}
                report["stages"]["formal_portfolio"] = {"status": "PENDING_REVIEW",
                    "confirmed_ids": [r["id"] for r in result_h if r["formal"]]}
            else:
                report["stages"]["H"] = {"status": "BLOCKED", "reason": "No B PASS"}
        except Exception as exc:
            report["stages"]["confirmation"] = {"status": "FAILED", "reason": str(exc)}
    # Audit access facts also survive confirmation exceptions.
    from engine.audit import AuditStore
    access = AuditStore(ROOT / "artifacts").verify()["access"]
    report["audit_access"] = access
    report["B_read"] = any(a["segment"] == "B" for a in access)
    report["H_read"] = any(a["segment"] == "H" for a in access)
    if state["completed"]:
        sid = state["completed"][0]
        factor = folder / sid / "research-factor.parquet"
        execution_folder = output / "research-execution"
        command = [sys.executable, "-u", "backtest/execute_research_target.py", "--factor", str(factor),
                   "--start", state["identity"]["config"]["start"],
                   "--end", state["identity"]["config"]["end"], "--output", str(execution_folder)]
        report["stages"]["research_execution"] = {"status": "RUNNING", "structure": sid,
                                                   "scope": "Full A-only fixed first-structure replay"}
        write_json(output / "pipeline.json", report)
        with (output / "research-execution.log").open("w", encoding="utf-8") as log:
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=False)
        report["stages"]["research_execution"].update(
            status="COMPLETED" if result.returncode == 0 else "FAILED", exit_code=result.returncode)
    else:
        report["stages"]["research_execution"] = {"status": "BLOCKED", "reason": "No measured factor"}
    statuses = [s["status"] for s in report["stages"].values()]
    report["status"] = "COMPLETED" if all(s in {"COMPLETED", "PASSED"} for s in statuses) else "COMPLETED_WITH_BLOCKERS"
    report["finished_at"] = now()
    write_json(output / "pipeline.json", report)
    print(json.dumps({"status": report["status"], "report": str(output / "pipeline.json")}), flush=True)
    return 0 if report["status"] == "COMPLETED" else 2


def main() -> int:
    """解析当前批次及进程参数；返回完整收尾状态码，不启动重复研究。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--research-pid", type=int, required=True)
    parser.add_argument("--validation-pid", type=int, required=True)
    args = parser.parse_args()
    return finish(args.run_id, args.research_pid, args.validation_pid)


if __name__ == "__main__":
    raise SystemExit(main())