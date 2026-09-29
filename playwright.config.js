import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests/browser',
  use: { baseURL: 'http://127.0.0.1:8765', browserName: 'chromium', ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) },
  webServer: { command: 'python3 -m http.server 8765 --bind 127.0.0.1 --directory dashboard', url: 'http://127.0.0.1:8765', reuseExistingServer: !process.env.CI },
  reporter: 'list',
});
