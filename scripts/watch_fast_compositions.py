"""Fast 后处理管线：等待固定完成数量，冻结组合并启动回放，单结构研究不等待组合任务。

固定在 4、8、16 个已提交结构时生成快照，成分按完成顺序选择，分别使用前 4、8、16 个。
每个快照只运行一次；失败记录保留，既不覆盖旧目标也不将执行失败改成通过。
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from engine.audit import now, write_json
from server_jobs import process_alive

ROOT = Path(__file__).resolve().parents[1]


def committed_count(state: dict) -> int:
    """统计已完成后处理的结构；输入检查点，返回可冻结组合的数量。"""
    return sum(sid != state.get("pending_postprocess") for sid in state["completed"])


def main() -> int:
    """接收源批次及守护 PID，顺序执行固定组合节点；返回零不代表策略通过。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--research-pid", type=int, required=True)
    args = parser.parse_args()
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", args.run_id) or args.research_pid <= 0:
        raise ValueError("Invalid research run or PID")
    path = ROOT / "artifacts" / args.run_id / "checkpoint.json"
    report_path = ROOT / "artifacts" / f"{args.run_id}-composition-watch.json"
    report = {"run_id": args.run_id, "status": "WATCHING", "created_at": now(),
              "milestones": [4, 8, 16], "batches": {}, "formal": False}
    write_json(report_path, report)
    while True:
        state = json.loads(path.read_text(encoding="utf-8"))
        count = committed_count(state)
        for milestone in report["milestones"]:
            batch_id = f"{args.run_id}-m{milestone}"
            if count < milestone or batch_id in report["batches"]:
                continue
            report["batches"][batch_id] = {"status": "RUNNING", "at_count": count}
            write_json(report_path, report)
            command = [sys.executable, "-u", "-m", "composition.runner", "--source-run", args.run_id,
                       "--batch-id", batch_id, "--max-sources", str(milestone), "--execute"]
            with (ROOT / "artifacts" / f"{batch_id}.log").open("w", encoding="utf-8") as log:
                result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=False)
            artifact = ROOT / "artifacts/compositions" / batch_id / "report.json"
            summary = json.loads(artifact.read_text(encoding="utf-8")) if artifact.exists() else {}
            report["batches"][batch_id].update(
                status=summary.get("status", "FAILED"), exit_code=result.returncode,
                execution={name: item.get("execution", {}) for name, item in summary.get("variants", {}).items()},
            )
            write_json(report_path, report)
        if len(report["batches"]) == len(report["milestones"]) or not process_alive(args.research_pid):
            report.update(status="FINISHED" if len(report["batches"]) == 3 else "SOURCE_STOPPED", finished_at=now())
            write_json(report_path, report)
            return 0
        time.sleep(15)


if __name__ == "__main__":
    raise SystemExit(main())