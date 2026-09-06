/** 后端组件共享的数据契约。日期为 ISO 字符串，价格为人民币元，收益率为小数。 */

export const HORIZONS = [1, 3, 5, 10] as const;
export type Horizon = (typeof HORIZONS)[number];
export type Verdict = "PASS" | "FAIL" | "UNDECIDABLE" | "INVALID";

export interface DailyBar {
  orderBookId: string; date: string; open: number; high: number; low: number;
  close: number; prevClose: number; volume: number; totalTurnover: number;
  isSt: boolean; isSuspended: boolean; limitUp?: number; limitDown?: number;
}
export interface PanelRow extends DailyBar {
  inPool: boolean; futureReturns: Partial<Record<Horizon, number>>;
}
export interface DataSource { loadDailyBars(): Promise<DailyBar[]>; }
export interface ValidationIssue { code: string; severity: "warning" | "fail"; message: string; sample?: string[]; }
export interface ValidationReport { passed: boolean; checkedRows: number; issues: ValidationIssue[]; generatedAt: string; }
export interface DataSplit { holdout: PanelRow[]; explore: PanelRow[]; confirm: PanelRow[]; }
export interface AssertionSpec {
  id: string; subject: string; relation: string; value: string | number | number[];
  direction: "positive" | "negative" | "difference" | "shape";
  tolerance: number; horizons: Horizon[]; required: boolean; scope: string;
}
export interface StructureSpec {
  id: string; coord: [string, string]; labels: Record<string, string>;
  assertions: AssertionSpec[]; expressionName: string; coverage: string;
  lineage: { origin: "manual" | "forest" | "transplant"; parent?: string };
}
export interface FrozenStructure extends StructureSpec { frozenAt: string; hash: string; }
export interface Measurement { horizon: Horizon; ic: number; icStandardError: number; tb: number; observations: number; validDays: number; }
export interface StructurePanel { structureId: string; measurements: Measurement[]; regimeByYear: Record<string, { ic: number; observations: number }>; }
export interface AssertionResult { assertionId: string; status: "hold" | "violated" | "untested"; statistic: number | null; reason: string; }
export interface ProvisionalResult { structureId: string; verdict: Verdict; pValue: number | null; assertionResults: AssertionResult[]; }
export interface BatchDecision extends ProvisionalResult { adjustedPValue: number | null; }
export interface ExecutionConfig {
  initialCash: number; maxPositions: number; maxWeight: number; cashReserve: number;
  commissionBp: number; sellTaxBp: number; slippageBp: number; holdingDays: number;
}
export interface BacktestResult { totalReturn: number; annualizedReturn: number; sharpe: number; maxDrawdown: number; turnover: number; failedOrders: number; }
