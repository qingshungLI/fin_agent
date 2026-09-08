"""企业研究工作室 API：接收用户数据、校验映射、启动隔离 SDK 子进程并提供可移植结果。

导入文件保存在独立 studio 目录，禁止用户提供执行路径或 Python 代码；请求体有大小限制。
最多一个自助研究同时运行，比赛研究使用自己的进程和冻结产物，互不覆盖。
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from research_sdk import ExperimentSpec, dataset_summary
from research_sdk.core import normalize, write_json
from server_jobs import process_alive

ROOT = Path(__file__).resolve().parent
STUDIO = ROOT / "artifacts/studio"
router = APIRouter(prefix="/api/studio", tags=["User research workspace"])
LAUNCH_LOCK = threading.Lock()


def allowed_origin(request: Request) -> None:
    """限制浏览器跨站写入；输入请求，同源或无 Origin 的本地 SDK 调用可继续。"""
    origin = request.headers.get("origin")
    allowed = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5173, 8001)}
    if origin and origin not in allowed:
        raise HTTPException(403, "仅允许本机工作室提交")


def record_path(kind: str, identifier: str) -> Path:
    """解析服务生成的标识；输入目录类型和 ID，返回受限路径，拒绝路径注入。"""
    if not re.fullmatch(r"[a-z]+-[a-f0-9]{12}", identifier):
        raise HTTPException(400, "无效标识")
    path = STUDIO / kind / identifier
    if not path.is_dir():
        raise HTTPException(404, "记录不存在")
    return path


def load(path: Path) -> dict:
    """读取本地原子报告；输入已验证路径，返回 JSON 对象。"""
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/datasets")
def datasets() -> list[dict]:
    """列出已校验的数据资产；无参数，返回数据摘要，不读取行情矩阵。"""
    return sorted([load(p) for p in (STUDIO / "datasets").glob("*/metadata.json")],
                  key=lambda item: item["created_at"], reverse=True)


@router.post("/datasets", status_code=201)
async def import_dataset(request: Request, filename: str = "data.csv", mapping: str = "{}") -> dict:
    """流式接收 CSV/Parquet；输入原文件和目标列到原列映射，返回规范数据摘要。"""
    allowed_origin(request)
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 25 * 1024 * 1024:
            raise HTTPException(413, "单次导入最多 25 MiB")
    try:
        aliases = json.loads(mapping)
        if not isinstance(aliases, dict) or any(k not in {"date", "symbol", "open", "close"} or not isinstance(v, str) for k, v in aliases.items()):
            raise ValueError("映射必须为标准列名到原列名的 JSON 对象")
        if len(set(aliases.values())) != len(aliases):
            raise ValueError("不同标准列不能映射到同一原始列")
        suffix = Path(filename).suffix.lower()
        if suffix not in {".csv", ".parquet"}:
            raise ValueError("仅支持 CSV 或 Parquet")
        frame = pd.read_parquet(io.BytesIO(content)) if suffix == ".parquet" else pd.read_csv(io.BytesIO(content), dtype={aliases.get("symbol", "symbol"): str})
        if any(value not in frame.columns for value in aliases.values()):
            raise ValueError("映射的原始列不存在")
        frame = normalize(frame.rename(columns={value: key for key, value in aliases.items()}))
        summary = dataset_summary(frame)
    except Exception as exc:
        raise HTTPException(422, f"数据校验失败：{exc}") from exc
    identifier = "data-" + uuid4().hex[:12]
    folder = STUDIO / "datasets" / identifier
    folder.mkdir(parents=True)
    frame.to_parquet(folder / "panel.parquet", index=False)
    metadata = {"id": identifier, "name": Path(filename).name[:150], **summary,
                "created_at": datetime.now(timezone.utc).isoformat()}
    write_json(folder / "metadata.json", metadata)
    return metadata


class LaunchRequest(BaseModel):
    """定义自助启动请求；输入数据资产 ID 和 SDK 配置，不接收服务器路径。"""
    model_config = ConfigDict(extra="forbid")
    dataset_id: str = Field(max_length=40)
    spec: ExperimentSpec


@router.get("/experiments")
def experiments() -> list[dict]:
    """返回任务状态；无参数，进程已结束但未写完成报告时明确标记失败。"""
    result = []
    for path in (STUDIO / "jobs").glob("*/job.json"):
        item = load(path)
        report = path.parent / "output/report.json"
        summary = load(report) if report.exists() else {}
        item.update(status=summary.get("status", "RUNNING"),
                    completed_candidates=len(summary.get("results", [])),
                    elapsed_seconds=summary.get("elapsed_seconds"), error=summary.get("error"))
        if item["status"] == "RUNNING" and not process_alive(item["pid"]):
            item.update(status="FAILED", error=item.get("error") or "工作进程已退出，请查看任务日志")
        result.append(item)
    return sorted(result, key=lambda item: item["created_at"], reverse=True)


@router.post("/experiments", status_code=202)
def launch(options: LaunchRequest, request: Request) -> dict:
    """冻结用户配置并启动无 shell 子进程；输入数据和格子，返回可轮询任务，不占比赛锁。"""
    allowed_origin(request)
    source = record_path("datasets", options.dataset_id)
    from engine.dsl import compile_expression
    try:
        for cell in options.spec.cells:
            compile_expression(cell.expression, set(load(source / "metadata.json")["fields"]), {})
    except (ValueError, SyntaxError) as exc:
        raise HTTPException(422, str(exc)) from exc
    with LAUNCH_LOCK:
        if any(item["status"] == "RUNNING" for item in experiments()):
            raise HTTPException(409, "已有自助研究运行中，请等待完成")
        identifier = "study-" + uuid4().hex[:12]
        folder = STUDIO / "jobs" / identifier
        folder.mkdir(parents=True)
        write_json(folder / "spec.json", options.spec.model_dump())
        import os
        environment = {**os.environ, "PYTHONUTF8": "1", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
        with (folder / "worker.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "-u", "-m", "research_sdk", "--data", str(source / "panel.parquet"),
                "--spec", str(folder / "spec.json"), "--output", str(folder / "output")], cwd=ROOT,
                stdout=log, stderr=subprocess.STDOUT, env=environment,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        item = {"id": identifier, "dataset_id": options.dataset_id, "name": options.spec.name,
                "profile": options.spec.profile, "pid": process.pid, "status": "RUNNING",
                "created_at": datetime.now(timezone.utc).isoformat()}
        write_json(folder / "job.json", item)
    return item


@router.get("/experiments/{identifier}")
def experiment(identifier: str) -> dict:
    """返回已完成候选和进度；输入任务 ID，结果未就绪时不虚构指标。"""
    folder = record_path("jobs", identifier)
    path = folder / "output/report.json"
    return load(path) if path.exists() else {"status": "STARTING", "results": []}


@router.get("/experiments/{identifier}/download/{filename}")
def download(identifier: str, filename: str) -> FileResponse:
    """导出白名单审计及因子目录；输入任务和文件名，拒绝任意路径。"""
    folder = record_path("jobs", identifier)
    if filename not in {"report.json", "frozen.json", "factors.csv", "candidates.json", "artifact-hashes.json", "worker.log"}:
        raise HTTPException(404, "未公开该文件")
    path = folder / filename if filename == "worker.log" else folder / "output" / filename
    if not path.is_file():
        raise HTTPException(404, "产物尚未生成")
    return FileResponse(path, filename=filename)


@router.get("/experiments/{identifier}/factors/{candidate}/{filename}")
def factor_download(identifier: str, candidate: str, filename: str) -> FileResponse:
    """导出单候选因子和回测路径；输入白名单 ID/文件，返回原始可复核矩阵。"""
    folder = record_path("jobs", identifier)
    if not re.fullmatch(r"C\d{3}", candidate) or filename not in {"factor.parquet", "target.parquet", "daily.parquet", "ic.parquet"}:
        raise HTTPException(404, "无此因子产物")
    path = folder / "output" / candidate / filename
    if not path.is_file():
        raise HTTPException(404, "因子尚未生成")
    return FileResponse(path, filename=f"{candidate}-{filename}")