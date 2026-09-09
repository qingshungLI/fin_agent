/** 研究状态管线：串行轮询快照，取消过期请求，控制命令成功后重新读取真实状态。 */
import { useCallback, useEffect, useState } from 'react';
import type { CompositionReport, Run, Snapshot } from './control-types';

/** 读取 JSON；非成功响应明确报错，取消信号由调用者管理。 */
async function readJson<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal });
  if (!response.ok) throw new Error(`研究服务请求失败 (${response.status})`);
  return response.json();
}

/** 管理一个批次的状态；返回只读快照、刷新和控制入口，不推测任务已完成。 */
export function useResearch() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [runId, setRunId] = useState('');
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [reports, setReports] = useState<CompositionReport[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0);
  const refresh = useCallback(() => setVersion((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    const poll = async () => {
      try {
        const choices = await readJson<Run[]>('/api/control/runs', controller.signal);
        if (controller.signal.aborted) return;
        setRuns(choices);
        const id = choices.some((run) => run.id === runId) ? runId : choices[0]?.id;
        if (!id) {
          setSnapshot(null);
          setReports([]);
          setError('');
        } else if (id !== runId) {
          setSnapshot(null);
          setReports([]);
          setRunId(id);
        } else {
          const next = await readJson<Snapshot>(
            `/api/control/snapshot/${encodeURIComponent(id)}`,
            controller.signal,
          );
          if (controller.signal.aborted) return;
          setSnapshot(next);
          const combinations = await readJson<CompositionReport[]>(
            `/api/control/compositions/${encodeURIComponent(id)}`,
            controller.signal,
          );
          if (controller.signal.aborted) return;
          setReports(combinations);
          setError('');
        }
      } catch (reason) {
        if (!controller.signal.aborted)
          setError(reason instanceof Error ? reason.message : '研究服务不可用');
      } finally {
        // 等待请求结束再安排下一次，避免大型快照产生重叠请求和旧状态覆盖。
        if (!controller.signal.aborted) timer = window.setTimeout(poll, 5000);
      }
    };
    void poll();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [runId, version]);

  const selectRun = (id: string) => {
    setSnapshot(null);
    setReports([]);
    setNotice('');
    setError('');
    setRunId(id);
  };
  const action = async (name: 'pause' | 'resume' | 'stop') => {
    if (!snapshot || busy) return;
    setBusy(true);
    setNotice('');
    try {
      const response = await fetch(
        `/api/control/runs/${encodeURIComponent(snapshot.run_id)}/action`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: name }),
        },
      );
      if (!response.ok) {
        const body = await response.text();
        let detail = '';
        try {
          const errorBody = JSON.parse(body) as { detail?: unknown };
          if (typeof errorBody.detail === 'string') detail = errorBody.detail;
        } catch {
          // 代理可能返回 HTML 错误页；保留 HTTP 状态，不向用户展示整段页面。
        }
        throw new Error(detail || `控制请求失败 (${response.status})`);
      }
      setNotice('指令已提交；暂停与停止在研究检查点生效，请以刷新后的状态为准。');
      refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '控制请求失败');
    } finally {
      setBusy(false);
    }
  };
  return { runs, runId, snapshot, reports, error, notice, busy, refresh, selectRun, action };
}
