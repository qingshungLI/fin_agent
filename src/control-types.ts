/** 控制面板契约：所有数值由只读后端提供，缺失值保持空白，不生成演示业绩。 */
export interface Cell { id: string; family: string; family_name: string; form: number; form_name: string; reason: string; display_state: 'active' | 'measured' | 'rejected' | 'pending'; structures: string[] }
export interface Spec { id: string; name: string; family: string; form: number; mechanism: string; operational: string[]; primary_horizon: number; coverage: string; assertions: { id: string; subject: string; attribution: string; kind: string }[]; lineage: { parent?: string; donor?: string; operator?: string; depth?: number } }
export interface Result { id: string; name: string; family: string; form: number; verdict: string; formal: boolean; spec: Spec; primary: { mean?: number; n_eff?: number; p?: number }; blades: { placebo?: { state: string; reason?: string; tests?: { kind: string; state: string; p?: number; spectral_error?: number }[] }; assertions?: { id: string; state: string; subject: string }[] }; confirmation: { reasons?: string[] }; cost: { net_top_excess_mean?: number }; curves: { expression: number; horizon: number; mean: number | null; ci_low?: number; ci_high?: number }[]; seconds?: number }
export interface Snapshot {
  run_id: string; status: string; started_at?: string; observed_at: string;
  config: { max_structures: number; n_boot: number; n_placebo: number; n_trees: number; n_splits: number; llm_max_calls: number; auto_evolve: boolean; start: string; end: string; mode: string };
  model: { model?: string; reasoning_effort?: string };
  counts: { attempts: number; budget: number; measured: number; inherited: number; rejected: number; cells: number; children: number; formal: number };
  panel: { dates?: number; symbols?: number }; map: Cell[]; rows: Result[];
  current: { id?: string; cell?: string; spec?: Spec; frozen: boolean; bets: Record<string, { probability: number }> };
  queue: Record<string, number>; log: { events: { id: number; kind: string; text: string }[]; requests: number | null; roles: Record<string, { requests: number; responses: number }>; truncated: boolean; updated_at?: string };
  quality: { name: string; status: string; count: number; detail?: string; formal_eligible?: boolean }[];
  validation: { status?: string; steps?: { name: string; status: string; started_at?: string; finished_at?: string }[] };
  memory: { state?: string; reason?: string; terms?: { group: string; name: string; mean: number; interpretable: boolean }[] };
  pipeline: { stages?: Record<string, { status: string; reasons?: string[]; reason?: string }>; B_read?: boolean; H_read?: boolean };
  audit: { valid: boolean | null; events: number; anchor?: string; access: { segment: string }[] };
  control?: { action: string; updated_at?: string; source?: string };
}
export interface Run { id: string; status: string; started_at: string; measured: number }
/** 组合研究摘要：实际成分/门控/成本与执行状态，未通过独立确认不标为正式。 */
export interface CompositionReport {
  batch_id: string; source_run: string; status: string; source_ids: string[]; formal: boolean;
  created_at: string; error?: { message: string }; confirmation: { status: string; reason: string };
  variants: Record<string, {
    status: string; independent_components: number; dates: number; symbols: number;
    mean_conflict_stocks: number; mean_gate_closed_stocks: number; mean_held_stocks: number; mean_exposure: number;
    aliases: Record<string, string>; new_hypothesis: boolean;
    metrics?: { state: string; mean_daily_target_transfer: number; mean_daily_cost_proxy: number;
      research_total_return: number | null; research_max_drawdown: number | null; missing_held_returns: number; execution_verified: boolean };
    cost_comparison?: { component_equal_capital_cost?: number; combined_cost?: number; cost_difference?: number };
    execution?: { status: string; exit_code: number }; execution_failure?: string;
  }>;
}
