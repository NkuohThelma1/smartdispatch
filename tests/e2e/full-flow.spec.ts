import { test, expect, type Page } from '@playwright/test';

const TEST_PHONE = `+254700000000${Date.now()}`;
const TEST_PASSWORD = 'testpass123';
const TEST_ROLE = 'customer';
const ORDER_LAT = '-1.28';
const ORDER_LON = '36.82';
const ORDER_MODE = 'standard';

async function switchToSignup(page: Page) {
  await page.getByRole('button', { name: 'Sign up' }).click();
  await expect(page.getByLabel('Role')).toBeVisible();
}

async function signup(page: Page) {
  await switchToSignup(page);
  await page.getByPlaceholder('+254700000000').fill(TEST_PHONE);
  await page.getByPlaceholder('••••••••').fill(TEST_PASSWORD);
  await page.getByLabel('Role').selectOption(TEST_ROLE);
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page.getByText('Signed up successfully')).toBeVisible();
}

async function logout(page: Page) {
  await page.getByRole('button', { name: 'Logout' }).click();
  await expect(page.getByText('Logged out.')).toBeVisible();
}

async function login(page: Page) {
  await page.locator('.segmented').getByRole('button', { name: 'Login' }).click();
  await page.getByPlaceholder('+254700000000').fill(TEST_PHONE);
  await page.getByPlaceholder('••••••••').fill(TEST_PASSWORD);
  await page.getByRole('button', { name: 'Login' }).last().click();
  await expect(page.getByText('Logged in successfully.')).toBeVisible();
}

async function placeOrder(page: Page): Promise<string> {
  await page.getByPlaceholder('Latitude').fill(ORDER_LAT);
  await page.getByPlaceholder('Longitude').fill(ORDER_LON);
  await page.getByRole('combobox').selectOption(ORDER_MODE);
  await page.getByPlaceholder('Optional item reference').fill('E2E test item');
  await page.getByRole('button', { name: 'Submit order' }).click();
  await expect(page.getByText(/Order [\w-]+ placed/)).toBeVisible();

  const messageText = await page.locator('.footer span').first().textContent();
  const match = messageText?.match(/Order ([\w-]+) placed/);
  expect(match).not.toBeNull();
  return match![1];
}

async function verifyOrderInTracking(page: Page, orderId: string) {
  await page.getByPlaceholder('Order ID').fill(orderId);
  await page.getByRole('button', { name: 'Load' }).click();

  const trackingSection = page.locator('section').filter({ hasText: 'Track order' });
  const orderPre = trackingSection.locator('pre');
  await expect(orderPre).toContainText(`"id": "${orderId}"`);
  await expect(orderPre).toContainText(`"lat": ${parseFloat(ORDER_LAT)}`);
  await expect(orderPre).toContainText(`"lon": ${parseFloat(ORDER_LON)}`);
  await expect(orderPre).toContainText(`"mode": "${ORDER_MODE}"`);
}

async function verifyAnalyticsUpdated(page: Page) {
  await page.getByRole('button', { name: 'Refresh stats' }).click();

  await page.waitForFunction(
    () => {
      const preTags = document.querySelectorAll('.card.wide pre');
      let eventsText = '';
      let deliveriesText = '';

      for (const pre of preTags) {
        const heading = pre.parentElement?.querySelector('h3')?.textContent?.trim();
        const text = pre.textContent || '';
        if (heading === 'Events') {
          eventsText = text;
        } else if (heading === 'Deliveries') {
          deliveriesText = text;
        }
      }

      const hasOrderPlaced = eventsText.includes('"order.placed"');
      const hasOrderInDeliveries = deliveriesText.includes('"standard"');

      return hasOrderPlaced && hasOrderInDeliveries;
    },
    { timeout: 30000 }
  );
}

test('full flow: signup, login, place order, track order, verify analytics', async ({ page }) => {
  await page.goto('/');
  await page.waitForLoadState('domcontentloaded');

  await signup(page);
  await logout(page);
  await login(page);

  const orderId = await placeOrder(page);
  await verifyOrderInTracking(page, orderId);
  await verifyAnalyticsUpdated(page);
});
