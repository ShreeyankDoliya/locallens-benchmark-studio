import { test, expect } from '@playwright/test';

test('published demo renders and every failure opens evidence', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/');
  await expect(page.locator('#model-table tbody tr')).toHaveCount(2);
  await expect(page.locator('#task-table tbody tr')).toHaveCount(40);
  await page.selectOption('#outcome-filter', 'failed');
  await expect(page.locator('#task-table tbody tr')).toHaveCount(12);
  await page.getByRole('button', { name: 'Inspect code-bool for mock-hasty in mock-demo', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.locator('#detail-content')).toContainText('Raw response');
  await expect(page.locator('#detail-content')).toContainText('Literal string equality');
  await expect(page.locator('#detail-content')).toContainText('Attempt history');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await page.selectOption('#outcome-filter', 'error');
  await expect(page.locator('#task-table tbody tr')).toHaveCount(1);
  await page.getByRole('button', { name: /Inspect json-empty/ }).click();
  await expect(page.locator('#detail-content')).toContainText('3 attempt(s)');
  expect(errors).toEqual([]);
});

test('compare runs, reset filters, and download report', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#task-table tbody tr')).toHaveCount(40);
  await page.selectOption('#compare-select', 'mock-repeat');
  await expect(page.locator('#model-table tbody tr')).toHaveCount(4);
  await expect(page.locator('#task-table tbody tr')).toHaveCount(80);
  await expect(page.locator('#comparison-note')).toBeVisible();
  await page.fill('#search', 'does-not-exist');
  await expect(page.locator('#empty')).toBeVisible();
  await page.getByRole('button', { name: 'Reset filters' }).click();
  await expect(page.locator('#task-table tbody tr')).toHaveCount(80);
  await page.selectOption('#outcome-filter', 'disagreement');
  await expect(page.locator('#task-table tbody tr')).toHaveCount(40);
  const downloadEvent = page.waitForEvent('download');
  await page.locator('#download-report').click();
  expect((await downloadEvent).suggestedFilename()).toBe('mock-demo.md');
});

test('mobile layout stays within viewport and filters work', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.locator('#task-table tbody tr')).toHaveCount(40);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.selectOption('#category-filter', 'grounding');
  await page.selectOption('#model-filter', 'mock-hasty');
  await expect(page.locator('#task-table tbody tr')).toHaveCount(4);
  await page.locator('.inspect-button').first().click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button', {name:'Close task details'}).click();
});

test('untrusted model output is displayed as text', async ({ page }) => {
  await page.route('**/data/mock-demo.json', async route => {
    const response = await route.fetch();
    const data = await response.json();
    data.results[0].response = '<img src=x onerror="window.injected=true">';
    await route.fulfill({ json: data });
  });
  await page.goto('/');
  await expect(page.locator('#task-table tbody tr')).toHaveCount(40);
  await page.fill('#search', 'window.injected');
  await page.locator('.inspect-button').click();
  await expect(page.locator('#detail-content')).toContainText('<img src=x');
  await expect(page.locator('#detail-content img')).toHaveCount(0);
  expect(await page.evaluate(() => window.injected)).toBeUndefined();
});

test('missing exports show an actionable error', async ({ page }) => {
  await page.route('**/data/index.json', route => route.fulfill({status:404,body:'Missing'}));
  await page.goto('/');
  await expect(page.locator('#notice')).toContainText('HTTP 404');
});
