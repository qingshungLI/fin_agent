from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .client import init_rqdata
from .config import DATA_ROOT, END_DATE, NEWS_START, WAREHOUSE_PATH, ensure_directories
from .migrate_csv import migrate_and_delete
from .notebook import create_sanity_notebook
from .quota import QuotaExhausted, quota_snapshot
from .state import Manifest
from .validate import validate_task
from .warehouse import build_views


def _run_task(name: str, rq, manifest: Manifest, start: str | None = None) -> None:
    if name == "skeleton":
        from .tasks.skeleton import run
        run(rq, manifest)
    elif name == "daily_bar":
        from .tasks.daily_bar import run
        run(rq, manifest, start=start or "2016-07-01")
    elif name == "events":
        from .tasks.events import run
        run(rq, manifest, start=start or "2016-07-01")
    elif name == "crosssec":
        from .tasks.crosssec import run
        run(rq, manifest, start=start or "2016-07-01")
    elif name == "open_auction":
        from .tasks.open_auction import run
        run(rq, manifest, start=start or "2016-07-01")
    elif name == "news":
        from .tasks.news import run
        run(rq, manifest, start=start or NEWS_START)
    elif name == "consensus":
        from .tasks.consensus import run
        run(rq, manifest, start=start or "2016-07-01")
    elif name == "calibration":
        from .tasks.calibration import run
        report = run(rq, manifest, start=start or "2016-07-01")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        raise ValueError(f"未知任务：{name}")


def cmd_backfill(args) -> int:
    rq = init_rqdata()
    manifest = Manifest()
    order = ("skeleton", "daily_bar", "events", "crosssec", "open_auction", "news", "consensus")
    tasks = order if args.task == "all" else (args.task,)
    try:
        for task in tasks:
            _run_task(task, rq, manifest, args.start)
            build_views()
            manifest.set_status(task, "COMPLETE")
    except QuotaExhausted as exc:
        manifest.set_status(task, "PAUSED", str(exc))
        print(str(exc), file=sys.stderr)
        return 75
    except Exception as exc:
        manifest.set_status(task, "FAILED", str(exc))
        raise
    return 0


def cmd_status(args) -> int:
    manifest = Manifest().data
    result = {"data_root": str(DATA_ROOT), "manifest": manifest}
    if args.online:
        result["quota"] = quota_snapshot(init_rqdata(), "status")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_validate(args) -> int:
    report = validate_task(args.task)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "CLEAN" else 2


def cmd_estimate(args) -> int:
    rq = init_rqdata()
    before = quota_snapshot(rq, f"estimate:{args.task}:before")
    if args.task == "news":
        if not hasattr(rq, "news"):
            raise PermissionError("news 插件不可用")
        try:
            frame = rq.news.get_stock_news(["000001.XSHE"], "2021-03-01", "2021-03-31")
        except Exception as exc:
            if "PermissionDenied" in type(exc).__name__ or "permission denied" in str(exc).lower():
                capability = DATA_ROOT / "_state" / "capabilities.json"
                capability.parent.mkdir(parents=True, exist_ok=True)
                capability.write_text(json.dumps({"news": {"available": False, "reason": "账号未开通 news.get_stock_news 权限"}}, ensure_ascii=False, indent=2), encoding="utf-8")
                raise PermissionError("账号未开通 news.get_stock_news 权限；请联系 Ricequant 商务开通") from exc
            raise
    elif args.task == "daily_bar":
        frame = rq.get_price(["000001.XSHE"], "2021-01-01", "2021-12-31", frequency="1d", adjust_type="none", skip_suspended=False)
    else:
        raise ValueError("estimate 当前仅支持 news 或 daily_bar")
    after = quota_snapshot(rq, f"estimate:{args.task}:after")
    used = max(0, float(after["bytes_used"]) - float(before["bytes_used"]))
    rows = 0 if frame is None else len(frame)
    print(json.dumps({"task": args.task, "sample_rows": rows, "sample_transfer_bytes": used}, ensure_ascii=False, indent=2))
    return 0


def cmd_update(args) -> int:
    rq = init_rqdata()
    from .tasks.update import run
    result = run(rq)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in ("UPDATED", "NO_TRADING_DATE") else 3


def cmd_migrate_csv(args) -> int:
    result = migrate_and_delete()
    views = build_views()
    result["views"] = views
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_build_views(args) -> int:
    print(json.dumps({"warehouse": str(WAREHOUSE_PATH), "views": build_views()}, ensure_ascii=False, indent=2))
    return 0


def cmd_notebook(args) -> int:
    print(create_sanity_notebook())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rqpull", description="RQData 可恢复 Parquet/DuckDB 数据管线")
    sub = parser.add_subparsers(dest="command", required=True)
    backfill = sub.add_parser("backfill", help="全量回补或恢复断点")
    backfill.add_argument("--task", required=True, choices=("all", "skeleton", "daily_bar", "events", "crosssec", "open_auction", "calibration", "news", "consensus"))
    backfill.add_argument("--from", dest="start")
    backfill.set_defaults(func=cmd_backfill)
    status = sub.add_parser("status", help="显示断点状态")
    status.add_argument("--online", action="store_true", help="同时读取在线配额")
    status.set_defaults(func=cmd_status)
    validate = sub.add_parser("validate", help="运行本地质量检查")
    validate.add_argument("--task", required=True)
    validate.set_defaults(func=cmd_validate)
    estimate = sub.add_parser("estimate", help="小样本估算传输量")
    estimate.add_argument("--task", required=True, choices=("news", "daily_bar"))
    estimate.set_defaults(func=cmd_estimate)
    update = sub.add_parser("update", help="检查数据就绪并执行日增量")
    update.set_defaults(func=cmd_update)
    migrate = sub.add_parser("migrate-csv", help="校验迁移旧 CSV 后删除 CSV")
    migrate.set_defaults(func=cmd_migrate_csv)
    views = sub.add_parser("build-views", help="重建 DuckDB 视图")
    views.set_defaults(func=cmd_build_views)
    notebook = sub.add_parser("create-notebook", help="生成离线体检 Notebook")
    notebook.set_defaults(func=cmd_notebook)
    return parser


def main() -> int:
    ensure_directories()
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
