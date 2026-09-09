/** 格式化可选测量值；无效或缺失值保留为未知，不填零。 */
export function number(value: number | null | undefined, digits = 4): string {
  return value == null || !Number.isFinite(value)
    ? '—'
    : value.toLocaleString('zh-CN', { maximumFractionDigits: digits });
}

/** 将快照时间转换为浏览器本地时间；非法日期保留未知，不采用当前时间替代。 */
export function timestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '未记录' : date.toLocaleString('zh-CN', { hour12: false });
}
