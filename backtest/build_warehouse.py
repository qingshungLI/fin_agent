"""构建本地回测仓库的 DuckDB 视图。

Pipeline：读取 FINANCE_DATA_ROOT 下的标准化 Parquet 分区，按数据集创建 v_* 视图，
写入 data/warehouse.duckdb，供 RQAlpha 本地 DataSource 和研究脚本复用。
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    """创建数据视图并打印结果；返回 0 表示成功。"""
    project_root = Path(__file__).resolve().parent
    sys.path.insert(0, str(project_root))
    from rqpull.config import DATA_ROOT, WAREHOUSE_PATH
    from rqpull.warehouse import build_views

    if not DATA_ROOT.exists():
        raise FileNotFoundError(f"数据目录不存在: {DATA_ROOT}")
    views = build_views()
    print(f"data_root={DATA_ROOT}")
    print(f"warehouse={WAREHOUSE_PATH}")
    print("views=" + ",".join(views))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
