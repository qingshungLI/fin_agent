"""自助研究 SDK：校验用户面板、冻结格子、训练段选择子结构、封存验证段评估并导出。

与比赛批次隔离；仅复用受限 DSL，不读取项目行情或调用外部模型。所有价格须由用户
提供同口径调整价格。快速模式用于候选筛查，输出不等同于可成交收益或正式统计确认。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from time import perf_counter
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from engine.dsl import compile_expression, evaluate


class CellSpec(BaseModel):
    """定义自有研究格子；输入名称、机制描述、表达式和周期，假设字段在收盘已可得。"""
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(min_length=1, max_length=100)
    mechanism: str = Field(min_length=1, max_length=500)
    expression: str = Field(min_length=1, max_length=1000)
    horizon: int = Field(default=5, ge=1, le=20)


class ExperimentSpec(BaseModel):
    """冻结研究预算和时间切分；输入格子列表及成本，返回配置，验证段不用于择优。"""
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(default="我的因子研究", min_length=1, max_length=100)
    cells: list[CellSpec] = Field(min_length=1, max_length=16)
    profile: Literal["fast", "balanced"] = "fast"
    evolve: bool = True
    train_fraction: float = Field(default=.65, ge=.5, le=.75)
    one_way_cost_bp: float = Field(default=8, ge=0, le=100)
    seed: int = Field(default=42, ge=0)


def write_json(path: Path, value: object) -> None:
    """原子发布 JSON；输入路径和可序列化对象，拒绝非有限浮点，返回 None。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def normalize(frame: pd.DataFrame) -> pd.DataFrame:
    """验证长表并规范日期；输入 date/symbol/open/close 面板，返回副本，不修补错误价格。"""
    needed = {"date", "symbol", "open", "close"}
    if not needed.issubset(frame.columns):
        raise ValueError("必需列：date、symbol、open、close；请先完成列名映射")
    if frame.empty or len(frame) > 500_000 or len(frame.columns) > 40:
        raise ValueError("面板需为 1 至 500000 行、最多 40 列")
    if frame.columns.has_duplicates or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,49}", str(c)) for c in frame.columns):
        raise ValueError("列名必须唯一，且为英文标识符")
    result = frame.copy()
    if result[list(needed)].isna().any().any():
        raise ValueError("主键或开收盘价格缺失；请处理后重新导入，不会自动填充")
    result["date"] = pd.to_datetime(result.date, errors="raise")
    if result.date.dt.tz is not None or not result.date.eq(result.date.dt.normalize()).all():
        raise ValueError("date 必须为无时区的日频日期")
    result["symbol"] = result.symbol.astype(str).str.strip()
    if result.symbol.eq("").any() or result.duplicated(["date", "symbol"]).any():
        raise ValueError("证券代码不能为空，date+symbol 不得重复")
    for name in result.columns.difference(["date", "symbol"]):
        result[name] = pd.to_numeric(result[name], errors="raise")
        if np.isinf(result[name].to_numpy()).any():
            raise ValueError(f"{name} 包含无限值")
    if (result[["open", "close"]] <= 0).any().any():
        raise ValueError("开收盘价格必须严格为正")
    if result.date.nunique() < 100 or result.symbol.nunique() < 10:
        raise ValueError("至少需要 100 个交易日和 10 只证券")
    if result.date.nunique() * result.symbol.nunique() > 2_000_000:
        raise ValueError("日历与证券的面板乘积超过 200 万；请缩小本次自助任务范围")
    return result.sort_values(["date", "symbol"], kind="stable").reset_index(drop=True)


def panel_fields(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """将规范长表对齐为字段矩阵并派生历史收益；输入已验证面板，返回不填补停牌缺口的字段。"""
    fields = {name: frame.pivot(index="date", columns="symbol", values=name)
              for name in frame.columns if name not in {"date", "symbol"}}
    for name in ("ret_1d", "ret_5d", "ret_20d"):
        if name in fields:
            raise ValueError(f"{name} 为 SDK 保留派生字段，请重命名上传列")
    for days in (1, 5, 20):
        fields[f"ret_{days}d"] = fields["close"].pct_change(days, fill_method=None)
    fields["in_pool"] = fields["close"].notna()
    return fields


def dataset_summary(frame: pd.DataFrame) -> dict:
    """汇总数据准入信息；输入原始长表，返回字段、覆盖和价格口径待核验提示。"""
    checked = normalize(frame)
    fields = panel_fields(checked)
    return {"rows": len(checked), "dates": int(checked.date.nunique()),
            "symbols": int(checked.symbol.nunique()), "start": str(checked.date.min().date()),
            "end": str(checked.date.max().date()), "fields": sorted(fields),
            "missing_cells": int(checked.isna().sum().sum()),
            "price_basis": "user_declared_adjusted", "point_in_time_verified": False,
            "limitations": ["用户必须确保价格复权口径一致、字段在当日收盘已知", "尚未验证停牌、涨跌停、幸存者偏差及公司行为"]}


def daily_ic(signal: pd.DataFrame, labels: pd.DataFrame) -> pd.Series:
    """计算每日截面 Rank IC；输入对齐信号和收益，至少十个成对观测，并列按平均秩。"""
    mask = signal.notna() & labels.notna()
    left, right = signal.where(mask).rank(axis=1), labels.where(mask).rank(axis=1)
    return left.corrwith(right, axis=1).where(mask.sum(axis=1) >= 10)


def mean_or_none(values: pd.Series) -> float | None:
    """汇总有限均值；输入日序列，无有效观测返回 None，避免把未知显示为零。"""
    values = values.replace([np.inf, -np.inf], np.nan).dropna()
    return float(values.mean()) if len(values) else None


def ic_interval(values: pd.Series, horizon: int, repeats: int, seed: int) -> list[float] | None:
    """按连续日期块估计描述性区间；输入 IC、周期和预算，返回区间，不校正候选多重搜索。"""
    array = values.to_numpy(dtype=float)
    block = max(5, horizon + 1)
    if np.isfinite(array).sum() < 20 or len(array) < block:
        return None
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(array) - block + 1, size=(repeats, int(np.ceil(len(array) / block))))
    sampled = array[(starts[..., None] + np.arange(block)).reshape(repeats, -1)[:, :len(array)]]
    valid = np.isfinite(sampled).any(axis=1)
    if valid.sum() < .95 * repeats:
        return None
    means = np.nanmean(sampled[valid], axis=1)
    return np.quantile(means, [.025, .975]).tolist()


def target_weights(signal: pd.DataFrame) -> pd.DataFrame:
    """冻结的顶部分位多头投影；输入信号，返回单股至多 5% 的目标，常量截面保持现金。"""
    rank = signal.rank(axis=1, pct=True, method="average")
    chosen = rank.ge(.8) & signal.notna()
    chosen = chosen.where(signal.nunique(axis=1) > 1, False)
    count = chosen.sum(axis=1)
    return chosen.mul((.95 / count.replace(0, np.nan)).clip(upper=.05).fillna(0), axis=0)


def backtest(target: pd.DataFrame, returns: pd.DataFrame, cost_bp: float) -> tuple[pd.DataFrame, dict]:
    """估计逐日目标收益与净额成本；输入 T+1 开盘收益，含期末平仓，缺收益不伪造净值。"""
    changes = target - target.shift(1, fill_value=0)
    transfer = changes.abs().sum(axis=1)
    transfer.iloc[-1] += target.iloc[-1].sum()
    missing = ((target > 0) & returns.isna()).any(axis=1)
    gross = (target * returns.fillna(0)).sum(axis=1).mask(missing)
    net = gross - transfer * cost_bp / 10000
    valid = not missing.any() and not (net <= -1).any()
    nav = (1 + net).cumprod() if valid else pd.Series(np.nan, index=net.index)
    daily = pd.DataFrame({"net_return": net, "nav": nav, "target_transfer": transfer,
                          "exposure": target.sum(axis=1)})
    return daily, {"total_return": float(nav.iloc[-1] - 1) if valid else None,
                   "max_drawdown": float((nav / nav.cummax().clip(lower=1) - 1).min()) if valid else None,
                   "mean_transfer": float(transfer.mean()), "mean_exposure": float(target.sum(axis=1).mean()),
                   "missing_return_days": int(missing.sum()), "execution_verified": False,
                   "scope": "T+1 adjusted-open research proxy; daily rebalance, target-transfer costs"}


def run_experiment(frame: pd.DataFrame, spec: ExperimentSpec, output: str | Path) -> dict:
    """运行用户数据研究；输入长表和冻结配置，返回独立报告；目录必须新建，验证段不参与演化。"""
    begin = perf_counter()
    checked = normalize(frame)
    fields = panel_fields(checked)
    for cell in spec.cells:
        compile_expression(cell.expression, set(fields), {})
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=False)
    dates = fields["close"].index
    boundary = int(len(dates) * spec.train_fraction)
    purge = max(cell.horizon for cell in spec.cells) + 1
    if boundary - purge < 40 or len(dates) - boundary - purge < 20:
        raise ValueError("切分后有效训练或验证日期不足")
    source_hash = hashlib.sha256(pd.util.hash_pandas_object(checked, index=False).values.tobytes()).hexdigest()
    source_files = [Path(__file__), Path(__file__).parents[1] / "engine/dsl.py"]
    write_json(destination / "frozen.json", {"spec": spec.model_dump(), "data_hash": source_hash,
        "data_columns": list(checked.columns), "validation_start": str(dates[boundary].date()),
        "purge_days": purge, "code_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files},
        "evolution_operator": "top two training-only parents; lag 1 and historical smoothing 3; depth one",
        "formal": False})
    report = {"name": spec.name, "status": "RUNNING", "profile": spec.profile,
              "dataset": dataset_summary(checked), "validation_start": str(dates[boundary].date()),
              "results": [], "formal": False, "llm_used": False, "selection": "training_only",
              "quality_policy": "validation observations are descriptive; external replication required"}
    write_json(destination / "report.json", report)
    cache: dict[str, pd.DataFrame] = {}
    candidates: list[tuple[str, CellSpec, str | None]] = []
    train_scores: dict[str, float | None] = {}
    seen: set[tuple[str, int]] = set()

    def register(cell: CellSpec, parent: str | None) -> None:
        """登记唯一表达式周期对；输入格子及父 ID，无返回，训练打分只读边界前已实现标签。"""
        key = (cell.expression, cell.horizon)
        if key in seen:
            return
        seen.add(key)
        if cell.expression not in cache:
            cache[cell.expression] = evaluate(cell.expression, fields)
        signal = cache[cell.expression]
        labels = fields["open"].shift(-(cell.horizon + 1)) / fields["open"].shift(-1) - 1
        score = mean_or_none(daily_ic(signal, labels).iloc[:boundary - purge])
        cid = f"C{len(candidates)+1:03d}"
        candidates.append((cid, cell, parent))
        train_scores[cid] = score

    try:
        for cell in spec.cells:
            register(cell, None)
        if spec.evolve:
            parents = sorted(candidates, key=lambda item: -(train_scores[item[0]] if train_scores[item[0]] is not None else -2))[:2]
            for cid, cell, _ in parents:
                if train_scores[cid] is None:
                    continue
                for expression in (f"lag({cell.expression}, 1)", f"ts_mean({cell.expression}, 3)"):
                    register(cell.model_copy(update={"name": cell.name + " · 演化", "expression": expression}), cid)
        write_json(destination / "candidates.json", [{"id": cid, **cell.model_dump(), "parent": parent,
                   "train_ic": train_scores[cid]} for cid, cell, parent in candidates])
        # 候选全集先冻结，然后才计算任何验证段诊断，避免验证段引导子结构。
        chosen_id = max(train_scores, key=lambda cid: train_scores[cid] if train_scores[cid] is not None else -2)
        for cid, cell, parent in candidates:
            started = perf_counter()
            signal = cache[cell.expression]
            labels = fields["open"].shift(-(cell.horizon + 1)) / fields["open"].shift(-1) - 1
            ic = daily_ic(signal, labels).iloc[boundary:-(cell.horizon + 1)]
            val_signal = signal.iloc[boundary:-2]
            target = target_weights(val_signal)
            returns = (fields["open"].shift(-2) / fields["open"].shift(-1) - 1).reindex_like(target)
            daily, metrics = backtest(target, returns, spec.one_way_cost_bp)
            _, stress = backtest(target, returns, spec.one_way_cost_bp * 2)
            # 用当日可得证券构造同暴露基准，避免把市场普涨或低仓位当作选股收益。
            available = fields["close"].reindex_like(target).notna()
            benchmark_target = available.mul(target.sum(axis=1).div(available.sum(axis=1).replace(0, np.nan)).fillna(0), axis=0)
            benchmark_daily, benchmark = backtest(benchmark_target, returns, spec.one_way_cost_bp)
            excess_return = (float(daily.nav.iloc[-1] / benchmark_daily.nav.iloc[-1] - 1)
                             if metrics["total_return"] is not None and benchmark["total_return"] is not None else None)
            interval = ic_interval(ic, cell.horizon, 100 if spec.profile == "fast" else 500, spec.seed)
            similarities = []
            for other_id, other_cell, _ in candidates:
                if other_id == cid:
                    break
                similarity = mean_or_none(daily_ic(signal.iloc[:boundary - purge], cache[other_cell.expression].iloc[:boundary - purge]))
                if similarity is not None:
                    similarities.append((other_id, similarity))
            closest = max(similarities, key=lambda pair: abs(pair[1])) if similarities else None
            folder = destination / cid
            folder.mkdir()
            target.to_parquet(folder / "target.parquet")
            signal.to_parquet(folder / "factor.parquet")
            daily.to_parquet(folder / "daily.parquet")
            ic.to_frame("rank_ic").to_parquet(folder / "ic.parquet")
            blocks = [ic.iloc[positions] for positions in np.array_split(np.arange(len(ic)), 3)]
            block_means = [mean_or_none(part) for part in blocks]
            val_ic = mean_or_none(ic)
            warnings = []
            if ic.notna().sum() < 20:
                warnings.append("有效验证 IC 日期不足 20")
            if val_signal.notna().to_numpy().mean() < .5:
                warnings.append("验证段信号覆盖不足一半")
            if interval is None or interval[0] <= 0:
                warnings.append("描述性 IC 区间未排除零或样本不足")
            if excess_return is None or excess_return <= 0:
                warnings.append("同暴露等权基准之上的净收益未显示支持")
            if closest and abs(closest[1]) >= .98:
                warnings.append("与已登记候选训练信号高度相似，需检查增量价值")
            if val_ic is None or val_ic <= 0:
                warnings.append("验证段 IC 未显示正向支持")
            if any(value is None or value <= 0 for value in block_means):
                warnings.append("验证子区间方向不稳定或样本不足")
            if metrics["total_return"] is None or metrics["total_return"] <= 0:
                warnings.append("成本后收益未通过研究筛查")
            if stress["total_return"] is None or stress["total_return"] <= 0:
                warnings.append("双倍成本压力下未通过研究筛查")
            item = {"id": cid, **cell.model_dump(), "parent": parent, "train_ic": train_scores[cid],
                    "validation_ic": val_ic, "ic_interval": interval,
                    "validation_blocks": block_means, "valid_ic_dates": int(ic.notna().sum()),
                    "coverage": float(val_signal.notna().to_numpy().mean()),
                    "backtest": metrics, "double_cost_return": stress["total_return"],
                    "benchmark": benchmark, "excess_return": excess_return,
                    "closest_training_signal": {"id": closest[0], "correlation": closest[1]} if closest else None,
                    "warnings": warnings, "quality": "NEEDS_REVIEW" if warnings else "REPLICATION_CANDIDATE",
                    "seconds": perf_counter() - started, "selected_on_train": cid == chosen_id,
                    "nav": [{"date": str(date.date()), "value": None if pd.isna(value) else float(value)}
                            for date, value in daily.nav.items()]}
            report["results"].append(item)
            report["elapsed_seconds"] = perf_counter() - begin
            write_json(destination / "report.json", report)
        report.update(status="COMPLETED", elapsed_seconds=perf_counter() - begin,
                      selected_id=chosen_id, candidate_count=len(candidates),
                      engine="custom-data SDK / deterministic one-generation evolution")
        write_json(destination / "report.json", report)
        pd.DataFrame([{k: item[k] for k in ("id", "name", "expression", "parent", "train_ic", "validation_ic", "quality")}
                      for item in report["results"]]).to_csv(destination / "factors.csv", index=False, encoding="utf-8-sig")
        write_json(destination / "artifact-hashes.json", {str(p.relative_to(destination)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in destination.rglob("*") if p.is_file() and p.name != "artifact-hashes.json"})
        return report
    except Exception as exc:
        report.update(status="FAILED", error=str(exc), elapsed_seconds=perf_counter() - begin)
        write_json(destination / "report.json", report)
        raise