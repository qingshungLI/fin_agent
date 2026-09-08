import { useEffect, useState } from 'react';
import { Download, ExternalLink, FileCode2, Github, Package, ShieldCheck } from 'lucide-react';
import './control.css';

type SkillManifest = {
  name: string;
  version: string;
  repository: string;
  skill_path: string;
  rsi: string;
  data_formats: string[];
  entrypoints: string[];
};

/** Present the reusable AURORA Skill package and its data contract.
 *
 * The page stays inside the project console so evaluators see the same
 * research protocol that an external user downloads and runs locally.
 */
export default function SkillPanel() {
  const [manifest, setManifest] = useState<SkillManifest | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    fetch('/api/control/skill-manifest').then(async response => {
      if (!response.ok) throw new Error(`Skill metadata unavailable (${response.status})`);
      return response.json() as Promise<SkillManifest>;
    }).then(setManifest).catch(reason => setError(reason instanceof Error ? reason.message : 'Skill metadata unavailable'));
  }, []);

  return <main className="c-content c-skill-page">
    <section className="c-page-title">
      <div><p className="c-eyebrow">AURORA / DISTRIBUTABLE RESEARCH PROTOCOL</p><h1>Research Skill <span>READY</span></h1><p>把递归自我改进研究流程带到任何符合契约的 CSV、Parquet 或 pandas 数据。</p></div>
      <div className="c-skill-actions"><a className="c-text-button" href="/api/control/skill" download><Download size={15} />Download SKILL.md</a>{manifest && <a className="c-text-button" href={manifest.repository} target="_blank" rel="noreferrer"><Github size={15} />GitHub repository <ExternalLink size={13} /></a>}</div>
    </section>
    {error && <div className="c-alert" role="alert">{error}</div>}
    <section className="c-skill-grid">
      <article className="c-panel c-skill-hero"><div className="c-skill-icon"><Package size={22} /></div><span className="c-tag">{manifest?.name || 'aurora-factor-research'} / v{manifest?.version || '1.0.0'}</span><h2>RSI Alpha Research Harness</h2><p>固定 evaluator、有限预算、可审计 checkpoint 和演化记忆组成一个可复现闭环。模型只能提出和批评候选，研究引擎负责冻结、测量、证伪和记录。</p><div className="c-skill-flow"><b>PROPOSE</b><i>→</i><b>MEASURE</b><i>→</i><b>CRITICIZE</b><i>→</i><b>MUTATE</b><i>→</i><b>RECORD</b></div></article>
      <article className="c-panel"><div className="c-heading"><div><span>DATA CONTRACT</span><h2>Bring your own data</h2></div><FileCode2 size={19} /></div><p className="c-muted">Required keys: <code>date</code>, <code>symbol</code>, <code>open</code>, <code>close</code>. Optional fields are validated before any factor is measured.</p><div className="c-skill-pills">{(manifest?.data_formats || ['CSV', 'Parquet', 'pandas DataFrame']).map(item => <span key={item}>{item}</span>)}</div><pre className="c-skill-code">{`from research_sdk import dataset_summary, run_experiment\nsummary = dataset_summary(panel)\nreport = run_experiment(panel, spec, output_dir)`}</pre></article>
      <article className="c-panel"><div className="c-heading"><div><span>GUARDRAILS</span><h2>What the Skill enforces</h2></div><ShieldCheck size={19} /></div><ul className="c-skill-list"><li>Training selection is separated from validation and confirmation.</li><li>Expressions use a bounded DSL; arbitrary Python evaluation is rejected.</li><li>Every mutation keeps parent lineage, budget usage and evidence artifacts.</li><li>Exploratory output never becomes a formal PASS without independent confirmation.</li></ul></article>
      <article className="c-panel"><div className="c-heading"><div><span>INSTALL / API</span><h2>Start from GitHub</h2></div><Github size={19} /></div><pre className="c-skill-code">{`git clone ${manifest?.repository || 'https://github.com/qingshungLI/fin_agent'}\ncd fin_agent\npip install -e .\npython -m research_sdk --data panel.parquet --spec spec.json --output artifacts/my-run`}</pre><p className="c-muted">The same contract is available through the local API for agent orchestration.</p><div className="c-skill-endpoints">{(manifest?.entrypoints || []).map(item => <code key={item}>{item}</code>)}</div></article>
    </section>
  </main>;
}