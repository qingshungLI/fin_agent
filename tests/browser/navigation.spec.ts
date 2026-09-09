/** 控制台导航回归：模拟空研究列表，验证路由返回和手动刷新，不启动研究任务。 */
import { test, expect } from '@playwright/test';

test('Skill navigation preserves hook order and refresh reloads runs', async ({ page }) => {
  const errors: string[] = [];
  let requests = 0;
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/api/control/runs', (route) => {
    requests += 1;
    return route.fulfill({ json: [] });
  });
  await page.route('**/api/control/skill-manifest', (route) =>
    route.fulfill({
      json: {
        name: 'AURORA',
        version: '0.1.0',
        repository: '',
        skill_path: '',
        rsi: 'Recursive Self-Improvement',
        data_formats: [],
        entrypoints: [],
      },
    }),
  );
  await page.goto('http://127.0.0.1:5173');
  await expect(page.locator('.c-sidebar')).toBeVisible();
  await expect.poll(() => requests).toBeGreaterThan(0);
  const before = requests;
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect.poll(() => requests, { timeout: 2000 }).toBeGreaterThan(before);
  await page.getByRole('link', { name: 'Research Skill' }).click();
  await expect(page.getByRole('heading', { name: 'Research Skill READY' })).toBeVisible();
  await page.getByRole('button', { name: 'Back to console' }).click();
  await expect(page.locator('.c-sidebar')).toBeVisible();
  expect(errors).toEqual([]);
});
