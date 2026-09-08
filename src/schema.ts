/** 前后端契约：所有研究结果来自冻结 JSON；前端不执行统计计算。 */
export type Verdict = 'PASS' | 'FAIL' | 'UNDECIDABLE';
export type CellStatus = 'unexplored' | 'infeasible' | 'deferred_horizon' | 'deferred_data' | 'deferred_implementation';
export interface MapCell { id: string; family: string; family_name: string; form: number; form_name: string; status: CellStatus; reason: string }
export interface Curve { expression: number; horizon: number; mean: number | null; se: number | null; n_eff: number | null; mde: number | null; t: number | null; p: number; tb: number | null; raw_ic: number | null; groups: number[] }
export interface AssertionResult { id: string; kind: string; subject: string; state: 'hold' | 'violated' | 'untested'; detail: unknown; attribution: string }
export interface Structure { id: string; name: string; family: string; form: number; hash: string; verdict: Verdict; formal: boolean; measurement: { curves: Curve[]; monthly: unknown[]; concentration: Record<string, number | null>; coverage: number; hit_rate: number }; blades: { gate: string; reason?: string; assertions: AssertionResult[]; placebo: { state: string }; increment: { state: string } } }
export interface Overview { run_id?: string; status: string; message?: string; dates?: number; symbols?: number; report?: Array<{ name: string; status: string; count: number; detail?: string }>; map: MapCell[]; power?: Record<string, number> }
export interface Audit { valid: boolean; events: number; structures: number; anchor: string; access: Array<{ segment: string; timestamp: string }> }
