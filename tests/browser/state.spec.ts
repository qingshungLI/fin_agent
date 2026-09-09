/** 状态边界测试：模拟空数据、异步批次切换与控制回执，不启动真实研究进程。 */
import { test, expect } from '@playwright/test';

/** 构造最小合法快照；参数为批次和状态，返回测试数据，不用于产品展示。 */
function snapshot(id: string, state = 'RUNNING') {
  return {
    run_id: id,
    status: state,
    observed_at: '2026-09-09T12:00:00Z',
    config: { mode: 'fast', n_placebo: 19, auto_evolve: true, n_trees: 30, n_splits: 2 },
    counts: { attempts: 1, budget: 210, measured: 0, children: 0, rejected: 0, formal: 0 },
    current: { cell: id, frozen: false },
    map: [],
    rows: [],
    panel: {},
    model: {},
    log: { events: [], requests: null },
    pipeline: { stages: {} },
    audit: { events: 0, valid: null },
  };
}

test('control acknowledgment preserves running status until a new snapshot arrives', async ({
  page,
}) => {
  let command: unknown;
  await page.route('**/api/control/runs', (route) =>
    route.fulfill({ json: [{ id: 'demo', status: 'RUNNING' }] }),
  );
  await page.route('**/api/control/snapshot/demo', (route) =>
    route.fulfill({ json: snapshot('demo') }),
  );
  await page.route('**/api/control/compositions/*', (route) => route.fulfill({ json: [] }));
  await page.route('**/api/control/runs/demo/action', async (route) => {
    command = route.request().postDataJSON();
    await route.fulfill({ json: { action: 'pause' } });
  });
  await page.goto('http://127.0.0.1:5173');
  await page.getByRole('button', { name: '暂停', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('指令已提交');
  expect(command).toEqual({ action: 'pause' });
  await expect(page.locator('.a-runbar')).toContainText('研究运行中');
  await expect(page.getByRole('button', { name: '继续', exact: true })).toBeDisabled();
  await page.screenshot({
    path: 'artifacts/validation/console-overview-fixture.png',
    fullPage: true,
  });
});

test('a delayed old batch cannot replace the newly selected snapshot', async ({ page }) => {
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let markRequested: () => void = () => {};
  const requested = new Promise<void>((resolve) => {
    markRequested = resolve;
  });
  let markSettled: () => void = () => {};
  const settled = new Promise<void>((resolve) => {
    markSettled = resolve;
  });
  await page.route('**/api/control/runs', (route) =>
    route.fulfill({ json: [{ id: 'old' }, { id: 'new' }] }),
  );
  await page.route('**/api/control/compositions/*', (route) => route.fulfill({ json: [] }));
  await page.route('**/api/control/snapshot/old', async (route) => {
    markRequested();
    await gate;
    // 切换批次会取消旧请求；等待处理完成后再检查新快照没有被覆盖。
    try {
      await route.fulfill({ json: snapshot('old') });
    } finally {
      markSettled();
    }
  });
  await page.route('**/api/control/snapshot/new', (route) =>
    route.fulfill({ json: snapshot('new', 'PAUSED') }),
  );
  await page.goto('http://127.0.0.1:5173');
  await expect(page.getByLabel('当前研究批次').locator('option')).toHaveCount(2);
  await requested;
  await page.getByLabel('当前研究批次').selectOption('new');
  await expect(page.locator('.a-runbar')).toContainText('已暂停');
  release();
  await settled;
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
  await expect(page.getByLabel('当前研究批次')).toHaveValue('new');
  await expect(page.locator('.a-runbar')).toContainText('已暂停');
  await expect(page.getByRole('button', { name: '暂停', exact: true })).toBeDisabled();
});

test('resume rejection explains the frozen-version conflict without a success notice', async ({
  page,
}) => {
  await page.route('**/api/control/runs', (route) => route.fulfill({ json: [{ id: 'demo' }] }));
  await page.route('**/api/control/snapshot/demo', (route) =>
    route.fulfill({ json: snapshot('demo', 'FAILED') }),
  );
  await page.route('**/api/control/compositions/*', (route) => route.fulfill({ json: [] }));
  await page.route('**/api/control/runs/demo/action', (route) =>
    route.fulfill({
      status: 409,
      json: { detail: '当前源码与批次冻结版本不同，请使用原版本恢复。' },
    }),
  );
  await page.goto('http://127.0.0.1:5173');
  await page.getByRole('button', { name: '继续', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('当前源码与批次冻结版本不同');
  await expect(page.locator('.a-notice')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '继续', exact: true })).toBeEnabled();
});
