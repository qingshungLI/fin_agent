/** 组合视图：真实研究快照驱动成分、gate、成本和执行状态，未知业绩不显示为零。 */
import { useState } from 'react';
import { ArrowRight, Download, GitBranch, LockKeyhole, ShieldCheck } from 'lucide-react';
import type { CompositionReport, Result } from './control-types';

const names: Record<string, string> = { parallel: '等资本并联', conflict_cash: '冲突区域空仓', consensus: '至少两结构同向' };
const reasons: Record<string, string> = { parallel: '沿用各结构覆盖 · 在持仓路径层合并', conflict_cash: '相反方向同时生效 → 当前证券空仓', consensus: '至少两个独立构造同向，且不存在反向票' };
const number = (n?: number | null, digits = 2) => n == null ? '—' : n.toLocaleString('zh-CN', { maximumFractionDigits: digits });

/** 显示一个组合批次；输入真实报告与结构档案，返回规则并列比较和审计下载。 */
export default function CompositionView({ reports, rows }: { reports: CompositionReport[]; rows: Result[] }) {
  const [chosen, setChosen] = useState('');
  const report = reports.find(r => r.batch_id === chosen) || reports[0];
  if (!report) return <section className="c-panel c-empty"><GitBranch size={30} /><h2>等待组合研究快照</h2><p>组合按已提交结构生成，单结构研究继续运行。尚无产物时不展示假组合。</p></section>;
  return <section className="c-composition"><div className="c-panel"><div className="c-heading"><div><span>COMPOSITION / MULTI-STRUCTURE GATES</span><h2>多结构组合与门控</h2></div><select className="c-composition-select" aria-label="选择组合批次" value={report.batch_id} onChange={e => setChosen(e.target.value)}>{reports.map(r => <option value={r.batch_id} key={r.batch_id}>{r.batch_id}</option>)}</select></div>
    <div className="c-limitations"><ShieldCheck size={17} /><div><b>{report.status === 'RUNNING' ? '组合计算进行中' : report.status === 'FAILED' ? '组合运行失败' : '组合研究产物已生成'} · {report.source_ids.length} 个源结构</b><p>固定选择最先完成的源结构，不按 IC 或收益择优。三套规则在组合收益计算前冻结，全部属于 A 段研究，不代表正式可交易组合。</p>{report.error && <p>{report.error.message}</p>}</div></div>
    <div className="c-composition-sources">{report.source_ids.map((id, i) => { const source = rows.find(r => r.id === id); return <div key={id}><span className="c-tag">{source ? `${source.family} · F${source.form}` : `S${i + 1}`}</span><b>{source?.name || id}</b><small>原 gate → {source?.spec.primary_horizon || '—'} 日持仓路径</small></div>; })}</div>
    <div className="c-loop-return"><GitBranch size={15} />保留各结构适用范围 <ArrowRight size={13} />重复定义合并 <ArrowRight size={13} />跨结构 gate <ArrowRight size={13} />仓位与现金约束</div>
  </div><div className="c-composition-variants">{['parallel', 'conflict_cash', 'consensus'].map((name, i) => { const item = report.variants[name]; return <article className="c-panel" key={name}><div className="c-heading"><div><span>RULE 0{i + 1}</span><h2>{names[name]}</h2></div><GitBranch size={17} /></div><p className="c-muted">{reasons[name]}</p>
    {!item ? <div className="c-empty"><p>该规则正在等待计算</p></div> : <><div className="c-combo-exposure"><span>平均多头目标暴露</span><strong>{number(item.mean_exposure * 100)}<small>%</small></strong><div className="c-progress"><i style={{ width: `${item.mean_exposure * 100}%` }} /></div></div>
      <dl className="c-combo-stats"><div><dt>独立构造成分</dt><dd>{item.independent_components}</dd></div><div><dt>信号交易日</dt><dd>{number(item.dates, 0)}</dd></div><div><dt>平均持仓数量</dt><dd>{number(item.mean_held_stocks)}</dd></div><div><dt>平均冲突证券</dt><dd>{number(item.mean_conflict_stocks)}</dd></div><div><dt>平均 gate 关闭证券</dt><dd>{number(item.mean_gate_closed_stocks)}</dd></div><div><dt>日均权重转移代理</dt><dd>{number(item.metrics?.mean_daily_target_transfer)}</dd></div><div><dt>日均固定成本代理</dt><dd>{item.metrics ? number(item.metrics.mean_daily_cost_proxy * 10000, 3) + ' bp' : '—'}</dd></div><div><dt>组合成本变化（总权重比例）</dt><dd>{number(item.cost_comparison?.cost_difference, 5)}</dd></div></dl>
      <div className="c-combo-result"><span>完整 A 段研究净收益估计</span><b>{item.metrics?.research_total_return == null ? '不可完整估计' : number(item.metrics.research_total_return * 100) + '%'}</b><small>{item.metrics?.state === 'INVALID_RETURN_COVERAGE' ? `${number(item.metrics.missing_held_returns)} 条持仓收益缺失，未填零或拼接净值。` : '调整开盘价与固定权重转移成本；不是实际成交净值。'}</small></div>
      <div className="c-combo-execution"><span>真实 RQAlpha 执行</span><b>{item.execution?.status === 'COMPLETED' ? '执行完成' : item.execution?.status === 'FAILED' ? '执行失败，保留原因' : '待执行或执行中'}</b>{item.execution_failure && <p>{item.execution_failure}</p>}</div>
      <div className="c-combo-downloads"><a href={`/api/control/composition-artifact/${report.batch_id}/${name}/target.parquet`} download><Download size={13} />目标持仓</a><a href={`/api/control/composition-artifact/${report.batch_id}/${name}/routing.json`} download><Download size={13} />门控规则</a><a href={`/api/control/composition-artifact/${report.batch_id}/${name}/contributions.parquet`} download><Download size={13} />成分贡献</a></div>
    </>}</article>; })}</div><div className="c-panel c-limitations"><LockKeyhole size={17} /><div><b>正式组合资格：尚未获得</b><p>{report.confirmation.reason}</p><p>相交、共识等新增 gate 需要独立组合检验。目标转移量重算成本已实现；拒单、停牌、涨跌停与公司行为由真实执行回放单独验收。</p></div></div></section>;
}