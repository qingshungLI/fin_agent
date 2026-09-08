"""恢复管线：核验失败批次与冻结证据，重新请求无效 reconciler 响应，再恢复原检查点。

只修复可再生成的模型响应缓存，保留原响应和重试身份；不修改冻结引擎、研究配置、
断言或测量。只有真实模型返回完整且正确的分类才替换缓存，失败不会伪造分类。
研究在独立进程中继续，最多恢复三次后续临时失败，避免无界重试和内存残留。
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from engine.audit import AuditStore, digest, now, write_json
from engine.cache import file_hash
from engine.llm import DeepSeek
from scripts.supervise_research import retryable

ROOT = Path(__file__).resolve().parents[1]


def expected_groups(assertions: list[dict[str, Any]]) -> dict[str, list[str]]:
    """由 assertions 构造校验基准，返回三组 ID；未知状态或重复 ID 明确报错。"""
    groups: dict[str, list[str]] = {"aligned": [], "divergent": [], "unresolved": []}
    names = {"hold": "aligned", "violated": "divergent", "untested": "unresolved"}
    seen = set()
    if not assertions:
        raise ValueError("Empty assertion set")
    for assertion in assertions:
        sid, state = assertion["id"], assertion["state"]
        if not isinstance(sid, str) or sid in seen or state not in names:
            raise ValueError("Invalid deterministic assertions")
        seen.add(sid)
        groups[names[state]].append(sid)
    return {key: sorted(value) for key, value in groups.items()}


def matches_groups(response: Any, expected: dict[str, list[str]]) -> bool:
    """检查 response 是否精确覆盖 expected，返回布尔；拒绝漏项、重复、错组和额外字段。"""
    return (isinstance(response, dict) and response.keys() == expected.keys()
            and all(isinstance(value, list) and all(isinstance(item, str) for item in value)
                    and sorted(value) == expected[key] for key, value in response.items()))


def read_json(path: Path) -> dict[str, Any]:
    """读取 path 的 UTF-8 JSON 并返回字典，文件或格式错误向上传递。"""
    return json.loads(path.read_text(encoding="utf-8"))


def repair_response(folder: Path, cache_root: Path, client: Any) -> dict[str, Any]:
    """对 folder 的待处理断言重新请求 client，核验后替换 cache_root 响应并返回修复记录。

    Args:
        folder: 已失败研究批次目录，不得有活动研究进程。
        cache_root: 可再生成的模型缓存目录。
        client: 提供 request 方法的模型客户端；只允许三次格式纠正。
    Returns:
        原响应哈希、新响应哈希和真实重试来源；研究证据保持不变。
    """
    state = read_json(folder / "checkpoint.json")
    if state["status"] != "FAILED" or not state.get("pending_postprocess"):
        raise ValueError("Expected failed run with committed pending postprocessing")
    sid = state["pending_postprocess"]
    result_path = folder / sid / "result.json"
    relative = str(result_path.relative_to(folder))
    if file_hash(result_path) != state["artifact_hashes"][relative]:
        raise ValueError("Committed measurement changed")
    assertions = read_json(result_path)["blades"]["assertions"]
    context = {"structure_id": sid,
               "assertion_results": [{"id": a["id"], "state": a["state"]} for a in assertions]}
    expected = expected_groups(assertions)
    candidates = []
    for path in cache_root.glob("*.json"):
        cached = read_json(path)
        identity = cached.get("identity", {})
        if (identity.get("role") == "reconciler" and identity.get("context") == context
                and identity.get("nonce") == ""):
            if path.stem != digest(identity):
                raise ValueError("Invalid response cache key")
            candidates.append((path, cached))
    if len(candidates) != 1:
        raise ValueError(f"Expected one original reconciler cache, found {len(candidates)}")
    path, cached = candidates[0]
    if matches_groups(cached["result"], expected):
        raise ValueError("Cached response is valid; failure needs separate investigation")
    evidence = folder / "recovery" / sid
    evidence.mkdir(parents=True, exist_ok=True)
    original_path = evidence / "original-response.json"
    if original_path.exists() and read_json(original_path) != cached:
        raise ValueError("Existing recovery evidence differs")
    write_json(original_path, cached)
    instruction = cached["identity"]["instruction"]
    for attempt in range(3):
        nonce = f"reconciler-repair-{digest(cached)}-{attempt}"
        response = client.request("reconciler", context, instruction, nonce=nonce)
        valid = matches_groups(response, expected)
        write_json(evidence / f"attempt-{attempt}.json", {
            "nonce": nonce, "result": response, "valid": valid, "timestamp": now()})
        if not valid:
            continue
        record = {"structure_id": sid, "original_cache_hash": digest(cached),
                  "replacement_result_hash": digest(response), "retry_nonce": nonce,
                  "script_hash": file_hash(Path(__file__)), "timestamp": now(),
                  "measurement_hash": file_hash(result_path), "evidence": str(evidence)}
        replacement = {**cached, "result": response, "timestamp": now(),
                       "recovery": record, "usage": None}
        # 原始计费信息保留在 original-response；新请求账单在 nonce 对应缓存中。
        write_json(evidence / "repair.json", record)
        write_json(path, replacement)
        print(f"Reconciler repaired: {sid}; measurement unchanged", flush=True)
        return record
    raise ValueError("Reconciler invalid after three audited repair requests")


def main() -> int:
    """校验 CLI 批次并有界修复/恢复，返回退出码；不允许改变冻结引擎或并行启动研究。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", args.run_id):
        raise ValueError("Invalid run ID")
    folder = ROOT / "artifacts" / args.run_id
    checkpoint = folder / "checkpoint.json"
    initial = read_json(checkpoint)
    log_path = ROOT / "artifacts" / f"{args.run_id}.stdout.log"
    report_path = ROOT / "artifacts" / f"{args.run_id}-recovery.json"
    report: dict[str, Any] = {"run_id": args.run_id, "status": "RECOVERING", "events": []}
    write_json(report_path, report)
    for index in range(4):
        state = read_json(checkpoint)
        if state["identity"] != initial["identity"]:
            raise ValueError("Frozen identity changed")
        for name, expected in state["identity"]["code"].items():
            if file_hash(ROOT / "engine" / name) != expected:
                raise ValueError(f"Frozen source changed: {name}")
        if state["status"] == "COMPLETED":
            report["status"] = "COMPLETED"
            write_json(report_path, report)
            return 0
        if state["status"] != "FAILED":
            raise ValueError("Only failed research can be recovered")
        failure = read_json(folder / "failure.json")
        used = len(re.findall(r"^llm \w+: request \d+/\d+$", log_path.read_text(encoding="utf-8"), re.MULTILINE))
        remaining = state["identity"]["config"]["llm_max_calls"] - used
        if remaining < 3:
            raise RuntimeError("Insufficient remaining logical model budget")
        if failure["error"] == "Reconciler changed deterministic assertion outcomes":
            from engine.pipeline import project_lock

            with project_lock(ROOT / "artifacts"):
                record = repair_response(folder, ROOT / "artifacts" / "llm-cache",
                                         DeepSeek(ROOT / "artifacts" / "llm-cache", max_calls=remaining))
                AuditStore(ROOT / "artifacts").append("reconciler_response_repaired", record)
                report["events"].append(record)
        elif not retryable(failure):
            report.update(status="STOPPED", reason=failure["error"])
            write_json(report_path, report)
            return 2
        report.update(status="RUNNING", resume=index + 1, preserved_completed=len(state["completed"]))
        write_json(report_path, report)
        command = [sys.executable, "-u", "-c",
                   ("import json,sys; from pathlib import Path; from engine.config import ResearchConfig; "
                   "from engine.pipeline import run_research; "
                   "s=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')); "
                   "run_research(ResearchConfig.model_validate(s['identity']['config']),s['run_id'],"
                   "Path(s['identity']['data_root']),Path(sys.argv[1]).parent.parent,"
                   "s['identity']['discovery'],s['identity']['bayes'])"), str(checkpoint)]
        result = subprocess.run(command, cwd=ROOT, check=False)
        if result.returncode == 0:
            report["status"] = "COMPLETED"
            write_json(report_path, report)
            return 0
    report.update(status="STOPPED", reason="Recovery limit reached")
    write_json(report_path, report)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())