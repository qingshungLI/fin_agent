/** 工作台 UI 管线：读取后端产物，展示地图覆盖、数据质量、统计功效、结构断言和审计链。 */
import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, ArrowRight, CheckCircle2, CircleAlert, Database, LockKeyhole, ShieldCheck } from 'lucide-react';
import type { Audit, Overview, Structure } from './schema';
import './styles.css';

const fallback: Overview = { status: 'LOADING', map: [] };
function App() {
  const [overview, setOverview] = useState<Overview>(fallback);
  const [structures, setStructures] = useState<Structure[]>([]);
  const [audit, setAudit] = useState<Audit | null>(null);
  useEffect(() => {
    Promise.all([fetch('/api/overview').then((r) => r.json()), fetch('/api/structures').then((r) => r.json()), fetch('/api/audit').then((r) => r.json()).catch(() => null)])
      .then(([nextOverview, nextStructures, nextAudit]) => { setOverview(nextOverview); setStructures(nextStructures); setAudit(nextAudit); });
  }, []);
  const feasible = overview.map.filter((cell) => cell.status !== 'infeasible');
  const explored = new Set(structures.map((item) => `${item.family}-F${item.form}`));
  const latest = structures[0];
  return <div className="shell">
    <header><div className="brand"><span className="mark">A</span><div><p className="eyebrow">RESEARCH OPERATING SYSTEM</p><h1>AutoAlpha <span>因子研究工作台</span></h1></div></div><div className="header-meta"><span className="live"><i /> {overview.status}</span><span>2026.09.07 · 日频 A 股</span></div></header>
    <main>
      <section className="hero"><div><p className="eyebrow">FALSIFICATION DRIVEN</p><h2>把“看起来有效”变成<br /><em>可审计的研究结论</em></h2><p className="hero-copy">事前冻结机制与断言，按真实有效样本量测量，在确认样本上控制全库错误率。系统保留失败，也保留不知道。</p></div><div className="hero-stat"><strong>{overview.map.length || 70}</strong><span>想法空间格子</span><small>{feasible.length || 52} 个可行 · {explored.size} 个已探索</small></div></section>
      <section className="status-grid"><Status icon={<Database />} label="数据层" value={overview.report?.length ? `${overview.report.filter((r) => r.status === 'pass').length}/${overview.report.length} checks` : '待运行'} tone={overview.report?.some((r) => r.status === 'fail') ? 'bad' : 'good'} /><Status icon={<Activity />} label="研究状态" value={overview.status} tone={overview.status === 'MEASURED' ? 'good' : 'warn'} /><Status icon={<ShieldCheck />} label="正式 PASS" value={structures.filter((s) => s.formal && s.verdict === 'PASS').length.toString()} tone="good" /><Status icon={<LockKeyhole />} label="审计链" value={audit?.valid ? `${audit.events} events` : '未锚定'} tone={audit?.valid ? 'good' : 'warn'} /></section>
      <section className="workspace"><div className="panel map-panel"><PanelTitle eyebrow="01 · IDEA SPACE" title="机制地图" note="10 × 7 · 事前枚举" /><div className="map-grid">{overview.map.map((cell) => <div key={cell.id} className={`map-cell ${cell.status} ${explored.has(cell.id) ? 'explored' : ''}`} title={cell.reason}><span>{cell.family}</span><b>F{cell.form}</b>{explored.has(cell.id) && <i />}</div>)}</div><div className="legend"><span><i className="dot explored-dot" />已探索</span><span><i className="dot" />待研究</span><span><i className="dot blocked-dot" />机制不可行</span></div></div><div className="panel focus-panel"><PanelTitle eyebrow="02 · CURRENT EVIDENCE" title="当前结构" note={latest?.id || '尚未运行'} />{latest ? <><div className="structure-title"><span className="family-tag">{latest.family} · F{latest.form}</span><h3>{latest.name}</h3><p>{latest.blades.reason}</p></div><div className="metrics-row"><Metric label="覆盖度" value={`${(latest.measurement.coverage * 100).toFixed(1)}%`} /><Metric label="命中率" value={`${(latest.measurement.hit_rate * 100).toFixed(1)}%`} /><Metric label="结论" value={latest.verdict} accent={latest.verdict === 'PASS' ? 'green' : 'amber'} /></div><div className="assertions">{latest.blades.assertions.map((item) => <div className="assertion" key={item.id}><span className={`assertion-state ${item.state}`} /> <b>{item.id}</b><span>{item.subject}</span><strong>{item.state}</strong></div>)}</div><button className="text-button">查看完整测量 <ArrowRight size={15} /></button></> : <EmptyState />}</div></section>
      <section className="lower-grid"><div className="panel quality"><PanelTitle eyebrow="03 · DATA QUALITY" title="数据质量闸门" note="未知口径不填零" />{overview.report?.slice(0, 7).map((row) => <div className="quality-row" key={row.name}><span className={`q-icon ${row.status}`}><CheckCircle2 size={14} /></span><span>{row.name}</span><small>{row.count.toLocaleString()}</small><b className={row.status}>{row.status}</b></div>) || <EmptyState />}</div><div className="panel power"><PanelTitle eyebrow="04 · POWER BUDGET" title="先算账，再搜索" note="交互检验门槛" /><div className="power-number"><strong>{overview.power?.interaction_mde?.toFixed(3) || '—'}</strong><span>确认段最小可检出交互效应</span></div><p>探索段只用于发现，确认段只读取一次。若功效不足，系统返回 UNDECIDABLE，不降低阈值制造方向。</p><div className="power-bar"><i style={{ width: `${Math.min(100, (overview.power?.projected_confirm_n_eff || 0) / 30)}%` }} /></div><small>确认侧 n_eff · {overview.power?.projected_confirm_n_eff?.toFixed(0) || '等待测量'}</small></div></section>
    </main><footer><span>AutoAlpha Harness v5 · research artifacts are immutable</span><span>数据源：本地 Parquet · 研究层与交易层单向</span></footer>
  </div>;
}
function Status({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: string; tone: string }) { return <div className="status-card"><span className={`status-icon ${tone}`}>{icon}</span><div><small>{label}</small><strong>{value}</strong></div></div>; }
function PanelTitle({ eyebrow, title, note }: { eyebrow: string; title: string; note: string }) { return <div className="panel-title"><div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2></div><span>{note}</span></div>; }
function Metric({ label, value, accent }: { label: string; value: string; accent?: string }) { return <div className="metric"><small>{label}</small><strong className={accent || ''}>{value}</strong></div>; }
function EmptyState() { return <div className="empty"><CircleAlert size={18} /><span>尚未产生可展示的结构产物</span></div>; }
export default App;
const root = document.getElementById('root');
if (!root) throw new Error('缺少应用挂载节点');
createRoot(root).render(<App />);
