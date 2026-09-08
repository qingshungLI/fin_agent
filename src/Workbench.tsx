/** 工作台 UI 管线：读取后端产物，展示地图覆盖、数据质量、统计功效、结构断言和审计链。 */
import { useEffect, useState } from 'react';

import { Activity, ArrowRight, CheckCircle2, CircleAlert, Database, LockKeyhole, ShieldCheck } from 'lucide-react';
import type { Audit, Overview, Structure } from './schema';
import './styles.css';

const fallback: Overview = { status: 'LOADING', map: [] };
function App() {
  const [overview, setOverview] = useState<Overview>(fallback);
  const [structures, setStructures] = useState<Structure[]>([]);
  const [audit, setAudit] = useState<Audit | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [details, setDetails] = useState(false);
  const [error, setError] = useState('');
  const [launchState, setLaunchState] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [jobs, setJobs] = useState<{id:string;status:string}[]>([]);
  async function launchRun(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSubmitting(true); setLaunchState('正在提交到服务器…');
    try {
      const response = await fetch('/api/jobs', {method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({provider:form.get('provider'),max_symbols:Number(form.get('symbols')),
          max_structures:Number(form.get('structures')),workers:4,
          data_profile:form.get('dataProfile'),discovery:form.get('discovery') === 'on',bayes:form.get('bayes') === 'on',
          engineering:form.get('mode') === 'engineering',industry_policy:form.get('policy'), industry_source:form.get('industrySource'),
          auction_policy:form.get('auctionPolicy') === 'inherit' ? null : form.get('auctionPolicy')})});
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '参数无效');
      setLaunchState('已提交：' + result.id);
      setJobs(previous => [result, ...previous]);
    } catch (e) { setLaunchState(e instanceof Error ? e.message : '提交失败'); }
    finally { setSubmitting(false); }
  }
  useEffect(() => {
    let alive = true;
    async function readEndpoint(path: string) {
      const response = await fetch(path);
      if (!response.ok) throw new Error('研究服务读取失败');
      return response.json();
    }
    const refresh = () => {
      fetch('/api/jobs').then(r => r.ok ? r.json() : []).then(rows => {if(alive) setJobs(rows);}).catch(() => {});
      return Promise.all([readEndpoint('/api/overview'), readEndpoint('/api/structures'), readEndpoint('/api/audit').catch(() => null)])
      .then(([nextOverview, nextStructures, nextAudit]) => {
        if (!Array.isArray(nextOverview.map) || !Array.isArray(nextStructures)) throw new Error('研究产物格式不正确');
        if (alive) { setOverview(nextOverview); setStructures(nextStructures); setAudit(nextAudit); setError(''); }
      }).catch(() => { if (alive) setError('研究服务暂时不可用，正在重连'); });
    };
    refresh();
    const interval = window.setInterval(refresh, 5000);
    return () => { alive = false; window.clearInterval(interval); };
  }, []);
  const feasible = overview.map.filter((cell) => cell.status === 'unexplored');
  const explored = new Set(structures.map((item) => `${item.family}-F${item.form}`));
  const latest = structures.find(s => s.id === selected) || structures.at(-1);
  return <div className="shell">
    <header><div className="brand"><span className="mark">A</span><div><p className="eyebrow">RESEARCH OPERATING SYSTEM</p><h1>AutoAlpha <span>因子研究工作台</span></h1></div></div><div className="header-meta"><span className="live"><i /> {overview.status}</span><span>2026.09.07 · 日频 A 股</span></div></header>
    <main>
      {error && <p role="alert" className="runtime-notice">{error}</p>}
      <section className="runtime-notice" aria-live="polite">
        <strong>{overview.run_id || '尚无研究批次'}</strong>
        <span> {overview.symbols || 0} 只股票 · {overview.dates || 0} 个交易日 · {structures.length} 个研究结构</span>
        <p>{overview.message || '等待服务器研究结果'}</p>
      </section>
      <section className="panel launch-panel">
        <h2>启动服务器研究</h2>
        <p>所有计算在服务器执行。快速检查用于验证流程；完整检验仍须通过数据质量和独立确认。</p>
        <form onSubmit={launchRun} className="run-form">
          <label>想法来源<select name="provider" defaultValue="llm"><option value="llm">DeepSeek 生成</option><option value="hybrid">基线 + DeepSeek 演化</option><option value="manual">固定基线</option></select></label>
          <label>股票数量（0 为全部）<input name="symbols" type="number" min="0" max="6000" defaultValue="600" required /></label>
          <label>结构数量<input name="structures" type="number" min="1" max="1000" defaultValue="1" required /></label>
          <label>检验规模<select name="mode" defaultValue="engineering"><option value="engineering">快速检查</option><option value="formal">完整检验</option></select></label>
          <label>研究数据<select name="dataProfile" defaultValue="daily"><option value="daily">日线与成交，不含竞价</option><option value="full">包含开盘竞价</option></select></label>
          <label>条件发现<input name="discovery" type="checkbox" /></label>
          <label>贝叶斯研究记忆<input name="bayes" type="checkbox" /></label>
          <label>行业来源<select name="industrySource" defaultValue="rqdata_daily"><option value="rqdata_daily">RQData 逐日直接查询</option><option value="exact_intervals">原始历史区间</option></select></label>
          <label>竞价处理<select name="auctionPolicy" defaultValue="inherit"><option value="inherit">随数据处理方式</option><option value="strict">严格校验</option><option value="quarantine">隔离异常，仅供探索</option></select></label>
          <label>数据处理<select name="policy" defaultValue="strict"><option value="strict">严格校验</option><option value="quarantine">隔离异常，仅供探索</option></select></label>
          <button type="submit" disabled={submitting || ['RUNNING','STARTING'].includes(overview.status) || jobs.some(j => ['QUEUED','RUNNING'].includes(j.status))}>开始研究</button>
        </form>
        <p role="status">{launchState}</p>
        {jobs.slice(0,3).map(j => <p key={j.id}>{j.id} · {j.status}</p>)}
      </section>
      <section className="hero"><div><p className="eyebrow">FALSIFICATION DRIVEN</p><h2>把“看起来有效”变成<br /><em>可审计的研究结论</em></h2><p className="hero-copy">事前冻结机制与断言，按真实有效样本量测量，在确认样本上控制全库错误率。系统保留失败，也保留不知道。</p></div><div className="hero-stat"><strong>{overview.map.length || 70}</strong><span>想法空间格子</span><small>{feasible.length || 70} 个可行 · {explored.size} 个已探索</small></div></section>
      <section className="status-grid"><Status icon={<Database />} label="数据层" value={overview.report?.length ? `${overview.report.filter((r) => r.status === 'pass').length}/${overview.report.length} checks` : '待运行'} tone={overview.report?.some((r) => r.status === 'fail') ? 'bad' : 'good'} /><Status icon={<Activity />} label="研究状态" value={overview.status} tone={overview.status === 'MEASURED' ? 'good' : 'warn'} /><Status icon={<ShieldCheck />} label="正式 PASS" value={structures.filter((s) => s.formal && s.verdict === 'PASS').length.toString()} tone="good" /><Status icon={<LockKeyhole />} label="审计链" value={audit?.valid ? `${audit.events} events` : '未锚定'} tone={audit?.valid ? 'good' : 'warn'} /></section>
      <section className="workspace"><div className="panel map-panel"><PanelTitle eyebrow="01 · IDEA SPACE" title="机制地图" note="10 × 7 · 事前枚举" /><div className="map-grid">{overview.map.map((cell) => <div key={cell.id} className={`map-cell ${cell.status} ${explored.has(cell.id) ? 'explored' : ''}`} title={cell.reason}><span>{cell.family}</span><b>F{cell.form}</b>{explored.has(cell.id) && <i />}</div>)}</div><div className="legend"><span><i className="dot explored-dot" />已探索</span><span><i className="dot" />待研究</span><span><i className="dot blocked-dot" />机制不可行</span></div></div><div className="panel focus-panel"><PanelTitle eyebrow="02 · CURRENT EVIDENCE" title="当前结构" note={latest?.id || '尚未运行'} />{latest ? <><div className="structure-title"><span className="family-tag">{latest.family} · F{latest.form}</span><h3>{latest.name}</h3><p>{latest.blades.reason}</p></div><div className="metrics-row"><Metric label="覆盖度" value={`${(latest.measurement.coverage * 100).toFixed(1)}%`} /><Metric label="命中率" value={`${(latest.measurement.hit_rate * 100).toFixed(1)}%`} /><Metric label="结论" value={{PASS:'已确认',FAIL:'已证伪',UNDECIDABLE:'未能判定'}[latest.verdict]} accent={latest.verdict === 'PASS' ? 'green' : 'amber'} /></div><div className="assertions">{latest.blades.assertions.map((item) => <div className="assertion" key={item.id}><span className={`assertion-state ${item.state}`} /> <b>{item.id}</b><span>{item.subject}</span><strong>{item.state}</strong></div>)}</div><button className="text-button" onClick={() => setDetails(!details)}>{details ? '收起测量' : '查看完整测量'} <ArrowRight size={15} /></button>
{details && <div className="measurement-table"><table><thead><tr><th>表达式</th><th>周期</th><th>IC</th><th>HAC t</th><th>最小可检出效应</th></tr></thead><tbody>{latest.measurement.curves.map(c => <tr key={c.expression + '-' + c.horizon}><td>{c.expression}</td><td>{c.horizon}日</td><td>{c.mean?.toFixed(4) ?? '—'}</td><td>{c.t?.toFixed(2) ?? '—'}</td><td>{c.mde?.toFixed(4) ?? '—'}</td></tr>)}</tbody></table></div>}</> : <EmptyState />}</div></section>
      <section className="panel structure-list"><h2>研究结构</h2>
        <p>以下为探索段结果；正式通过需要独立确认和数据质量验收。</p>
        {structures.map(s => <button key={s.id} onClick={() => {setSelected(s.id); setDetails(true);}}
          aria-pressed={latest?.id === s.id}>{s.name} · {s.verdict} · 安慰剂 {s.blades.placebo.state}</button>)}
      </section>
      <section className="lower-grid"><div className="panel quality"><PanelTitle eyebrow="03 · DATA QUALITY" title="数据质量闸门" note="未知口径不填零" />{overview.report?.slice(0, 7).map((row) => <div className="quality-row" key={row.name}><span className={`q-icon ${row.status}`}><CheckCircle2 size={14} /></span><span>{row.name}</span><small>{row.count.toLocaleString()}</small><b className={row.status}>{row.status}</b></div>) || <EmptyState />}</div><div className="panel power"><PanelTitle eyebrow="04 · POWER BUDGET" title="先算账，再搜索" note="交互检验门槛" /><div className="power-number"><strong>{overview.power?.interaction_mde?.toFixed(3) || '—'}</strong><span>确认段最小可检出交互效应</span></div><p>探索段只用于发现，确认段只读取一次。若功效不足，系统返回 UNDECIDABLE，不降低阈值制造方向。</p><div className="power-bar"><i style={{ width: `${Math.min(100, (overview.power?.projected_confirm_n_eff || 0) / 30)}%` }} /></div><small>确认侧 n_eff · {overview.power?.projected_confirm_n_eff?.toFixed(0) || '等待测量'}</small></div></section>
    </main><footer><span>AutoAlpha Harness v5 · research artifacts are immutable</span><span>数据源：本地 Parquet · 研究层与交易层单向</span></footer>
  </div>;
}
function Status({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: string; tone: string }) { return <div className="status-card"><span className={`status-icon ${tone}`}>{icon}</span><div><small>{label}</small><strong>{value}</strong></div></div>; }
function PanelTitle({ eyebrow, title, note }: { eyebrow: string; title: string; note: string }) { return <div className="panel-title"><div><p className="eyebrow">{eyebrow}</p><h2>{title}</h2></div><span>{note}</span></div>; }
function Metric({ label, value, accent }: { label: string; value: string; accent?: string }) { return <div className="metric"><small>{label}</small><strong className={accent || ''}>{value}</strong></div>; }
function EmptyState() { return <div className="empty"><CircleAlert size={18} /><span>尚未产生可展示的结构产物</span></div>; }
export default App;
