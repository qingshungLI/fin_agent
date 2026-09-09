/** 控制台入口：路由隔离、批次控制、证据浏览；研究计数与状态全部来自后端快照。 */
import { lazy, Suspense, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity,
  Box,
  Download,
  Expand,
  FileCheck2,
  GitBranch,
  Pause,
  Play,
  RotateCcw,
  Square,
  Terminal,
} from 'lucide-react';
import { useResearch } from './useResearch';
import { number, timestamp } from './format';
import type { Snapshot } from './control-types';
import './control.css';
import './console.css';
const ResearchScene = lazy(() => import('./ResearchScene'));
const EvidenceView = lazy(() => import('./EvidenceView'));
const CompositionView = lazy(() => import('./CompositionView'));
const SkillPanel = lazy(() => import('./SkillPanel'));
const Studio = lazy(() => import('./Studio'));
const Workbench = lazy(() => import('./Workbench'));
const tabs = [
  { id: 'overview', name: '运行总览', icon: Activity },
  { id: 'map', name: '机制地图', icon: Box },
  { id: 'evidence', name: '结构证据', icon: FileCheck2 },
  { id: 'compositions', name: '组合门控', icon: GitBranch },
  { id: 'events', name: '研究日志', icon: Terminal },
];
const states: Record<string, string> = {
  RUNNING: '研究运行中',
  PAUSED: '已暂停',
  COMPLETED: '已完成',
  FAILED: '运行失败',
  STOPPED: '已停止',
  INTERRUPTED: '进程中断',
  RESUMING: '恢复中',
};

/** 地图视图；输入快照，默认低开销二维模式，三维不可用时保留坐标入口。 */
function Landscape({ snapshot }: { snapshot: Snapshot }) {
  const [selected, setSelected] = useState('');
  const [dimension, setDimension] = useState<'2d' | '3d'>('2d');
  const [reset, setReset] = useState(0);
  const cell =
    snapshot.map.find((item) => item.id === (selected || snapshot.current.cell)) || snapshot.map[0];
  const rows = snapshot.rows.filter(
    (row) => row.family === cell?.family && row.form === cell?.form,
  );
  const matrix = (
    <div className="c-matrix">
      {snapshot.map.map((item) => (
        <button
          aria-label={`${item.id} ${item.family_name}`}
          aria-pressed={item.id === cell?.id}
          className={`c-cell ${item.display_state}`}
          key={item.id}
          onClick={() => setSelected(item.id)}
        >
          <b>{item.id}</b>
          <small>{item.structures.length} 个结构</small>
        </button>
      ))}
    </div>
  );
  return (
    <section className="c-research-grid">
      <article className="c-panel c-map-panel">
        <div className="c-heading">
          <div>
            <span>RESEARCH LANDSCAPE</span>
            <h2>机制 × 表达形式</h2>
          </div>
          <div className="c-segment">
            {(['2d', '3d'] as const).map((mode) => (
              <button
                key={mode}
                aria-pressed={dimension === mode}
                onClick={() => setDimension(mode)}
              >
                {mode.toUpperCase()}
              </button>
            ))}
          </div>
        </div>
        <p className="c-muted">{snapshot.map.length} 个研究坐标；格子数量与有效因子数量不同。</p>
        {dimension === '2d' ? (
          matrix
        ) : (
          <div className="c-scene-wrap">
            <Suspense fallback={<p>加载三维地图…</p>}>
              <ResearchScene
                cells={snapshot.map}
                rows={snapshot.rows}
                selected={cell?.id}
                onSelect={setSelected}
                reset={reset}
                fallback={matrix}
              />
            </Suspense>
            <button className="c-text-button" onClick={() => setReset((value) => value + 1)}>
              复位三维视角
            </button>
          </div>
        )}
      </article>
      <article className="c-panel c-mechanism">
        <div className="c-heading">
          <h2>坐标档案</h2>
          <span className="c-tag">{cell?.id || '—'}</span>
        </div>
        <label className="a-label">
          选择研究坐标
          <select
            aria-label="选择研究坐标"
            value={cell?.id || ''}
            onChange={(event) => setSelected(event.target.value)}
          >
            {snapshot.map.map((item) => (
              <option key={item.id} value={item.id}>
                {item.id} · {item.family_name}
              </option>
            ))}
          </select>
        </label>
        <h3>{cell?.family_name}</h3>
        <p>{cell?.form_name}</p>
        <p className="c-muted">{cell?.reason}</p>
        {rows.length ? (
          rows.map((row) => (
            <div className="a-coordinate-result" key={row.id}>
              <b>{row.name}</b>
              <p>
                IC {number(row.primary.mean)} · {row.verdict}
              </p>
              <code className="c-code">{row.spec.operational[0]}</code>
            </div>
          ))
        ) : (
          <p className="c-muted">该坐标尚无已完成测量。</p>
        )}
      </article>
    </section>
  );
}

/** 概览仅呈现当前、下一步和边界；输入快照，返回无需滚动大量介绍的工作入口。 */
function Overview({ snapshot, navigate }: { snapshot: Snapshot; navigate: (tab: string) => void }) {
  const next =
    snapshot.status === 'RUNNING' || snapshot.status === 'RESUMING'
      ? '提交当前测量与诊断 → 更新研究记忆 → 调度下一个训练证据驱动的假设。'
      : snapshot.status === 'COMPLETED'
        ? '审查候选证据与缺失检验，决定是否启动独立确认和组合评估。'
        : '检查日志和冻结身份，在可恢复条件满足后继续研究。';
  return (
    <>
      <section className="a-overview">
        <article className="c-panel">
          <div className="c-heading">
            <div>
              <span>LIVE RESEARCH</span>
              <h2>当前正在做什么</h2>
            </div>
            <span className="c-tag">{states[snapshot.status] || snapshot.status}</span>
          </div>
          <h3>{snapshot.current.spec?.name || snapshot.current.id || '等待下一项任务'}</h3>
          <p className="c-live-event">{snapshot.log.events.at(-1)?.text || '尚无事件记录'}</p>
          <div className="a-metrics">
            <div>
              当前坐标<strong>{snapshot.current.cell || '—'}</strong>
            </div>
            <div>
              规格冻结<strong>{snapshot.current.frozen ? '已冻结' : '待冻结'}</strong>
            </div>
            <div>
              自动演化<strong>{snapshot.config.auto_evolve ? '已启用' : '未启用'}</strong>
            </div>
          </div>
          <div className="a-progress">
            <span
              style={{
                width: `${Math.min(100, Math.max(0, (snapshot.counts.attempts / Math.max(1, snapshot.counts.budget)) * 100))}%`,
              }}
            />
          </div>
          <p className="c-muted">
            已使用 {snapshot.counts.attempts} / {snapshot.counts.budget} 次尝试额度；并非成功率。
          </p>
        </article>
        <article className="c-panel">
          <div className="c-heading">
            <div>
              <span>NEXT DECISION</span>
              <h2>下一步研究</h2>
            </div>
            <GitBranch size={18} />
          </div>
          <p>{next}</p>
          <div className="a-metrics">
            <div>
              拒绝的提案<strong>{snapshot.counts.rejected}</strong>
            </div>
            <div>
              正式结果<strong>{snapshot.counts.formal}</strong>
            </div>
          </div>
          <button className="a-primary" onClick={() => navigate('evidence')}>
            审查结构证据
          </button>
          <button className="c-text-button" onClick={() => navigate('map')}>
            打开研究地图 →
          </button>
        </article>
      </section>
      <article className="c-panel a-protocol">
        <div>
          <span className="a-eyebrow">RSI / RECURSIVE SELF-IMPROVEMENT</span>
          <h2>研究假设递归改进，评估协议保持冻结</h2>
          <p className="c-muted">
            AI 提案与审查 → 编译冻结 → 测量与证伪 → 条件发现 →
            记忆与子代。子代必须重新检验；验证段不用于调度下一代。
          </p>
        </div>
        <div className="a-stage-grid">
          {Object.entries(snapshot.pipeline.stages || {}).map(([name, stage]) => (
            <div key={name}>
              <b>{name.replaceAll('_', ' ')}</b>
              <span>{stage.status}</span>
            </div>
          ))}
        </div>
        <details>
          <summary>查看数据、模型与审计信息</summary>
          <p>
            模型：{snapshot.model.model || '未记录'} · 数据：{number(snapshot.panel.dates, 0)} 日 /{' '}
            {number(snapshot.panel.symbols, 0)} 证券
          </p>
          <p>
            审计事件 {snapshot.audit.events} · 完整性{' '}
            {snapshot.audit.valid === null
              ? '未验证'
              : snapshot.audit.valid
                ? '已验证'
                : '验证失败'}{' '}
            · B/H 读取 {String(snapshot.pipeline.B_read ?? false)} /{' '}
            {String(snapshot.pipeline.H_read ?? false)}
          </p>
        </details>
      </article>
    </>
  );
}

/** 主控制台管理展示布局；研究状态和命令由独立 hook 维护。 */
function Dashboard() {
  const research = useResearch();
  const { snapshot, runs, runId, reports, error, notice, busy } = research;
  const [tab, setTab] = useState('overview');
  const [presentation, setPresentation] = useState(false);
  return (
    <div className={`control a-console ${presentation ? 'a-presentation' : ''}`}>
      <aside className="c-sidebar">
        <a className="c-brand" href="#">
          <span className="c-brand-mark">A</span>
          <div>
            AURORA<small>ALPHA HARNESS</small>
          </div>
        </a>
        <p className="c-nav-label">RESEARCH OPERATIONS</p>
        <nav>
          {tabs.map((item) => (
            <button
              className={tab === item.id ? 'active' : ''}
              key={item.id}
              onClick={() => setTab(item.id)}
            >
              <item.icon size={17} />
              {item.name}
            </button>
          ))}
        </nav>
        <div className="c-sidebar-bottom">
          <span>本地研究工作空间</span>
          <a href="#skill">Research Skill ↗</a>
          <a href="#studio">自有数据接入 ↗</a>
          <a href="#workbench">新建研究任务 ↗</a>
        </div>
      </aside>
      <div className="c-main">
        <header className="c-topbar">
          <div className="c-breadcrumb">
            工作空间 / <b>{tabs.find((item) => item.id === tab)?.name}</b>
          </div>
          <div className="c-top-actions">
            <span className={`c-connection ${error ? 'offline' : ''}`}>
              {error ? '连接异常 · 保留上次快照' : snapshot ? '实时同步 · 5 秒' : '等待批次'}
            </span>
            <button
              className="c-icon-button"
              aria-label="Refresh"
              title="刷新"
              onClick={research.refresh}
            >
              <RotateCcw size={16} />
            </button>
            <button
              className="c-text-button"
              aria-label={presentation ? '退出展示' : '评委展示模式'}
              onClick={() => setPresentation((value) => !value)}
            >
              <Expand size={16} />
              {presentation ? '退出展示' : '展示模式'}
            </button>
          </div>
        </header>
        <main className="c-content">
          <section className="c-page-title">
            <div>
              <p className="c-eyebrow">AUDITABLE ALPHA RESEARCH</p>
              <h1>自动演化研究控制台</h1>
              <p>从机制假设到可复核证据，持续推进下一轮研究。</p>
            </div>
            <label className="c-run-picker">
              当前研究批次
              <select
                disabled={busy}
                aria-label="当前研究批次"
                value={runId}
                onChange={(event) => research.selectRun(event.target.value)}
              >
                {!runs.length && <option value="">暂无批次</option>}
                {runs.map((run) => (
                  <option key={run.id} value={run.id}>
                    {run.id}
                  </option>
                ))}
              </select>
            </label>
          </section>
          {error && (
            <div className="c-alert" role="alert">
              {error}。请检查研究服务；现有快照可能已过期。
            </div>
          )}
          {notice && (
            <p className="a-notice" role="status">
              {notice}
            </p>
          )}
          {!snapshot ? (
            <section className="c-panel c-empty">
              <h2>{error ? '暂时无法读取研究' : '等待研究批次'}</h2>
              <p>可以新建研究任务，或通过 Skill 接入自己的数据。</p>
              <a className="a-primary" href="#workbench">
                新建研究任务
              </a>
            </section>
          ) : (
            <>
              {snapshot.config.mode === 'fast' && (
                <div className="c-alert">
                  FAST 探索 · {snapshot.config.n_placebo} 次横截面诊断 · 不授予正式
                  PASS；独立确认状态请查看证据。
                </div>
              )}
              <section className="a-runbar">
                <div>
                  <span className="c-tag">{states[snapshot.status] || snapshot.status}</span>
                  <small title={snapshot.observed_at}>
                    更新于 {timestamp(snapshot.observed_at)}
                  </small>
                </div>
                <div className="c-run-control-buttons">
                  <button
                    disabled={busy || !['RUNNING', 'RESUMING'].includes(snapshot.status)}
                    onClick={() => research.action('pause')}
                  >
                    <Pause size={14} />
                    暂停
                  </button>
                  <button
                    disabled={
                      busy ||
                      !['PAUSED', 'STOPPED', 'FAILED', 'INTERRUPTED'].includes(snapshot.status)
                    }
                    onClick={() => research.action('resume')}
                  >
                    <Play size={14} />
                    继续
                  </button>
                  <button
                    disabled={busy || !['RUNNING', 'PAUSED', 'RESUMING'].includes(snapshot.status)}
                    onClick={() => research.action('stop')}
                  >
                    <Square size={14} />
                    停止
                  </button>
                </div>
              </section>
              <section className="c-kpis">
                {[
                  ['研究尝试', `${snapshot.counts.attempts} / ${snapshot.counts.budget}`],
                  ['已测量结构', snapshot.counts.measured],
                  ['演化子代', snapshot.counts.children],
                  ['LLM 请求', number(snapshot.log.requests, 0)],
                ].map(([label, value]) => (
                  <div className="c-kpi" key={label}>
                    <span>{label}</span>
                    <strong>{value}</strong>
                  </div>
                ))}
              </section>
              <Suspense fallback={<p>正在加载视图…</p>}>
                {tab === 'overview' ? (
                  <Overview snapshot={snapshot} navigate={setTab} />
                ) : tab === 'map' ? (
                  <Landscape key={runId} snapshot={snapshot} />
                ) : tab === 'evidence' ? (
                  <EvidenceView key={runId} rows={snapshot.rows} />
                ) : tab === 'compositions' ? (
                  <CompositionView reports={reports} rows={snapshot.rows} />
                ) : (
                  <section className="c-bottom-grid">
                    <article className="c-panel c-events">
                      <h2>研究日志</h2>
                      {snapshot.log.events
                        .slice()
                        .reverse()
                        .map((event) => (
                          <div key={event.id}>
                            <code>{event.text}</code>
                          </div>
                        ))}
                    </article>
                    <article className="c-panel c-config">
                      <h2>冻结研究配置</h2>
                      <p>模式：{snapshot.config.mode}</p>
                      <p>Bootstrap：{number(snapshot.config.n_boot, 0)}</p>
                      <p>Placebo：{snapshot.config.n_placebo}</p>
                      <p>
                        森林：{snapshot.config.n_trees} 棵 / {snapshot.config.n_splits} 次切分
                      </p>
                      <p>模型额度：{snapshot.config.llm_max_calls}</p>
                    </article>
                  </section>
                )}
              </Suspense>
              <footer className="a-footer">
                <span>所有统计来自研究产物 · 未完成检验保持未知</span>
                <a
                  className="c-text-button"
                  href={`/api/control/artifact/${encodeURIComponent(runId)}/report.md`}
                  download
                >
                  <Download size={14} />
                  下载研究报告
                </a>
              </footer>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

/** 将兼容路由与控制台分离，避免路由切换改变 hook 调用顺序。 */
function App() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const updateHash = () => setHash(window.location.hash);
    window.addEventListener('hashchange', updateHash);
    return () => window.removeEventListener('hashchange', updateHash);
  }, []);
  const page =
    hash === '#skill' ? (
      <SkillPanel />
    ) : hash === '#studio' ? (
      <Studio />
    ) : hash === '#workbench' ? (
      <Workbench />
    ) : null;
  if (page)
    return (
      <div className="control">
        <button
          className="c-back-console"
          onClick={() => {
            window.location.hash = '';
          }}
        >
          Back to console
        </button>
        <Suspense fallback={<p>加载页面…</p>}>{page}</Suspense>
      </div>
    );
  return <Dashboard />;
}
createRoot(document.getElementById('root')!).render(<App />);
