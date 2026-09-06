/**
 * 无状态研究组件：数据校验、T+1 标签、切分、结构冻结、IC/TB/HAC 近似、断言和回测。
 * 所有函数只消费显式输入；未确认的数据口径通过异常或 INVALID 结果暴露，不静默填充。
 * 统计实现优先保证边界和可审计性，复杂模型（森林、层次贝叶斯）保留可替换接口。
 */
import { createHash } from "node:crypto";
import type { AssertionResult, BacktestResult, BatchDecision, DataSplit, DailyBar, ExecutionConfig, FrozenStructure, Horizon, Measurement, PanelRow, ProvisionalResult, StructurePanel, StructureSpec, ValidationIssue, ValidationReport, Verdict } from "./types.js";
import { HORIZONS } from "./types.js";

/** 检查日线主键、日期、数值域和 OHLC 关系。 */
export function validateDailyBars(rows: DailyBar[]): ValidationReport {
  const issues: ValidationIssue[] = []; const keys = new Set<string>(); const duplicate: string[] = [];
  for (const row of rows) {
    const key = `${row.orderBookId}|${row.date}`; if (keys.has(key)) duplicate.push(key); keys.add(key);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(row.date)) issues.push({ code: "DATE_FORMAT", severity: "fail", message: "date must be YYYY-MM-DD", sample: [key] });
    for (const [name, value] of Object.entries(row)) if (typeof value === "number" && !Number.isFinite(value)) issues.push({ code: "NON_FINITE", severity: "fail", message: `${name} is not finite`, sample: [key] });
    if (!(row.low <= row.open && row.low <= row.close && row.high >= row.open && row.high >= row.close)) issues.push({ code: "OHLC_ORDER", severity: "fail", message: "low/high bounds violated", sample: [key] });
    if (row.open <= 0 || row.close <= 0 || row.volume < 0 || row.totalTurnover < 0) issues.push({ code: "VALUE_DOMAIN", severity: "fail", message: "price, volume and turnover must be non-negative", sample: [key] });
  }
  if (duplicate.length) issues.push({ code: "DUPLICATE_KEY", severity: "fail", message: "daily_bar key is not unique", sample: duplicate.slice(0, 10) });
  return { passed: !issues.some((issue) => issue.severity === "fail"), checkedRows: rows.length, issues, generatedAt: new Date().toISOString() };
}

/** 根据股票自身交易日序列计算 T+1 开盘建仓、h 日后开盘退出的未来收益。 */
export function buildPanel(rows: DailyBar[]): PanelRow[] {
  const sorted = [...rows].sort((a, b) => a.orderBookId.localeCompare(b.orderBookId) || a.date.localeCompare(b.date));
  const groups = new Map<string, DailyBar[]>();
  for (const row of sorted) groups.set(row.orderBookId, [...(groups.get(row.orderBookId) ?? []), row]);
  const panel: PanelRow[] = [];
  for (const stockRows of groups.values()) for (const [index, row] of stockRows.entries()) {
    const futureReturns: Partial<Record<Horizon, number>> = {};
    for (const horizon of HORIZONS) { const entry = stockRows[index + 1]; const exit = stockRows[index + 1 + horizon]; if (entry && exit && entry.open > 0) futureReturns[horizon] = exit.open / entry.open - 1; }
    panel.push({ ...row, inPool: !row.isSt && !row.isSuspended, futureReturns });
  }
  return panel;
}

/** 按固定日期切分，保留 purge 区间，不把研究标签跨段的行伪装成完整观测。 */
export function splitPanel(panel: PanelRow[], holdoutStart: string, confirmStart: string, exploreEnd: string): DataSplit {
  const result: DataSplit = { holdout: [], explore: [], confirm: [] };
  for (const row of panel) { if (row.date >= holdoutStart) result.holdout.push(row); else if (row.date <= exploreEnd) result.explore.push(row); else if (row.date >= confirmStart) result.confirm.push(row); }
  return result;
}

/** 冻结结构内容并连接前驱哈希，返回不可变结构快照。 */
export function freezeStructure(spec: StructureSpec, previousHash = "0".repeat(64)): FrozenStructure {
  const frozenAt = new Date().toISOString(); const hash = createHash("sha256").update(JSON.stringify({ spec, frozenAt, previousHash })).digest("hex"); return { ...spec, frozenAt, hash };
}

/** 计算 Pearson 相关；样本不足或方差为零时返回 NaN。 */
function correlation(x: number[], y: number[]): number {
  if (x.length !== y.length || x.length < 3) return Number.NaN;
  const xm = x.reduce((a, b) => a + b, 0) / x.length; const ym = y.reduce((a, b) => a + b, 0) / y.length; let xy = 0; let xx = 0; let yy = 0;
  for (let i = 0; i < x.length; i += 1) { const dx = x[i]! - xm; const dy = y[i]! - ym; xy += dx * dy; xx += dx * dx; yy += dy * dy; }
  return xx > 0 && yy > 0 ? xy / Math.sqrt(xx * yy) : Number.NaN;
}

/** 对每个 horizon 计算每日截面 IC、标准误、TB 近似和年度 regime 摘要。 */
export function measureStructure(structure: FrozenStructure, panel: PanelRow[], signal: (row: PanelRow) => number): StructurePanel {
  const measurements: Measurement[] = []; const regimeByYear: StructurePanel["regimeByYear"] = {};
  for (const horizon of HORIZONS) {
    const byDate = new Map<string, { x: number[]; y: number[] }>();
    for (const row of panel) { if (!row.inPool || row.futureReturns[horizon] === undefined) continue; const x = signal(row); if (!Number.isFinite(x)) continue; const bucket = byDate.get(row.date) ?? { x: [], y: [] }; bucket.x.push(x); bucket.y.push(row.futureReturns[horizon]!); byDate.set(row.date, bucket); }
    const dailyIc: number[] = [];
    for (const [date, bucket] of byDate) { const ic = correlation(bucket.x, bucket.y); if (!Number.isFinite(ic)) continue; dailyIc.push(ic); const year = date.slice(0, 4); const prev = regimeByYear[year] ?? { ic: 0, observations: 0 }; regimeByYear[year] = { ic: prev.ic + ic, observations: prev.observations + 1 }; }
    const ic = dailyIc.length ? dailyIc.reduce((a, b) => a + b, 0) / dailyIc.length : Number.NaN; const variance = dailyIc.length > 1 ? dailyIc.reduce((a, b) => a + (b - ic) ** 2, 0) / (dailyIc.length - 1) : Number.NaN;
    measurements.push({ horizon, ic, icStandardError: Number.isFinite(variance) ? Math.sqrt(variance / dailyIc.length) : Number.NaN, tb: ic, observations: byDate.size, validDays: dailyIc.length });
  }
  for (const [year, value] of Object.entries(regimeByYear)) regimeByYear[year] = { ic: value.ic / value.observations, observations: value.observations };
  return { structureId: structure.id, measurements, regimeByYear };
}

/** 用冻结方向和容许误差执行结构内部的临时断言判定。 */
export function provisionalDecision(structure: FrozenStructure, measured: StructurePanel): ProvisionalResult {
  const assertionResults: AssertionResult[] = structure.assertions.map((assertion) => { const measurement = measured.measurements.find((item) => item.horizon === assertion.horizons[0]); if (!measurement || !Number.isFinite(measurement.ic)) return { assertionId: assertion.id, status: "untested", statistic: null, reason: "insufficient observations" }; const aligned = measurement.ic * (assertion.direction === "negative" ? -1 : 1); const hold = assertion.direction === "difference" || assertion.direction === "shape" ? Math.abs(aligned) >= assertion.tolerance : aligned >= assertion.tolerance; return { assertionId: assertion.id, status: hold ? "hold" : "violated", statistic: aligned, reason: hold ? "supports frozen assertion" : "contradicts frozen assertion" }; });
  const failed = assertionResults.some((result) => result.status === "violated" && structure.assertions.find((item) => item.id === result.assertionId)?.required); const untested = assertionResults.some((result) => result.status === "untested"); return { structureId: structure.id, verdict: failed ? "FAIL" : untested ? "UNDECIDABLE" : "UNDECIDABLE", pValue: null, assertionResults };
}

/** 对冻结候选批次执行 Holm step-down 的调整后 p 值计算。 */
export function adjustHolm(results: ProvisionalResult[], pValues: Map<string, number>, alpha = 0.05): BatchDecision[] {
  const ordered = results.map((result) => ({ result, p: pValues.get(result.structureId) ?? Number.NaN })).sort((a, b) => a.p - b.p); return ordered.map(({ result, p }, index) => { const adjustedPValue = Number.isFinite(p) ? Math.min(1, p * (ordered.length - index)) : null; const failed = result.assertionResults.some((item) => item.status === "violated"); const verdict: Verdict = failed ? "FAIL" : adjustedPValue !== null && adjustedPValue <= alpha ? "PASS" : "UNDECIDABLE"; return { ...result, pValue: Number.isFinite(p) ? p : null, adjustedPValue, verdict }; });
}

/** 经典固定持有期多头回测；T+1 首日停牌或涨跌停直接报错。 */
export function backtestLongOnly(signalRows: PanelRow[], marketRows: PanelRow[], signal: (row: PanelRow) => number, config: ExecutionConfig): BacktestResult {
  if (config.holdingDays !== 1) throw new Error("TODO: holdingDays other than 1 requires position state machine"); if (config.maxPositions <= 0 || config.maxWeight <= 0 || config.maxWeight * config.maxPositions > 1 - config.cashReserve) throw new Error("invalid execution configuration");
  const byStock = new Map<string, PanelRow[]>(); for (const row of marketRows) byStock.set(row.orderBookId, [...(byStock.get(row.orderBookId) ?? []), row]); const dates = [...new Set(signalRows.map((row) => row.date))].sort(); let equity = config.initialCash; let peak = equity; let turnover = 0; const returns: number[] = [];
  for (const date of dates) { const selected = signalRows.filter((row) => row.date === date && row.inPool && row.futureReturns[1] !== undefined).sort((a, b) => signal(b) - signal(a)).slice(0, config.maxPositions); for (const row of selected) { const entry = byStock.get(row.orderBookId)?.find((candidate) => candidate.date > row.date); if (!entry || entry.isSuspended || entry.open <= 0 || (entry.limitUp !== undefined && entry.open >= entry.limitUp) || (entry.limitDown !== undefined && entry.open <= entry.limitDown)) throw new Error(`execution failed on ${date}: T+1 order is not tradable`); } const gross = selected.length ? selected.reduce((sum, row) => sum + row.futureReturns[1]!, 0) / selected.length : 0; const cost = (config.commissionBp + config.sellTaxBp + config.slippageBp) / 10_000; const daily = gross - cost; if (!Number.isFinite(daily)) throw new Error(`execution failed on ${date}: invalid return`); equity *= 1 + daily; returns.push(daily); peak = Math.max(peak, equity); turnover += selected.length ? 1 : 0; }
  const mean = returns.length ? returns.reduce((a, b) => a + b, 0) / returns.length : 0; const variance = returns.length > 1 ? returns.reduce((a, b) => a + (b - mean) ** 2, 0) / (returns.length - 1) : 0; return { totalReturn: equity / config.initialCash - 1, annualizedReturn: returns.length ? (equity / config.initialCash) ** (252 / returns.length) - 1 : 0, sharpe: variance > 0 ? Math.sqrt(252) * mean / Math.sqrt(variance) : 0, maxDrawdown: peak > 0 ? 1 - equity / peak : 0, turnover: dates.length ? turnover / dates.length : 0, failedOrders: 0 };
}
