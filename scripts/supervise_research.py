"""研究守护管线：等待现有进程结束，仅对有限的 DeepSeek 临时响应错误恢复原检查点。

不重复启动活跃研究，不改变冻结参数，不重算已提交结构。认证、额度、代码指纹和数据
错误均直接停止；每次守护最多自动恢复三次，所有恢复追加日志和独立事件记录。
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from engine.audit import now, write_json
from server_jobs import process_alive

ROOT = Path(__file__).resolve().parents[1]


def retryable(failure: dict[str, Any]) -> bool:
    """判定是否为临时模型响应错误；输入失败产物，返回布尔值，不接受授权或数据错误。"""
    return failure.get("type") == "RuntimeError" and bool(re.fullmatch(
        r"DeepSeek request failed after bounded retries: (ValueError|KeyError|ReadTimeout|ConnectTimeout|ConnectError|ReadError|RemoteProtocolError|HTTP (429|5\d\d))",
        str(failure.get("error", ""))))


def main() -> int:
    """解析批次和现有 PID 并有界恢复；返回研究退出码，状态与恢复证据独立落盘。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--existing-pid", type=int, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", args.run_id) or args.existing_pid <= 0:
        raise ValueError("Invalid run or process ID")
    folder = ROOT / "artifacts" / args.run_id
    record_path = ROOT / "artifacts" / (args.run_id + "-supervisor.json")
    log_path = ROOT / "artifacts" / (args.run_id + ".stdout.log")
    initial = json.loads((folder / "checkpoint.json").read_text(encoding="utf-8"))
    record: dict[str, Any] = {"run_id": args.run_id, "status": "WATCHING", "started_at": now(),
                              "existing_pid": args.existing_pid, "max_resumes": 3, "resumes": []}
    write_json(record_path, record)
    while process_alive(args.existing_pid):
        time.sleep(10)
    for index in range(4):
        state = json.loads((folder / "checkpoint.json").read_text(encoding="utf-8"))
        if state["identity"] != initial["identity"]:
            raise ValueError("Checkpoint identity changed during supervision")
        if state["status"] == "COMPLETED":
            record.update(status="COMPLETED", finished_at=now())
            write_json(record_path, record)
            return 0
        failure = json.loads((folder / "failure.json").read_text(encoding="utf-8"))
        if not retryable(failure) or index >= 3:
            record.update(status="STOPPED", reason=failure.get("error"), finished_at=now())
            write_json(record_path, record)
            return 2
        calls = len(re.findall(r"^llm \w+: request \d+/\d+$", log_path.read_text(encoding="utf-8"), re.MULTILINE))
        if calls >= state["identity"]["config"]["llm_max_calls"]:
            record.update(status="STOPPED", reason="Cumulative logical request budget reached", finished_at=now())
            write_json(record_path, record)
            return 2
        entry = {"index": index+1, "at": now(), "reason": failure["error"],
                 "already_measured": len(state["completed"]), "logical_requests": calls}
        record["resumes"].append(entry)
        record["status"] = "RESUMING"
        write_json(record_path, record)
        time.sleep(10)
        command = [sys.executable, "-u", "-c",
            "import json,sys; from pathlib import Path; from engine.config import ResearchConfig; "
            "from engine.pipeline import run_research; "
            "s=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')); "
            "run_research(ResearchConfig.model_validate(s['identity']['config']),s['run_id'],"
            "Path(s['identity']['data_root']),Path(sys.argv[1]).parent.parent,"
            "s['identity']['discovery'],s['identity']['bayes'])", str(folder / "checkpoint.json")]
        with log_path.open("a", encoding="utf-8") as log, (ROOT / "artifacts" / (args.run_id + ".stderr.log")).open("a", encoding="utf-8") as errors:
            log.write(f"\nResearch supervisor: resume {index+1}/3; completed={len(state['completed'])}\n")
            log.flush()
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=errors, check=False)
        entry["exit_code"] = result.returncode
        write_json(record_path, record)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())