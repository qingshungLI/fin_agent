"""SDK 命令行：从指定 CSV/Parquet 和 JSON 格子配置运行自助研究，退出码反映完成状态。"""
import argparse
import json
from pathlib import Path

import pandas as pd

from research_sdk import ExperimentSpec, run_experiment


def main() -> int:
    """解析路径并运行研究；输入 CLI 参数，返回退出码，输出目录必须不存在。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    frame = pd.read_parquet(args.data) if args.data.suffix.lower() == ".parquet" else pd.read_csv(args.data, dtype={"symbol": str})
    spec = ExperimentSpec.model_validate_json(args.spec.read_text(encoding="utf-8"))
    report = run_experiment(frame, spec, args.output)
    print(json.dumps({"status": report["status"], "candidates": report["candidate_count"],
                      "seconds": report["elapsed_seconds"]}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())