import { test, expect } from '@playwright/test';

test('research references cannot be confused with measured GLM runs', async ({ page }) => {
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  await page.goto('/research.html');
  await expect(page.locator('#research-status')).toContainText('Measured pilot');
  await expect(page.locator('#access-table tbody tr')).toHaveCount(7);
  await expect(page.locator('#access-table')).toContainText('1113');
  await expect(page.locator('#access-table')).toContainText('Not scored');
  await expect(page.locator('#reference-table tbody tr')).toHaveCount(6);
  await expect(page.locator('#paper-grid article')).toHaveCount(5);
  await page.getByRole('button', {name: 'Inspect source for Terminal-Bench 2.1', exact: true}).click();
  await expect(page.getByRole('dialog')).toContainText('Vendor-reported');
  await expect(page.getByRole('dialog')).toContainText('88.2');
  await expect(page.getByRole('dialog')).toContainText('has not reproduced');
  await page.keyboard.press('Escape');
  await expect(page.locator('#paper-reference')).toContainText('GLM-4.6');
  expect(errors).toEqual([]);
});

test('native task inventory filters and control evidence opens', async ({ page }) => {
  await page.goto('/research.html');
  await expect(page.locator('#native-table tbody tr')).toHaveCount(89);
  await page.locator('#native-category-trigger').click();
  await page.locator('#native-category-listbox').getByRole('option', {name:'scientific computing', exact:true}).click();
  await expect(page.locator('#native-table tbody tr')).toHaveCount(8);
  await page.locator('#native-search').fill('dna-insert');
  await expect(page.locator('#native-table tbody tr')).toHaveCount(1);
  await expect(page.locator('#native-table a').first()).toHaveAttribute('href', /69671fbaac6d67a7ef0dfec016cc38a64ef7a77c\/dna-insert\/instruction.md$/);
  await page.getByRole('button', {name:'Inspect verifier evidence'}).first().click();
  await expect(page.getByRole('dialog')).toContainText('Exact task instruction');
  await expect(page.getByRole('dialog')).toContainText('test_outputs.py::test_key_file');
  await expect(page.getByRole('dialog')).toContainText('No GLM inference');
});

test('research page fits mobile and handles missing evidence', async ({ page }) => {
  await page.setViewportSize({width:390,height:844});
  await page.goto('/research.html');
  await expect(page.locator('#native-table tbody tr')).toHaveCount(89);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.route('**/research/catalog.json', r => r.fulfill({status:404,body:'Missing'}));
  await page.reload();
  await expect(page.locator('#research-status')).toContainText('HTTP 404');
});

test('measured pilot filters failures and exposes exact evidence', async ({ page }) => {
  await page.goto('/research.html');
  await expect(page.locator('#measured-table tbody tr')).toHaveCount(10);
  await expect(page.locator('#pilot-results tbody tr')).toHaveCount(86);
  await page.locator('#pilot-benchmark-trigger').click();
  await page.locator('#pilot-benchmark-listbox').getByRole('option', {name:'GSM8K', exact:true}).click();
  await page.locator('#pilot-outcome-trigger').click();
  await page.locator('#pilot-outcome-listbox').getByRole('option', {name:'Models disagree', exact:true}).click();
  await expect(page.locator('#pilot-results tbody tr')).toHaveCount(2);
  await page.locator('#pilot-outcome-trigger').click();
  await page.locator('#pilot-outcome-listbox').getByRole('option', {name:'Failures', exact:true}).click();
  await expect(page.locator('#pilot-results tbody tr')).toHaveCount(1);
  await page.getByRole('button', {name:'Inspect gsm8k 1288 glm-5.3', exact:true}).click();
  await expect(page.getByRole('dialog')).toContainText('Exact prompt');
  await expect(page.getByRole('dialog')).toContainText('2040');
  await expect(page.getByRole('dialog')).toContainText('Expected result');
  await expect(page.getByRole('dialog')).toContainText('Recorded evidence');
});

test('measured output is rendered as text, never executable HTML', async ({ page }) => {
  await page.route('**/research/measurements.json', async route => {
    const data=await (await route.fetch()).json();
    data.results[0].response='<img src=x onerror="window.__unsafe=true">';
    await route.fulfill({json:data});
  });
  await page.goto('/research.html');
  await page.locator('#pilot-results button').first().click();
  await expect(page.getByRole('dialog')).toContainText('<img src=x');
  expect(await page.evaluate(()=>window.__unsafe)).toBeUndefined();
  await expect(page.getByRole('dialog').locator('img')).toHaveCount(0);
});
