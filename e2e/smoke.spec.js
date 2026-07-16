import { test, expect } from "@playwright/test";

test("dashboard loads with hard-lines compliance block", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.locator("text=Acme Finance").first()).toBeVisible();
  await expect(page.getByText("not a money transmitter", { exact: false })).toBeVisible();
  await expect(page.getByText("YTD Revenue")).toBeVisible();
  await page.screenshot({ path: "e2e-results/dashboard.png", fullPage: true });
});

test("invoices page renders form and creates an invoice", async ({ page }) => {
  await page.goto("/invoices");
  await expect(page.getByRole("heading", { name: "Invoices" })).toBeVisible();

  // Wait for the customer dropdown to load a real value (not the disabled placeholder)
  const customerSelect = page.locator("select").first();
  await expect.poll(async () => (await customerSelect.inputValue()).length).toBeGreaterThan(0);

  await page.locator('input[type="number"]').fill("9850");
  await page.getByPlaceholder("Roof replacement").fill("Roof replacement — e2e test");
  await page.getByRole("button", { name: /Create \+ Send invoice/ }).click();

  await expect(page.getByText(/INV-\d/).first()).toBeVisible({ timeout: 10000 });
  await page.screenshot({ path: "e2e-results/invoices.png", fullPage: true });
});

test("ledger entries page loads", async ({ page }) => {
  await page.goto("/ledger");
  await expect(page.getByRole("heading", { name: "Ledger" })).toBeVisible();
  await expect(page.getByText("Chart of accounts")).toBeVisible();
  await page.screenshot({ path: "e2e-results/ledger.png", fullPage: true });
});

test("tax page shows OBBBA 2026 threshold = $2,000", async ({ page }) => {
  await page.goto("/tax");
  await expect(page.getByRole("heading", { name: "Tax packet" })).toBeVisible();
  await expect(page.getByText("$2,000.00").first()).toBeVisible();
  await page.screenshot({ path: "e2e-results/tax.png", fullPage: true });
});

test("payouts page can create a profile", async ({ page }) => {
  await page.goto("/payouts");
  await expect(page.getByRole("heading", { name: "PM Payouts" })).toBeVisible();

  // Wait for the PM dropdown to populate so the form can submit
  const pmSelect = page.locator("select").first();
  await expect.poll(async () => (await pmSelect.inputValue()).length).toBeGreaterThan(0);

  const ts = Date.now();
  const newName = `E2E PM ${ts}`;
  await page.getByLabel("Legal name").fill(newName);
  await page.getByRole("button", { name: "Add profile" }).click();

  // The new profile must appear in the Profiles section
  await expect(page.locator(".card", { hasText: newName }).first()).toBeVisible({ timeout: 5000 });
  await page.screenshot({ path: "e2e-results/payouts.png", fullPage: true });
});

test("receipts page lets you log a Home Depot receipt", async ({ page }) => {
  await page.goto("/receipts");
  await expect(page.getByRole("heading", { name: "Receipts" })).toBeVisible();
  await page.getByPlaceholder("Home Depot").fill("Home Depot #6543");
  await page.locator('input[type="number"]').fill("142.37");
  await page.getByRole("button", { name: "Capture receipt" }).click();
  await expect(page.getByText("materials").first()).toBeVisible();
  await page.screenshot({ path: "e2e-results/receipts.png", fullPage: true });
});

test("mileage page logs a trip and shows IRS rate", async ({ page }) => {
  await page.goto("/mileage");
  await expect(page.getByRole("heading", { name: "Mileage" })).toBeVisible();
  await page.getByLabel("Miles").fill("12.5");
  await page.getByPlaceholder("Inspection").fill("Inspection — Smith roof");
  await page.getByRole("button", { name: "Log trip" }).click();
  await expect(page.getByText("12.50")).toBeVisible();
  await page.screenshot({ path: "e2e-results/mileage.png", fullPage: true });
});

test("merch page renders products", async ({ page }) => {
  await page.goto("/merch");
  await expect(page.getByRole("heading", { name: "Merch storefront" })).toBeVisible();
  await expect(page.getByText("Acme Black Tee")).toBeVisible();
  await page.screenshot({ path: "e2e-results/merch.png", fullPage: true });
});
