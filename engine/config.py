"""研究配置管线：验证显式参数，固定交易日周期与 A/B/H 边界，供数据和检验共享。

所有随机数、检验次数与成本在读取收益前登记。快速模式仅用于工程验收，禁止正式确认。
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[1]
HORIZONS = (1, 3, 5, 10)
EXPLORE_END = "2022-06-30"
CONFIRM_START = "2022-07-22"
CONFIRM_END = "2025-07-31"
HOLDOUT_START = "2025-08-01"
HOLDOUT_END = "2026-07-29"
SLOTS = ("agent", "friction", "mispricing", "correction", "form")


class ResearchConfig(BaseModel):
    """验证运行参数并返回冻结配置；正式模式遵守 v5 检验规模。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    start: str = "2016-07-01"
    end: str = EXPLORE_END
    max_symbols: int = Field(default=0, ge=0, le=6000)
    seed: int = Field(default=20260907, ge=0)
    n_boot: int = Field(default=1000, ge=100, le=10000)
    n_placebo: int = Field(default=500, ge=99, le=2000)
    n_trees: int = Field(default=500, ge=10, le=2000)
    n_splits: int = Field(default=20, ge=2, le=50)
    max_structures: int = Field(default=4, ge=1, le=30)
    min_effect: float = Field(default=0.05, gt=0, lt=1)
    min_dates: int = Field(default=200, ge=40)
    min_cross_section: int = Field(default=30, ge=10)
    commission_bp: float = Field(default=3, ge=0, le=100)
    slippage_bp: float = Field(default=5, ge=0, le=100)
    workers: int = Field(default=2, ge=1, le=8)
    mode: Literal["formal", "engineering"] = "formal"
    provider: Literal["manual", "llm", "hybrid"] = "manual"
    industry_policy: Literal["strict", "quarantine"] = "strict"
    industry_source: Literal["exact_intervals", "rqdata_daily"] = "exact_intervals"
    auction_policy: Literal["strict", "quarantine"] | None = None
    cache: bool = True

    @model_validator(mode="after")
    def validate_protocol(self) -> "ResearchConfig":
        """检查日期和正式规模；参数来自模型，返回自身，禁止 A 段越界。"""
        from datetime import date

        start, end = date.fromisoformat(self.start), date.fromisoformat(self.end)
        if start < date(2016, 7, 1) or end > date.fromisoformat(EXPLORE_END) or start >= end:
            raise ValueError("探索日期必须位于 2016-07-01 至 2022-06-30 且开始早于结束")
        if self.mode == "formal" and (
            self.n_boot < 1000 or self.n_placebo < 500
            or self.n_trees < 500 or self.n_splits < 20
        ):
            raise ValueError("正式模式要求 bootstrap>=1000、安慰剂>=500、树>=500、切分>=20")
        return self
