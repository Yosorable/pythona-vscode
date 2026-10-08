import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 45000,
  expect: { timeout: 12000 },
  fullyParallel: true,
  workers: 2,
  use: { screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'], channel: 'chrome', viewport: { width: 1194, height: 834 } } },
    { name: 'webkit-ipad', use: { ...devices['iPad Pro 11 landscape'], browserName: 'webkit', userAgent: devices['Desktop Safari'].userAgent } },
  ],
});
