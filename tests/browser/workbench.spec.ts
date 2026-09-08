import { test, expect } from '@playwright/test';

test('real server workbench renders research evidence and opens measurement', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:5173/#workbench');
  await expect(page.getByRole('heading', { name: 'AutoAlpha 因子研究工作台' })).toBeVisible();
  await expect(page.getByText('尚无研究批次')).toHaveCount(0);
  await expect(page.locator('.map-cell')).toHaveCount(70);
  const response = await page.request.get('http://127.0.0.1:5173/api/structures');
  expect(response.ok()).toBeTruthy();
  const structures = await response.json();
  expect(Array.isArray(structures)).toBeTruthy();
  if (structures.length) {
    const open = page.getByRole('button', { name: '查看完整测量' });
    await expect(open).toBeVisible();
    await open.click();
    await expect(page.locator('.measurement-table tbody tr')).toHaveCount(12);
  } else {
    await expect(page.locator('.focus-panel .empty')).toBeVisible();
    await expect(page.getByRole('button', { name: '查看完整测量' })).toHaveCount(0);
  }
  await expect(page.getByLabel('研究数据')).toHaveValue('daily');
  await expect(page.getByLabel('条件发现')).not.toBeChecked();
  await expect(page.getByLabel('贝叶斯研究记忆')).not.toBeChecked();
  expect(errors).toEqual([]);
  await page.screenshot({ path: 'artifacts/validation/workbench-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: 'artifacts/validation/workbench-mobile.png', fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});

test('workbench submits a bounded real server research job', async ({ page }) => {
  test.skip(process.env.RUN_LIVE_RESEARCH !== '1', 'Explicit live API budget required');
  await page.goto('http://127.0.0.1:5173/#workbench');
  await page.getByLabel('想法来源').selectOption('llm');
  await page.getByLabel('股票数量').fill('600');
  await page.getByLabel('结构数量').fill('1');
  await page.getByLabel('检验规模').selectOption('formal');
  await page.getByLabel('数据处理').selectOption('quarantine');
  const response = page.waitForResponse(r => r.url().endsWith('/api/jobs') && r.request().method() === 'POST');
  await page.getByRole('button', {name:'开始研究'}).click();
  expect((await response).status()).toBe(202);
  await expect(page.getByText(/已提交：job-/)).toBeVisible();
});

test('workbench keeps a usable view during a server error', async ({ page }) => {
  await page.route('**/api/overview', route => route.fulfill({
    status:500, contentType:'application/json', body:JSON.stringify({detail:'temporary error'})}));
  await page.goto('http://127.0.0.1:5173/#workbench');
  await expect(page.getByRole('alert')).toContainText('研究服务暂时不可用');
  await expect(page.getByRole('heading', { name:'AutoAlpha 因子研究工作台' })).toBeVisible();
});
