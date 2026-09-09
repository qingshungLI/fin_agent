/** 浏览器验收：真实 API、三维渲染与选取、二维键盘入口、证据、移动端和错误恢复。 */
import { test, expect, type Page } from '@playwright/test';

test.use({ launchOptions: { args: ['--enable-unsafe-swiftshader'] } });
const base = 'http://127.0.0.1:5173';

/** 已保存批次用于稳定证据验收；输入页面，返回加载完成的历史真实批次。 */
async function openExistingRun(page: Page) {
  await page.goto(base);
  await expect(page.locator('.c-kpis')).toBeVisible();
  await page.getByLabel('当前研究批次').selectOption('fullcycle-20260908');
  await expect(page.locator('.c-kpis')).toBeVisible();
}

test('real 3D scene and map selection show the same research coordinate', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1512, height: 1100 });
  await openExistingRun(page);
  await expect(page.getByRole('heading', { name: '自动演化研究控制台' })).toBeVisible();
  await page.locator('nav button').nth(1).click();
  await page.getByRole('button', { name: '3D', exact: true }).click();
  await expect(page.locator('.c-scene-wrap canvas')).toBeVisible({ timeout: 30000 });
  await expect(page.locator('.c-kpi')).toHaveCount(4);
  await page.getByLabel('选择研究坐标').selectOption('M2-F3');
  await expect(page.locator('.c-mechanism .c-tag')).toHaveText('M2-F3');
  await expect(page.locator('.c-mechanism .c-code').first()).toBeVisible();
  await page.screenshot({ path: 'artifacts/validation/control-desktop.png', fullPage: true });
  const canvas = page.locator('.c-scene-wrap canvas');
  const box = await canvas.boundingBox();
  expect(box).not.toBeNull();
  for (const [x, y] of [
    [0.53, 0.6],
    [0.48, 0.62],
    [0.56, 0.56],
    [0.45, 0.55],
  ]) {
    await canvas.click({ position: { x: box!.width * x, y: box!.height * y } });
    if ((await page.getByLabel('选择研究坐标').inputValue()) !== 'M2-F3') break;
  }
  await expect(page.getByLabel('选择研究坐标')).not.toHaveValue('M2-F3');
  await page.getByRole('button', { name: '复位三维视角' }).click();
  await page.getByRole('button', { name: '2D', exact: true }).click();
  await expect(page.locator('.c-cell')).toHaveCount(70);
  await page.getByRole('button', { name: 'M8-F6', exact: false }).click();
  await expect(page.locator('.c-mechanism .c-tag')).toHaveText('M8-F6');
  await expect(page.getByLabel('选择研究坐标')).toHaveValue('M8-F6');
  expect(errors).toEqual([]);
});

test('evidence and logs show actual artifacts with downloadable report', async ({ page }) => {
  await openExistingRun(page);
  await expect(page.locator('.c-kpis')).toBeVisible();
  await page.getByRole('button', { name: '结构证据', exact: true }).click();
  await expect(page.locator('.c-evidence-body')).toBeVisible();
  await page.getByText('查看冻结机制与全部表达式').click();
  await expect(page.locator('.c-detail pre.c-code')).toHaveCount(3);
  await expect(page.locator('.c-curve')).toBeVisible();
  await page.screenshot({ path: 'artifacts/validation/control-evidence.png', fullPage: true });
  const href = await page.getByRole('link', { name: '下载研究报告' }).getAttribute('href');
  const report = await page.request.get(base + href);
  expect(report.ok()).toBeTruthy();
  expect(await report.text()).toContain('exploratory');
  await page.getByRole('button', { name: '研究日志', exact: true }).click();
  await expect(page.locator('.c-events')).toBeVisible();
  await expect(page.locator('.c-config')).toContainText('1,000');
});

test('presentation and mobile views remain usable without overflow', async ({ page }) => {
  await openExistingRun(page);
  await expect(page.locator('.c-kpis')).toBeVisible();
  await page.getByRole('button', { name: '评委展示模式' }).click();
  await expect(page.locator('.c-sidebar')).toBeHidden();
  await page.getByRole('button', { name: '退出展示', exact: true }).click();
  await page.locator('nav button').nth(1).click();
  await page.getByRole('button', { name: '3D', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator('.c-scene-wrap canvas')).toBeVisible();
  await page.screenshot({ path: 'artifacts/validation/control-mobile.png', fullPage: true });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
  ).toBeTruthy();
  await page.getByRole('button', { name: '2D', exact: true }).click();
  await expect(page.locator('.c-cell')).toHaveCount(70);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
  ).toBeTruthy();
});

test('API outage displays a clear error without invented statistics', async ({ page }) => {
  await page.route('**/api/control/runs', (route) => route.fulfill({ status: 503, body: '{}' }));
  await page.goto(base);
  await expect(page.getByRole('alert')).toContainText('503');
  await expect(page.locator('.c-kpis')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '自动演化研究控制台' })).toBeVisible();
});
test('composition panel shows actual rules, failures and downloadable frozen targets', async ({
  page,
}) => {
  await openExistingRun(page);
  await expect(page.locator('.c-kpis')).toBeVisible();
  await page.getByRole('button', { name: '组合门控', exact: true }).click();
  await expect(page.getByRole('heading', { name: '多结构组合与门控' })).toBeVisible();
  await expect(page.locator('.c-composition-variants article')).toHaveCount(3);
  await expect(page.locator('.c-composition-sources > div')).toHaveCount(6);
  await expect(page.locator('.c-combo-execution').first()).toContainText('Missing execution price');
  const rules = page.getByRole('link', { name: '门控规则', exact: true }).first();
  const response = await page.request.get(base + (await rules.getAttribute('href')));
  expect(response.ok()).toBeTruthy();
  expect(await response.json()).toHaveProperty('formal', false);
  await page.screenshot({ path: 'artifacts/validation/control-compositions.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
  ).toBeTruthy();
});

test('fast profile displays actual reduced configuration without formal success', async ({
  page,
}) => {
  await page.goto(base);
  await expect(page.locator('.c-kpis')).toBeVisible();
  await page.getByLabel('当前研究批次').selectOption('fastcycle-v2-20260908');
  await expect(page.locator('.c-alert').filter({ hasText: 'FAST 探索' })).toContainText(
    '19 次横截面诊断',
  );
  await expect(page.locator('.c-alert').filter({ hasText: 'FAST 探索' })).toContainText(
    '不授予正式 PASS',
  );
  await page.getByRole('button', { name: '研究日志', exact: true }).click();
  await expect(page.locator('.c-config')).toContainText('19');
  await page.screenshot({ path: 'artifacts/validation/control-fast.png', fullPage: true });
});
