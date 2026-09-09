/** 证据视图管线：从实际结果选择结构、展示 IC 曲线和冻结规格，不混用坐标与结构 ID。 */
import { useState } from 'react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { Result } from './control-types';

import { number } from './format';

/** 展示冻结机制和各表达式曲线；输入一个真实结果，返回可审查证据。 */
export function EvidenceDetail({ row }: { row?: Result }) {
  if (!row)
    return (
      <div className="c-empty">
        <h2>尚无测量证据</h2>
        <p>结构完成后，这里显示冻结表达式、IC 与验证状态。</p>
      </div>
    );
  const horizons = [...new Set(row.curves.map((curve) => curve.horizon))].sort((a, b) => a - b);
  const chart = horizons.map((horizon) =>
    Object.fromEntries([
      ['horizon', horizon],
      ...row.curves
        .filter((curve) => curve.horizon === horizon)
        .map((curve) => [`e${curve.expression}`, curve.mean]),
    ]),
  );
  return (
    <div className="c-evidence-body">
      <div className="c-heading">
        <div>
          <span>{row.id}</span>
          <h2>{row.name}</h2>
        </div>
        <span className="c-tag">{row.verdict}</span>
      </div>
      <p className="c-muted">{row.spec.mechanism}</p>
      <div className="a-metrics">
        <div>
          主要 IC<strong>{number(row.primary.mean)}</strong>
        </div>
        <div>
          持有期<strong>{row.spec.primary_horizon} 日</strong>
        </div>
        <div>
          确认资格<strong>{row.formal ? '正式结果' : '探索结果'}</strong>
        </div>
      </div>
      <div className="c-curve" aria-label="各持有期 IC 曲线">
        <ResponsiveContainer width="100%" height={210}>
          <LineChart data={chart}>
            <CartesianGrid stroke="#263c43" vertical={false} />
            <XAxis dataKey="horizon" tick={{ fill: '#a0b1bd' }} />
            <YAxis tick={{ fill: '#a0b1bd' }} />
            <Tooltip contentStyle={{ background: '#15242e', border: '1px solid #405765' }} />
            {[...new Set(row.curves.map((curve) => curve.expression))].map((expression, index) => (
              <Line
                key={expression}
                dataKey={`e${expression}`}
                name={`表达式 ${expression}`}
                stroke={['#68d7be', '#8baeff', '#edbc79'][index % 3]}
                connectNulls={false}
                dot={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="c-muted">IC 为描述性测量；未知或失败检验不代表通过。曲线不表示可交易收益。</p>
      <details className="c-detail">
        <summary>查看冻结机制与全部表达式</summary>
        {row.spec.operational.map((expression, index) => (
          <pre className="c-code" key={index}>
            {expression}
          </pre>
        ))}
        <p>
          覆盖：{row.spec.coverage} · 父结构：{row.spec.lineage?.parent || '初始结构'} · 演化：
          {row.spec.lineage?.operator || 'seed'}
        </p>
      </details>
      <details className="c-detail">
        <summary>查看检验与确认记录</summary>
        <pre>{JSON.stringify({ blades: row.blades, confirmation: row.confirmation }, null, 2)}</pre>
      </details>
    </div>
  );
}

/** 搜索和选择真实结构；输入结果列表，局部选择状态不会影响地图坐标。 */
export default function EvidenceView({ rows }: { rows: Result[] }) {
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState('');
  const matches = rows.filter((row) =>
    `${row.name} ${row.id}`.toLowerCase().includes(query.toLowerCase()),
  );
  const row = matches.find((item) => item.id === selected) || matches.at(-1);
  return (
    <section className="c-evidence-grid">
      <aside className="c-panel c-result-list">
        <h2>结构证据</h2>
        <input
          className="a-search"
          aria-label="搜索结构"
          placeholder="搜索名称或编号"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        {!matches.length && <p>没有匹配结构。</p>}
        {matches.map((item) => (
          <button
            className={item.id === row?.id ? 'active' : ''}
            key={item.id}
            onClick={() => setSelected(item.id)}
          >
            {item.name}
            <small>
              {item.id} · IC {number(item.primary.mean)}
            </small>
          </button>
        ))}
      </aside>
      <article className="c-panel">
        <EvidenceDetail row={row} />
      </article>
    </section>
  );
}
