import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests/browser',
  outputDir: './artifacts/browser-tests',
  timeout: 30000,
  use: { browserName: 'chromium', headless: true, launchOptions: { executablePath: '/data1/yuxiao/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome' } },
  reporter: 'list',
});
