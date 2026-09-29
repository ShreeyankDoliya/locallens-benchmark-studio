import { test, expect } from '@playwright/test';

async function choose(page, id, value) {
  await page.locator(`${id}-trigger`).click();
  await page.locator(`${id}-listbox [role=option]`).filter({ hasText: await page.locator(id).evaluate((select, target) => [...select.options].find(option => option.value === target).textContent, value) }).click();
}

async function openMock(page) {
  await page.goto('/');
  await choose(page, '#run-select', 'mock-demo');
  await expect(page.locator('#notice')).toContainText('Scripted demo results.');
  await expect(page.locator('#model-table')).toContainText('mock-steady');
}

test('published demo renders and every failure opens evidence', async ({ page }) => {
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await openMock(page);
  await expect(page.locator('#model-table tbody tr')).toHaveCount(2);
  await expect(page.locator('#task-table tbody tr')).toHaveCount(40);
  await choose(page, '#outcome-filter', 'failed');
  await expect(page.locator('#task-table tbody tr')).toHaveCount(12);
  await page.getByRole('button', { name: 'Inspect code-bool for mock-hasty in mock-demo', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.locator('#detail-content')).toContainText('Raw response');
  await expect(page.locator('#detail-content')).toContainText('Literal string equality');
  await expect(page.locator('#detail-content')).toContainText('Attempt history');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await choose(page, '#outcome-filter', 'error');
  await expect(page.locator('#task-table tbody tr')).toHaveCount(1);
  await page.getByRole('button', { name: /Inspect json-empty/ }).click();
  await expect(page.locator('#detail-content')).toContainText('3 attempt(s)');
  expect(errors).toEqual([]);
});

test('compare runs, reset filters, and download report', async ({ page }) => {
  await openMock(page);
  await expect(page.locator('#task-table tbody tr')).toHaveCount(40);
  await choose(page, '#compare-select', 'mock-repeat');
  await expect(page.locator('#model-table tbody tr')).toHaveCount(4);
  await expect(page.locator('#task-table tbody tr')).toHaveCount(80);
  await expect(page.locator('#comparison-note')).toBeVisible();
  await page.fill('#search', 'does-not-exist');
  await expect(page.locator('#empty')).toBeVisible();
  await page.getByRole('button', { name: 'Reset filters' }).click();
  await expect(page.locator('#task-table tbody tr')).toHaveCount(80);
  await choose(page, '#outcome-filter', 'disagreement');
  await expect(page.locator('#task-table tbody tr')).toHaveCount(40);
  const downloadEvent = page.waitForEvent('download');
  await page.locator('#download-report').click();
  expect((await downloadEvent).suggestedFilename()).toBe('mock-demo.md');
});

test('mobile layout stays within viewport and filters work', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openMock(page);
  await expect(page.locator('#task-table tbody tr')).toHaveCount(40);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await choose(page, '#category-filter', 'grounding');
  await choose(page, '#model-filter', 'mock-hasty');
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
  await openMock(page);
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

test('themed dropdowns support keyboard selection, Escape, and outside dismissal', async ({ page }) => {
  await page.goto('/');
  const trigger = page.locator('#run-select-trigger');
  await expect(trigger).toBeEnabled();
  await trigger.focus();
  await page.keyboard.press('ArrowDown');
  await expect(trigger).toHaveAttribute('aria-expanded', 'true');
  await page.keyboard.press('End');
  await page.keyboard.press('Escape');
  await expect(page.locator('#run-select')).toHaveValue('local-qwen-m1-pro');
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
  await page.keyboard.press('Enter');
  await page.keyboard.press('End');
  await page.keyboard.press('Enter');
  await expect(page.locator('#run-select')).toHaveValue('mock-repeat');
  await expect(page.locator('#notice')).toContainText('Scripted demo results.');
  await trigger.click();
  await page.getByRole('heading', { name: 'Every score has a story.' }).click();
  await expect(trigger).toHaveAttribute('aria-expanded', 'false');
});

test('real local results are distinct from the scripted demo', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#notice')).toContainText('Local model results.');
  await expect(page.locator('#model-table')).toContainText('qwen-0.5b');
  await expect(page.locator('#model-table')).toContainText('qwen-1.5b');
  await expect(page.locator('#task-table tbody tr')).toHaveCount(40);
  await choose(page, '#compare-select', 'mock-demo');
  await expect(page.locator('#comparison-note')).toContainText('configurations');
  await expect(page.locator('#model-table tbody tr')).toHaveCount(4);
  await expect(page.locator('#notice')).toContainText('Local model results.');
});

test('remote API results never claim local inference or zero fees', async ({ page }) => {
  await page.route('**/data/local-qwen-m1-pro.json', async route => {
    const response = await route.fetch(); const data = await response.json();
    Object.values(data.run.snapshot.model_manifests).forEach(m => { m.remote = true; });
    data.summary.models.forEach(m => { m.cost_usd = null; m.cost_covered_results = 0; });
    await route.fulfill({json:data});
  });
  await page.goto('/');
  await expect(page.locator('#notice')).toContainText('Remote API results.');
  await expect(page.locator('#notice')).toContainText('network latency');
  await expect(page.locator('#metrics')).toContainText('Estimated API cost');
  await expect(page.locator('#metrics')).toContainText('Unknown');
  await expect(page.locator('#metrics')).not.toContainText('$0');
});
