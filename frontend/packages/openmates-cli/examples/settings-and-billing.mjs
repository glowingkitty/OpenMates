#!/usr/bin/env node
/*
 * OpenMates npm SDK example: account, settings, and billing.
 *
 * Run after building the package:
 *   OPENMATES_API_KEY=sk-api-... node examples/settings-and-billing.mjs
 *
 * This uses real API requests. It reads account/billing data and performs a safe
 * settings write by setting dark mode to its current value.
 */

import { OpenMates } from "../dist/index.js";

const client = new OpenMates({
  apiKey: process.env.OPENMATES_API_KEY,
  apiUrl: process.env.OPENMATES_API_URL,
});

const account = await client.account.info();
const darkModeWrite = await client.settings.setDarkMode(Boolean(account.darkmode));
const billing = await client.billing.overview();
const invoices = await client.billing.listInvoices();

console.log(JSON.stringify({
  account: {
    id: account.id,
    username: account.username ?? null,
    credits: account.credits ?? null,
    darkmode: Boolean(account.darkmode),
  },
  darkModeWrite,
  billing: {
    paymentTier: billing.payment_tier ?? null,
    autoTopupEnabled: billing.auto_topup_enabled ?? null,
  },
  invoiceCount: Array.isArray(invoices.invoices) ? invoices.invoices.length : 0,
}, null, 2));
