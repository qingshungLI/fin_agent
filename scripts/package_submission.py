"""主办方打包管线：从 Git 源码白名单构建 code.zip，再汇集报告与说明并记录哈希。

包不包含授权行情、凭据、运行缓存或环境；按十进制 512 MB 同时限制代码包和总包。
清单记录源码提交及实际文件哈希，确保离线评审可核对来源。重复构建覆盖已命名文件。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "submission" / "AURORA_submission"
LIMIT = 512_000_000
CODE_DIRS = {"engine", "composition", "research_sdk", "src", "tests", "backtest", "skills"}
CODE_SUFFIXES = {".py", ".ts", ".tsx", ".css", ".toml", ".yaml", ".yml", ".md", ".json"}
ROOT_FILES = {
    "run_engine.py",
    "dashboard_server.py",
    "studio_api.py",
    "server_jobs.py",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "tsconfig.json",
    "vite.config.ts",
    "playwright.config.ts",
    "index.html",
    ".env.example",
    ".gitignore",
    "README.md",
    "competition_submission.md",
    "PSEUDOCODE.md",
    "IMPLEMENTATION.md",
    "RUN_PIPELINE.md",
    "CONTROL_PANEL.md",
    "COMPOSITION.md",
    "FAST_RESEARCH.md",
    "RSI_ALPHA_HARNESS.md",
    "ENTERPRISE_READINESS.md",
    "backtest.md",
}
OMIT_SCRIPTS = set()


def git(*args: str) -> str:
    """运行只读 Git 命令；输入参数，返回标准输出，失败时抛异常。"""
    return subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout.strip()


def digest(path: Path) -> str:
    """计算附件 SHA256；输入现有文件，返回十六进制摘要，按块避免读入大文件。"""
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def core_files() -> list[Path]:
    """选择受版本管理的核心源码；无参数，返回排序路径，拒绝任何凭据或数据扩展名。"""
    selected = []
    for name in git("ls-files").splitlines():
        path = ROOT / name
        rel = Path(name)
        if not path.is_file() or any(part.startswith("._") for part in rel.parts):
            continue
        allowed = name in ROOT_FILES
        if rel.parts[0] in CODE_DIRS and path.suffix in CODE_SUFFIXES:
            allowed = True
        if rel.parts[0] == "scripts" and path.suffix in {".py", ".ps1", ".sh"}:
            allowed = path.name not in OMIT_SCRIPTS
        if rel.parts[0] == "docs" and path.suffix == ".md" :
            allowed = True
        if ((rel.parts[0] == "report" and path.suffix in {".md", ".json", ".png"})
                or (rel.parts[0] == "docs" and path.suffix in {".tex", ".pdf", ".png", ".json", ".pptx", ".html", ".svg", ".jpg"}
                    )
                or name == "docs/research/2026-09-09-results.json" or name == "data/data.md"):
            allowed = True
        if allowed:
            if path.name.startswith(".env") and path.name != ".env.example":
                raise ValueError(f"代码白名单包含凭据文件：{name}")
            selected.append(path)
    if not selected or not (ROOT / "engine/pipeline.py") in selected:
        raise ValueError("缺少核心引擎源码")
    return sorted(set(selected))


def verify_zip(path: Path) -> None:
    """校验压缩包大小、CRC 和路径；输入 ZIP，返回 None，超限或异常路径立即失败。"""
    if not 0 < path.stat().st_size <= LIMIT:
        raise ValueError(f"压缩包超出 512 MB 或为空：{path.name}")
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError(f"压缩包 CRC 异常：{path.name}")
        for name in archive.namelist():
            parts = Path(name).parts
            if name.startswith(("/", "\\")) or ".." in parts or ":" in name:
                raise ValueError("压缩包包含非安全路径")


def main() -> None:
    """构建代码包和主办方总包；无参数，返回 None，附件缺失或大小超限时明确失败。"""
    OUT.mkdir(parents=True, exist_ok=True)
    paths = core_files()
    records = {
        p.relative_to(ROOT).as_posix(): {"bytes": p.stat().st_size, "sha256": digest(p)}
        for p in paths
    }
    guide = (ROOT / "docs/SUBMISSION_README.md").read_text(encoding="utf-8-sig").encode("utf-8")
    records["提交版使用说明.md"] = {"bytes": len(guide), "sha256": hashlib.sha256(guide).hexdigest()}
    code_path = OUT / "code.zip"
    with zipfile.ZipFile(code_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in paths:
            archive.write(path, "code/" + path.relative_to(ROOT).as_posix())
        archive.writestr(
            "code/提交版使用说明.md",
            (ROOT / "docs/SUBMISSION_README.md").read_text(encoding="utf-8-sig"),
        )
    verify_zip(code_path)
    attachments = {
        "AURORA_技术报告.pdf": "docs/AURORA_Alpha_Harness_Technical_Report.pdf",
        "AURORA_项目演示.pptx": "docs/ppt/AURORA_论文图示版.pptx",
        "AURORA_项目演示.pdf": "docs/ppt/AURORA_论文图示版.pdf",
        "核心流程伪代码.md": "docs/SUBMISSION_PSEUDOCODE.md",
        "项目说明.md": "docs/SUBMISSION_README.md",
        "项目公开介绍.md": "competition_submission.md",
        "项目封面.png": "docs/figures/brand_cover.png",
    }
    for target, source in attachments.items():
        if target == "项目公开介绍.md":
            # Outer documentation links point into the separately extracted code/ tree.
            import re
            text = (ROOT / source).read_text(encoding="utf-8-sig")
            text = re.sub(r"\]\((?!https?://|#)([^)]+)\)", r"](code/\1)", text)
            (OUT / target).write_text(text, encoding="utf-8")
        else:
            shutil.copyfile(ROOT / source, OUT / target)
    expected = {"code.zip", "MANIFEST.json", *attachments}
    actual = {p.name for p in OUT.iterdir()}
    if actual - expected:
        raise ValueError(f"提交目录存在未登记文件：{sorted(actual - expected)}")
    manifest = {
        "project": "AURORA Alpha Harness",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": git("rev-parse", "HEAD"),
        "source_branch": git("branch", "--show-current"),
        "size_limit_bytes": LIMIT,
        "code_file_count": len(records),
        "scope": "Core source and tests; excludes licensed raw data, credentials and runtime artifacts.",
        "attachments": {
            name: {"bytes": (OUT / name).stat().st_size, "sha256": digest(OUT / name)}
            for name in sorted(expected - {"MANIFEST.json"})
        },
        "code_files": records,
    }
    (OUT / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    bundle = OUT.parent / "AURORA_submission.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(OUT.iterdir()):
            archive.write(path, OUT.name + "/" + path.name)
    verify_zip(bundle)
    (OUT.parent / "SHA256SUMS.txt").write_text(
        f"{digest(bundle)}  {bundle.name}\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "source_commit": manifest["source_commit"],
                "code_files": len(records),
                "code_bytes": code_path.stat().st_size,
                "bundle_bytes": bundle.stat().st_size,
                "limit_bytes": LIMIT,
                "bundle": str(bundle),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
