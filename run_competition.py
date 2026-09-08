"""Competition submission research run with adjusted thresholds."""
import argparse
from datetime import UTC, datetime
from pathlib import Path

from engine.config import ResearchConfig
from engine.pipeline import run_research


def main():
    """
    竞赛专用研究运行脚本

    调整说明：
    1. 使用工程模式加速（n_boot=100, n_placebo=99, n_trees=30）
    2. 仅运行A段探索（不读取B/H段）
    3. 生成完整的研究展示材料
    4. 所有结果标注为"研究证据"而非"正式因子"
    """
    p = argparse.ArgumentParser()
    p.add_argument("--data-root", type=Path, default=Path("data"))
    p.add_argument("--output-root", type=Path, default=Path("artifacts_competition"))
    p.add_argument("--max-structures", type=int, default=9,
                   help="最多运行的结构数（已有9个冻结提案）")
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args()

    # 竞赛专用配置：工程模式 + 已有提案
    # 使用quarantine模式处理数据质量问题，而不是strict模式阻止运行
    # 关键修复：n_placebo 必须 >= 100，否则 placebo.py 会直接短路返回 untested
    # （100次以下重复数学上不可能达到 p<0.01 判据），四把刀会全部空转
    config = ResearchConfig(
        start="2016-07-01",
        end="2022-06-30",  # 仅A段
        max_symbols=0,  # 全市场
        max_structures=args.max_structures,
        workers=args.workers,
        provider="manual",  # 使用已冻结的9个提案
        industry_policy="quarantine",  # 隔离有问题的数据，不阻止运行
        industry_source="exact_intervals",
        auction_policy="quarantine",  # 同样用隔离模式
        data_profile="full",
        auto_evolve=False,  # 不自动演化，避免生成未验证的新结构
        mode="engineering",  # 工程模式加速
        n_boot=200,
        n_placebo=150,
        n_trees=50,
        n_splits=5
    )

    run_id = f"competition-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"

    print("=" * 80)
    print("北京大学金融AI智能体创新大赛 - AutoAlpha Harness")
    print("=" * 80)
    print(f"运行ID: {run_id}")
    print(f"数据范围: {config.start} 至 {config.end} (A段探索)")
    print(f"最大结构数: {args.max_structures}")
    print(f"工作进程: {args.workers}")
    print(f"模式: 工程加速模式（用于展示）")
    print("=" * 80)
    print()
    print("重要说明：")
    print("1. 本运行仅使用A段数据进行探索和测量")
    print("2. B段和H段保持封存，未进行正式确认")
    print("3. 所有输出标注为'研究证据'而非'正式因子'")
    print("4. 统计检验使用加速参数（150次安慰剂，200次bootstrap，安慰剂>=100以避免untested短路）")
    print("5. 数据质量问题采用隔离模式（quarantine），标记但不阻止运行")
    print("=" * 80)
    print()

    try:
        run_research(
            config,
            run_id,
            args.data_root,
            args.output_root,
            discovery=False,  # 不运行发现层（避免生成新结构）
            bayes=False  # 不运行贝叶斯层次模型（避免过拟合）
        )
        print()
        print("=" * 80)
        print("研究运行完成！")
        print(f"输出目录: {args.output_root / run_id}")
        print("=" * 80)
        return 0
    except Exception as exc:
        print()
        print("=" * 80)
        print(f"研究运行失败: {type(exc).__name__}: {exc}")
        print("=" * 80)
        import traceback
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
