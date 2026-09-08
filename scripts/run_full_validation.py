"""完整验证管线：依次运行统计校准与研究记忆恢复，记录退出码、代码指纹和适用范围。

验证只用合成数据；每个子进程独立日志。正式确认校准仅由主检验、必要断言和 ICM 三套
真实报告共同产生，记忆恢复另行记录，不把合成验证写成实盘因子通过。
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from engine.audit import now, write_json
from engine.cache import file_hash
from engine.pipeline import runtime_identity

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "artifacts" / "validation"


def collect_calibration(folder: Path, identity: dict[str, str]) -> dict[str, Any]:
    """汇总同代码下的三项推断校准。

    Args:
        folder: 子验证报告目录。
        identity: 启动时全引擎代码指纹。
    Returns:
        dict: 带输入哈希的校准结果；缺失、失败、代码改变均不可通过。
    """
    names = ("statistics-batch-revised.json", "inference-suite.json", "necessary-assertion-suite.json")
    checks = []
    for name in names:
        path = folder / name
        if not path.exists():
            checks.append({"name": name, "passed": False, "reason": "missing report"})
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        code = report.get("code_sha256", {})
        matched = bool(code) and all(identity.get(k) == v for k, v in code.items())
        checks.append({"name": name, "passed": bool(report.get("passed")) and matched,
                       "hash": file_hash(path), "code_matches": matched,
                       "scope": report.get("scope")})
    current = {p.name: file_hash(p) for p in (ROOT / "engine").glob("*.py")}
    return {"passed": all(c["passed"] for c in checks) and current == identity,
            "checks": checks, "code_sha256": identity, "environment": runtime_identity(),
            "uses_market_data": False, "created_at": now(),
            "scope": "Specified synthetic main/Holm, necessary-endpoint and nonlinear ICM cases only",
            "limitations": "Does not calibrate assertion e-process p0, temporal surrogates or certify data quality"}


def main() -> int:
    """执行完整验证任务；无参数，返回 0 表示所有任务通过，2 表示存在失败。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    FOLDER.mkdir(parents=True, exist_ok=True)
    identity = {p.name: file_hash(p) for p in (ROOT / "engine").glob("*.py")}
    jobs = [
        ("main-statistics", ["scripts/validate-statistics.py"]),
        ("necessary-assertions", ["scripts/validate_necessary_assertions.py"]),
        ("nonlinear-icm", ["scripts/validate_inference_suite.py", "--trials", "600"]),
        ("memory-recovery", ["scripts/validate_memory_recovery.py"]),
        ("memory-interactions", ["scripts/validate_stage_c_recovery.py"]),
    ]
    state: dict[str, Any] = {"status": "RUNNING", "started_at": now(), "steps": [],
                             "code_sha256": identity, "environment": runtime_identity()}
    previous_path = FOLDER / "full-validation.json"
    previous = json.loads(previous_path.read_text(encoding="utf-8")) if args.resume and previous_path.exists() else {}
    if previous and (previous.get("code_sha256") != identity or previous.get("environment") != state["environment"]):
        raise ValueError("Validation resume requires unchanged inference code and package versions")
    reports = {"main-statistics": "statistics-batch-revised.json", "necessary-assertions": "necessary-assertion-suite.json", "nonlinear-icm": "inference-suite.json"}
    state["execution"] = {"pytensor_flags": os.environ.get("PYTENSOR_FLAGS", ""), "resumed": bool(previous)}
    if previous:
        write_json(FOLDER / "validation-before-resume.json", previous)
    env = dict(os.environ, PYTHONUTF8="1", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    for name, arguments in jobs:
        previous_step = next((step for step in previous.get("steps", []) if step["name"] == name), {})
        if name in reports and previous_step.get("status") == "PASSED":
            report_path = FOLDER / reports[name]
            report = json.loads(report_path.read_text(encoding="utf-8"))
            code = report.get("code_sha256", {})
            if not report.get("passed") or not code or any(identity.get(k) != v for k, v in code.items()):
                raise ValueError(f"Prior validation report is not reusable: {name}")
            state["steps"].append({**previous_step, "reused": True, "report_hash": file_hash(report_path)})
            write_json(FOLDER / "full-validation.json", state)
            print(f"{name}: verified previous result reused", flush=True)
            continue
        entry = {"name": name, "status": "RUNNING", "started_at": now(), "command": arguments}
        state["steps"].append(entry)
        write_json(FOLDER / "full-validation.json", state)
        print(f"{name}: started", flush=True)
        with (FOLDER / (name + ".log")).open("a" if previous else "w", encoding="utf-8") as log:
            if previous:
                log.write("\n--- Resumed with recorded compiler configuration ---\n")
                log.flush()
            result = subprocess.run([sys.executable, "-u", *arguments], cwd=ROOT, env=env,
                                    stdout=log, stderr=subprocess.STDOUT, check=False)
        entry.update(status="PASSED" if result.returncode == 0 else "FAILED",
                     exit_code=result.returncode, finished_at=now())
        write_json(FOLDER / "full-validation.json", state)
        if name == "nonlinear-icm":
            write_json(FOLDER / "calibration.json", collect_calibration(FOLDER, identity))
        print(f"{name}: {entry['status']}", flush=True)
    calibration = collect_calibration(FOLDER, identity)
    write_json(FOLDER / "calibration.json", calibration)
    passed = all(s["status"] == "PASSED" for s in state["steps"]) and calibration["passed"]
    state.update(status="PASSED" if passed else "FAILED", finished_at=now())
    write_json(FOLDER / "full-validation.json", state)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())