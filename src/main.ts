/**
 * 真实后端流程入口：读取 daily_bar -> 数据校验 -> T+1 面板 -> 研究切分 -> 结构冻结 -> 测量 -> 回测。
 * 默认要求显式传入 --data-root；没有完整状态、复权和行业组件时只输出 INVALID，禁止生成伪研究结论。
 */
import { resolve } from "node:path";
import { DailyBarParquetSource, validateDailyBars } from "./data.js";
import { backtestLongOnly, buildPanel, freezeStructure, measureStructure, provisionalDecision, splitPanel } from "./core.js";
import type { DataSource, PanelRow } from "./types.js";

/** 运行真实数据流程；当前 DataSource 只提供 daily_bar，未完成的关联表会阻止生产研究。 */
export async function run(source: DataSource, options: { production: boolean }): Promise<void> {
  const raw = await source.loadDailyBars(); const validation = validateDailyBars(raw); if (!validation.passed) throw new Error(`data validation failed: ${JSON.stringify(validation.issues)}`);
  if (options.production) throw new Error("INVALID: production mode requires PIT state, corporate-action and industry components; wire them before research");
  const panel = buildPanel(raw); const split = splitPanel(panel, "2025-08-01", "2022-07-22", "2022-06-30");
  const structure = freezeStructure({ id: "S-MANUAL-001", coord: ["M2", "F3"], labels: { agent: "liquidity_provider", friction: "inventory_risk", mispricing: "temporary_impact", correction: "inventory_unwind", form: "F3" }, assertions: [{ id: "P1", subject: "effect_sign", relation: "=", value: "negative", direction: "negative", tolerance: 0, horizons: [1], required: true, scope: "in_pool" }], expressionName: "neg(ret_5d)", coverage: "in_pool", lineage: { origin: "manual" } });
  const signal = (row: PanelRow): number => { const stock = raw.find((item) => item.orderBookId === row.orderBookId && item.date === row.date); if (!stock || stock.prevClose <= 0) return Number.NaN; return -(stock.close / stock.prevClose - 1); };
  const measured = measureStructure(structure, split.explore, signal); const provisional = provisionalDecision(structure, measured); const backtest = backtestLongOnly(split.explore, panel, signal, { initialCash: 1_000_000, maxPositions: 20, maxWeight: 0.05, cashReserve: 0.1, commissionBp: 2, sellTaxBp: 5, slippageBp: 2, holdingDays: 1 }); console.log(JSON.stringify({ status: "research_scaffold", validation, rows: raw.length, splitSizes: { holdout: split.holdout.length, explore: split.explore.length, confirm: split.confirm.length }, structure, measured, provisional, backtest }, null, 2));
}

const root = process.argv.find((value) => value === "--data-root") ? process.argv[process.argv.indexOf("--data-root") + 1] : undefined; if (root) await run(new DailyBarParquetSource(resolve(root, "daily_bar"), undefined), { production: process.argv.includes("--production") });
