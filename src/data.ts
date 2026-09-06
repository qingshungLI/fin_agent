/**
 * 数据组件：读取 daily_bar 分区并执行结构与业务边界检查。
 * 真实供应商字段映射集中在本文件，未知语义不会被静默转换；尚未接入的表在报告中明确标记。
 */
import { readdir } from "node:fs/promises";
import { join } from "node:path";
import { ParquetReader } from "parquetjs-lite";
import type { DataSource, DailyBar, ValidationIssue, ValidationReport } from "./types.js";

function numberField(row: Record<string, unknown>, name: string, key: string): number {
  const value = row[name];
  if (typeof value !== "number" || !Number.isFinite(value)) throw new Error(`${key}.${name} must be a finite number`);
  return value;
}
function optionalNumber(row: Record<string, unknown>, name: string): number | undefined {
  const value = row[name]; return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}
function booleanField(row: Record<string, unknown>, name: string, key: string): boolean {
  const value = row[name];
  if (typeof value !== "boolean") throw new Error(`${key}.${name} must be boolean after explicit state join`);
  return value;
}

/** 读取 daily_bar 年度分区；limit 仅用于受控诊断，正式运行不应设置。 */
export class DailyBarParquetSource implements DataSource {
  public constructor(private readonly root: string, private readonly limit?: number) {}
  public async loadDailyBars(): Promise<DailyBar[]> {
    const files = (await readdir(this.root, { withFileTypes: true }))
      .filter((entry) => entry.isDirectory() && /^year=\d{4}$/.test(entry.name))
      .map((entry) => join(this.root, entry.name, "data.parquet")).sort();
    if (files.length === 0) throw new Error(`no daily_bar partitions found: ${this.root}`);
    const output: DailyBar[] = [];
    for (const file of files) {
      const reader = await ParquetReader.openFile(file);
      try {
        const cursor = reader.getCursor(); let raw: Record<string, unknown> | null;
        while ((raw = await cursor.next()) !== null) {
          const orderBookId = String(raw.order_book_id ?? ""); const date = String(raw.date ?? "").slice(0, 10); const key = `${orderBookId}|${date}`;
          if (!orderBookId || !/^\d{4}-\d{2}-\d{2}$/.test(date)) throw new Error(`${key}: invalid identity/date`);
          const limitUp = optionalNumber(raw, "limit_up");
          const limitDown = optionalNumber(raw, "limit_down");
          output.push({ orderBookId, date, open: numberField(raw, "open", key), high: numberField(raw, "high", key), low: numberField(raw, "low", key), close: numberField(raw, "close", key), prevClose: numberField(raw, "prev_close", key), volume: numberField(raw, "volume", key), totalTurnover: numberField(raw, "total_turnover", key), isSt: false, isSuspended: false, ...(limitUp === undefined ? {} : { limitUp }), ...(limitDown === undefined ? {} : { limitDown }) });
          if (this.limit !== undefined && output.length >= this.limit) return output;
        }
      } finally { await reader.close(); }
    }
    return output;
  }
}

/** 检查日线主键、数值域和 OHLC 关系；未接入的关联表在 issues 中明确列为 warning。 */
export function validateDailyBars(rows: DailyBar[]): ValidationReport {
  const issues: ValidationIssue[] = []; const keys = new Set<string>(); const duplicate: string[] = [];
  for (const row of rows) {
    const key = `${row.orderBookId}|${row.date}`; if (keys.has(key)) duplicate.push(key); keys.add(key);
    if (!(row.low <= row.open && row.low <= row.close && row.high >= row.open && row.high >= row.close)) issues.push({ code: "OHLC_ORDER", severity: "fail", message: "low/high bounds violated", sample: [key] });
    if (row.open <= 0 || row.close <= 0 || row.volume < 0 || row.totalTurnover < 0) issues.push({ code: "VALUE_DOMAIN", severity: "fail", message: "price/volume/turnover domain violated", sample: [key] });
  }
  if (duplicate.length) issues.push({ code: "DUPLICATE_KEY", severity: "fail", message: "daily_bar key is not unique", sample: duplicate.slice(0, 10) });
  issues.push({ code: "UNJOINED_STATE_TABLES", severity: "warning", message: "st_flag/suspension joins are not yet attached by this source" });
  issues.push({ code: "UNJOINED_CORPORATE_ACTIONS", severity: "warning", message: "adj_factor/dividend/split joins are not yet attached; returns are not production-safe" });
  return { passed: !issues.some((issue) => issue.severity === "fail"), checkedRows: rows.length, issues, generatedAt: new Date().toISOString() };
}
