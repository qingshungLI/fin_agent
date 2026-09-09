"""控制面板服务：只读检查点、模型日志与冻结证据，形成适合展示的轻量快照。

独立于 engine 目录，避免改变正在执行批次的引擎指纹。只公开指定研究产物与模型角色
计数，不公开凭据、模型完整请求、行情矩阵或任意文件路径。校准仅匹配同版本批次。
"""

import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Body, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from engine.api import app
from engine.audit import AuditStore, write_json
from engine.cache import file_hash
from engine.pipeline import project_lock, runtime_identity
from engine.catalog import build_map
from server_jobs import process_alive

ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "artifacts"
RUN_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,80}")
ROLES = ("proposer", "operationalizer", "reviewer", "bettor", "reconciler", "inducer")


def load(path: Path, default: Any = None) -> Any:
    """读取原子 JSON；输入限定产物路径，缺失返回默认值，损坏明确报错。"""
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(503, f"研究产物暂不可读：{path.name}") from exc


def run_folder(run_id: str) -> Path:
    """验证批次 ID；返回含检查点的目录，假设产物根目录由服务固定。"""
    if not RUN_PATTERN.fullmatch(run_id):
        raise HTTPException(400, "批次 ID 无效")
    folder = ARTIFACTS / run_id
    if not folder.resolve().is_relative_to(ARTIFACTS.resolve()) or not (folder / "checkpoint.json").is_file():
        raise HTTPException(404, "研究批次不存在")
    return folder


def logs(run_id: str) -> dict[str, Any]:
    """提取模型角色和统计进度；输入批次 ID，返回限定日志行和明确截断标志。"""
    path = ARTIFACTS / (run_id + ".stdout.log")
    if not path.exists():
        path = ARTIFACTS / "jobs" / (run_id + ".log")
    if not path.exists():
        return {"events": [], "roles": {}, "requests": None, "truncated": False, "updated_at": None}
    with path.open("rb") as handle:
        size = handle.seek(0, 2)
        handle.seek(max(0, size - 2_000_000))
        text = handle.read().decode("utf-8", errors="replace")
    lines = text.splitlines()[1:] if size > 2_000_000 else text.splitlines()
    events, counts, responses = [], Counter(), Counter()
    panel = {}
    for index, line in enumerate(lines):
        shape = re.search(r"panel ready \((\d+), (\d+)\)", line)
        if shape:
            panel = {"dates": int(shape[1]), "symbols": int(shape[2])}
        request = re.fullmatch(r"llm (\w+): request (\d+)/(\d+)", line)
        response = re.fullmatch(r"llm (\w+): response cached", line)
        if request and request[1] in ROLES:
            counts[request[1]] += 1
            events.append({"id": index, "kind": "llm", "text": line})
        elif response and response[1] in ROLES:
            responses[response[1]] += 1
            events.append({"id": index, "kind": "llm", "text": line})
        elif re.match(r"^(placebo (within_day|time_shift|iaaft):|S-[\w-]+:|panel ready |Full grid:)", line):
            events.append({"id": index, "kind": "statistics" if line.startswith("placebo") else "research", "text": line[:500]})
    return {"events": events[-60:], "panel": panel, "requests": sum(counts.values()), "truncated": size > 2_000_000,
            "roles": {r: {"requests": counts[r], "responses": responses[r]} for r in ROLES},
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()}


def result_card(folder: Path, sid: str) -> dict[str, Any]:
    """投影一份已测证据；输入批次目录和结构 ID，返回指标、断言与谱系。"""
    row = load(folder / sid / "result.json", {})
    spec = row.get("structure", {})
    primary = next((c for c in row.get("measurement", {}).get("curves", [])
                    if c["expression"] == 1 and c["horizon"] == spec.get("primary_horizon")), {})
    return {"id": sid, "name": row.get("name", sid), "family": row.get("family"), "form": row.get("form"),
            "verdict": row.get("verdict", "UNDECIDABLE"), "formal": row.get("formal", False),
            "primary": primary, "spec": spec, "blades": row.get("blades", {}),
            "confirmation": row.get("confirmation", {}), "cost": row.get("cost", {}),
            "curves": row.get("measurement", {}).get("curves", []), "seconds": row.get("seconds"),
            "stability": row.get("stability", {}), "discovery": row.get("discovery", {})}


def control_record(folder: Path) -> dict[str, Any]:
    """读取控制记录，缺失时视为运行请求。

    Args:
        folder: 已验证的批次目录。
    Returns:
        dict[str, Any]: 最近控制请求；损坏文件明确报错。
    """
    return load(folder / "control.json", {"action": "run"}) or {"action": "run"}


def write_control(folder: Path, action: str) -> dict[str, Any]:
    """原子写入控制请求，假设调用者持有批次控制锁。

    Args:
        folder: 已验证的批次目录。
        action: run、pause 或 stop。
    Returns:
        dict[str, Any]: 已持久化的请求和 UTC 时间。
    """
    if action not in {"run", "pause", "stop"}:
        raise HTTPException(400, "不支持的控制操作")
    record = {"action": action, "updated_at": datetime.now(timezone.utc).isoformat(),
              "source": "control-panel"}
    write_json(folder / "control.json", record)
    return record


def validate_resume(state: dict[str, Any]) -> None:
    """快速核对恢复进程的代码和环境，数据与模型身份仍由引擎完整验证。

    Args:
        state: 具有冻结 identity 的检查点。
    Returns:
        None: 不一致时返回 HTTP 409，不修改已有控制请求或冻结身份。
    """
    identity = state.get("identity", {})
    code = {path.name: file_hash(path) for path in sorted((ROOT / "engine").glob("*.py"))}
    if not code or identity.get("code") != code:
        raise HTTPException(409, "当前源码与批次冻结版本不同；请使用原版本恢复，或新建研究批次。")
    if identity.get("environment") != runtime_identity():
        raise HTTPException(409, "当前 Python 或依赖环境与冻结记录不同，不能直接恢复。")


def launch_resume(run_id: str, folder: Path) -> dict[str, Any]:
    """启动恢复子进程并记录 PID，假设调用者已校验身份并持有控制锁。

    Args:
        run_id: 已验证的批次标识。
        folder: 具有 checkpoint.json 的批次目录。
    Returns:
        dict[str, Any]: 进程 PID 与 RESUMING 状态；它不表示引擎已通过完整恢复验证。
    """
    command = [sys.executable, "-u", "-c",
        "import json,sys; from pathlib import Path; from engine.config import ResearchConfig; "
        "from engine.pipeline import run_research; s=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')); "
        "run_research(ResearchConfig.model_validate(s['identity']['config']),s['run_id'],"
        "Path(s['identity']['data_root']),Path(sys.argv[2]),s['identity']['discovery'],s['identity']['bayes'])",
        str(folder / "checkpoint.json"), str(ARTIFACTS)]
    record = load(ARTIFACTS / f"{run_id}-processes.json", {}) or {}
    # 父进程及时关闭日志句柄；子进程持有自己的句柄，继续写日志不受影响。
    with (ARTIFACTS / f"{run_id}.stdout.log").open("a", encoding="utf-8") as stdout, \
         (ARTIFACTS / f"{run_id}.stderr.log").open("a", encoding="utf-8") as stderr:
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
            stdout=stdout, stderr=stderr, start_new_session=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    record.update({"research_launcher_pid": process.pid,
                   "control_panel_resume_at": datetime.now(timezone.utc).isoformat()})
    try:
        write_json(ARTIFACTS / f"{run_id}-processes.json", record)
    except OSError:
        # 只终止本次刚启动但未能登记的子进程，避免留下控制台无法追踪的任务。
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        raise
    return {"pid": process.pid, "status": "RESUMING"}


def apply_control(run_id: str, folder: Path, action: str) -> dict[str, Any]:
    """在控制锁内检查状态并提交指令，restart 沿用幂等恢复语义。

    Args:
        run_id: 已验证的批次标识。
        folder: 批次目录。
        action: pause、stop、resume 或 restart。
    Returns:
        dict[str, Any]: 请求回执；不将回执伪装成实际 PAUSED 或 STOPPED。
    """
    state = load(folder / "checkpoint.json")
    status = state.get("status")
    if status not in {"RUNNING", "PAUSED", "RESUMING", "FAILED", "STOPPED", "INTERRUPTED", "COMPLETED"}:
        raise HTTPException(409, "检查点状态未知，不能自动执行控制操作。")
    if status == "COMPLETED":
        raise HTTPException(409, "批次已完成；请新建批次开展后续研究。")
    if action in {"pause", "stop"}:
        if status not in {"RUNNING", "PAUSED", "RESUMING"}:
            raise HTTPException(409, f"当前状态 {status} 不接受暂停或停止请求。")
        return {"run_id": run_id, "status": "REQUESTED", "control": write_control(folder, action)}
    record = load(ARTIFACTS / f"{run_id}-processes.json", {}) or {}
    pid = record.get("research_launcher_pid")
    if pid and process_alive(pid):
        return {"run_id": run_id, "status": "REQUESTED", "pid": pid,
                "control": write_control(folder, "run")}
    if not pid and status in {"RUNNING", "PAUSED", "RESUMING"}:
        # 外部 CLI 启动的进程可能没有控制台 PID，不能据此断言它已退出并重复启动。
        if action == "restart":
            raise HTTPException(409, "缺少进程记录，无法确认原进程已退出；请先核对启动终端。")
        return {"run_id": run_id, "status": "REQUESTED", "control": write_control(folder, "run")}
    validate_resume(state)
    previous = control_record(folder)
    write_control(folder, "run")
    try:
        launched = launch_resume(run_id, folder)
    except OSError as exc:
        write_json(folder / "control.json", previous)
        raise HTTPException(503, "恢复进程未能启动，请检查本机日志目录和执行环境。") from exc
    return {"run_id": run_id, **launched}


@app.post("/api/control/runs/{run_id}/action")
def run_action(run_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """串行处理批次控制命令，控制锁与长期研究锁分开。

    Args:
        run_id: 批次标识。
        payload: 仅含 action 的请求对象。
    Returns:
        dict[str, Any]: 已提交回执；并发请求返回 HTTP 409，避免重复启动。
    """
    action = payload.get("action")
    if set(payload) != {"action"} or not isinstance(action, str) or action not in {
        "pause", "resume", "stop", "restart"
    }:
        raise HTTPException(400, "请求必须仅包含有效的 action。")
    folder = run_folder(run_id)
    try:
        with project_lock(ARTIFACTS / ".control-locks" / run_id):
            return apply_control(run_id, folder, action)
    except RuntimeError as exc:
        raise HTTPException(409, "另一个控制请求正在处理中，请刷新状态后重试。") from exc

@app.get("/api/control/skill")
def skill_download() -> FileResponse:
    """Download the repository skill that packages the RSI research protocol."""
    path = ROOT / "skills" / "factor-research" / "SKILL.md"
    if not path.is_file():
        raise HTTPException(404, "Skill package is unavailable")
    return FileResponse(path, filename="aurora-factor-research-skill.md", media_type="text/markdown")


@app.get("/api/control/skill-manifest")
def skill_manifest() -> dict[str, Any]:
    """Return the public Skill metadata and repository installation coordinates."""
    return {"name": "aurora-factor-research", "version": "1.0.0",
            "repository": "https://github.com/qingshungLI/fin_agent",
            "skill_path": "skills/factor-research/SKILL.md", "rsi": "Recursive Self-Improvement",
            "data_formats": ["CSV", "Parquet", "pandas DataFrame"],
            "entrypoints": ["research_sdk", "POST /api/studio/datasets", "POST /api/studio/experiments"]}


@app.get("/api/control/runs")
def runs() -> list[dict[str, Any]]:
    """列出本地可审查批次；无参数，返回按启动时间倒序排列的基础信息。"""
    found = []
    for path in ARTIFACTS.glob("*/checkpoint.json"):
        state = load(path)
        if state and RUN_PATTERN.fullmatch(path.parent.name):
            found.append({"id": path.parent.name, "status": state.get("status"),
                          "started_at": state.get("started_at", ""), "measured": len(state.get("completed", []))})
    return sorted(found, key=lambda r: r["started_at"], reverse=True)


@app.get("/api/control/snapshot/{run_id}")
def snapshot(run_id: str) -> dict[str, Any]:
    """合成真实研究快照；输入批次 ID，返回可轮询的进度、证据与模型调用信息。"""
    folder = run_folder(run_id)
    state = load(folder / "checkpoint.json")
    status = state["status"]
    process_record = load(ARTIFACTS / (run_id + "-processes.json"), {})
    recorded_pid = process_record.get("research_launcher_pid")
    if recorded_pid and status in {"RUNNING", "FAILED"}:
        alive = process_alive(recorded_pid)
        status = "RESUMING" if alive and status == "FAILED" else "INTERRUPTED" if not alive and status == "RUNNING" else status
    identity = state["identity"]
    config = identity["config"]
    ids = state.get("inherited", []) + state.get("completed", [])
    rows = [result_card(folder, sid) for sid in ids]
    attempts = state.get("attempts", len(state.get("completed", [])))
    sid = f"S-{run_id}-{attempts + 1:03d}"
    proposal = load(folder / sid / "proposal.json") if state["status"] != "COMPLETED" else None
    if state.get("pending_postprocess"):
        sid = state["pending_postprocess"]
        proposal = load(folder / sid / "proposal.json")
    frozen = load(folder / sid / "frozen.json", {}) if proposal else {}
    queue = state.get("queue", [])
    current_cell = (f"{proposal['family']}-F{proposal['form']}" if proposal else
                    f"{queue[0]['family']}-F{queue[0]['form']}" if queue and status in {"RUNNING", "RESUMING"} else None)
    cells = build_map()
    rejected = state.get("rejected_priors", [])
    for cell in cells:
        matches = [r for r in rows if r["family"] == cell["family"] and r["form"] == cell["form"]]
        cell.update(structures=[r["id"] for r in matches],
                    display_state="active" if cell["id"] == current_cell else
                    "measured" if matches else "rejected" if any(r.get("coordinate") == cell["id"] for r in rejected)
                    else "pending")
    overview = load(ARTIFACTS / "overview.json", {})
    progress = load(folder / "progress.json", {})
    log = logs(run_id)
    panel = {"dates": overview.get("dates") if overview.get("run_id") == run_id else None,
             "symbols": overview.get("symbols") if overview.get("run_id") == run_id else None}
    if not panel["dates"] and log.get("panel"):
        panel = log["panel"]
    validation = load(ARTIFACTS / "validation/full-validation.json", {})
    if validation.get("code_sha256") != identity.get("code") or validation.get("environment") != identity.get("environment"):
        validation = {"status": "UNAVAILABLE", "steps": [], "reason": "无匹配当前批次版本的验证记录"}
    pipeline = load(ARTIFACTS / (run_id + "-pipeline") / "pipeline.json", {})
    memory = load(folder / "memory.json", state.get("posterior", {}))
    audit = {"valid": None, "events": 0, "access": []}
    if (ARTIFACTS / "audit.sqlite3").exists():
        try:
            audit = AuditStore(ARTIFACTS).verify()
        except ValueError:
            audit = {"valid": False, "events": 0, "access": [], "reason": "审计验证失败"}
    return {"run_id": run_id, "status": status, "checkpoint_status": state["status"], "started_at": state.get("started_at"),
            "finished_at": state.get("finished_at"), "observed_at": datetime.now(timezone.utc).isoformat(),
            "config": config, "model": {k: v for k, v in (identity.get("model") or {}).items()
                                          if k in {"model", "reasoning_model", "reasoning_effort", "thinking_roles"}},
            "counts": {"attempts": attempts, "budget": config["max_structures"],
                       "measured": len(state.get("completed", [])), "inherited": len(state.get("inherited", [])),
                       "rejected": len(rejected), "cells": len({(r["family"], r["form"]) for r in rows}),
                       "children": sum(bool(r["spec"].get("lineage", {}).get("parent")) for r in rows),
                       "formal": sum(r["formal"] and r["verdict"] == "PASS" for r in rows)},
            "panel": panel,
            "map": cells, "rows": rows, "current": {"id": sid if proposal else None,
                "cell": current_cell, "spec": proposal, "frozen": bool(frozen), "bets": frozen.get("bets", {})},
            "queue": dict(Counter(t["operator"] for t in queue)), "log": log,
            "quality": load(folder / "data-quality.json", []), "memory": memory,
            "validation": validation, "pipeline": pipeline, "audit": audit,
            "progress": progress, "control": control_record(folder), "failure": {"type": load(folder / "failure.json", {}).get("type")}}


@app.get("/api/control/compositions/{run_id}")
def compositions(run_id: str) -> list[dict[str, Any]]:
    """返回当前源批次的组合快照；输入批次 ID，仅读取摘要，不加载持仓矩阵。"""
    run_folder(run_id)
    reports = []
    replays = [load(path, {}) for path in
               (ARTIFACTS / "composition-executions").glob("*/report.json")]
    for path in (ARTIFACTS / "compositions").glob("*/report.json"):
        record = load(path, {})
        if record.get("source_run") != run_id:
            continue
        record = dict(record)
        history = sorted(
            (item for item in replays if item.get("source_run") == run_id
             and item.get("batch_id") == record.get("batch_id")),
            key=lambda item: item.get("created_at", ""), reverse=True,
        )
        record["execution_history"] = history
        for name, variant in record.get("variants", {}).items():
            if name not in {"parallel", "conflict_cash", "consensus"}:
                continue
            variant["cost_comparison"] = load(path.parent / name / "cost-comparison.json", {})
            execution = load(path.parent / name / "execution/failure.json", {})
            if execution:
                variant["execution_failure"] = execution.get("reason", "执行失败")[:700]
            if history:
                latest = history[0].get("variants", {}).get(name)
                # 新回放尚未开始的规则必须显示等待，不能沿用旧执行结果。
                variant["execution"] = latest or {"status": "PENDING"}
                variant.pop("execution_failure", None)
                if latest and latest.get("reason"):
                    variant["execution_failure"] = latest["reason"][:700]
        reports.append(record)
    return sorted(reports, key=lambda item: item.get("created_at", ""), reverse=True)


@app.get("/api/control/composition-artifact/{batch_id}/{variant}/{name}")
def composition_artifact(batch_id: str, variant: str, name: str) -> FileResponse:
    """下载组合白名单产物；输入组合 ID、规则名和文件名，拒绝任意路径和不存在结果。"""
    if not RUN_PATTERN.fullmatch(batch_id) or variant not in {"parallel", "conflict_cash", "consensus"}:
        raise HTTPException(400, "组合标识无效")
    allowed = {"target.parquet", "routing-daily.parquet", "contributions.parquet", "routing.json",
               "relations.json", "research-daily.parquet", "cost-comparison.json"}
    path = ARTIFACTS / "compositions" / batch_id / variant / name
    if name not in allowed or not path.is_file():
        raise HTTPException(404, "组合产物尚未生成或未公开")
    return FileResponse(path, filename=f"{batch_id}-{variant}-{name}")


@app.get("/api/control/artifact/{run_id}/{name}")
def artifact(run_id: str, name: str) -> FileResponse:
    """下载白名单报告；输入批次和报告名，返回附件，不提供任意目录浏览。"""
    allowed = {"report.md", "law.md", "progress.json", "data-quality.json", "memory.json", "queue.json"}
    if name not in allowed:
        raise HTTPException(404, "未公开此产物")
    path = run_folder(run_id) / name
    if not path.is_file():
        raise HTTPException(404, "产物尚未生成")
    return FileResponse(path, filename=f"{run_id}-{name}")


from studio_api import router as studio_router
app.include_router(studio_router)

if (ROOT / "dist").is_dir():
    app.mount("/", StaticFiles(directory=ROOT / "dist", html=True), name="dashboard")