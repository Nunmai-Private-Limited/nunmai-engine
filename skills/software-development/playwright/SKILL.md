---
name: playwright
description: "Browser automation & end-to-end testing with Playwright: scripts, scraping, form flows, screenshots, test suites."
version: 1.0.0
author: Nunmai Research
license: MIT
platforms: [linux, macos, windows]
metadata:
  nunmai:
    tags: [browser, automation, testing, e2e, scraping, playwright]
    related_skills: [dogfood]
---

# Playwright — browser automation and E2E testing

## Overview

Use this skill when the user wants to automate a website, scrape data, fill forms,
take screenshots/PDFs, or write/run end-to-end tests. Two ways to work:

1. **Built-in browser toolset** (`browser_navigate`, `browser_snapshot`, `browser_click`,
   `browser_type`, `browser_vision`, `browser_console`, `browser_scroll`, `browser_back`,
   `browser_press`) — fastest for interactive, one-off tasks. Backed by Playwright.
2. **Playwright scripts/tests** (Node or Python) — for repeatable jobs and test suites the
   user keeps in their project.

## Setup (first use)

Nunmai Engine installs lightweight by default. Install browsers once:

```bash
# Node (recommended for test suites)
npm init playwright@latest        # in the user's project, or:
npx playwright install chromium   # browsers only

# Python
pip install playwright && playwright install chromium
```

If the built-in browser tools report "browser unavailable", run
`cd ~/.nunmai/nunmai-engine && npm install && npx playwright install chromium`
(or reinstall with `curl -fsSL https://nunmai-engine.nunmai.in/install.sh | bash -s -- --full`).

## Workflow

1. **Clarify** target URL, credentials (never store them in code), and the goal
   (data out / action done / test written).
2. **Explore** with `browser_navigate` + `browser_snapshot` to learn selectors. Prefer
   role/text locators (`getByRole`, `getByText`, `getByLabel`) over CSS/XPath.
3. **Script** it (Node example):

```ts
import { test, expect } from '@playwright/test';

test('login works', async ({ page }) => {
  await page.goto('https://example.com/login');
  await page.getByLabel('Email').fill(process.env.LOGIN_EMAIL!);
  await page.getByLabel('Password').fill(process.env.LOGIN_PASSWORD!);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
});
```

Python example:

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://example.com")
    print(page.title())
    page.screenshot(path="home.png", full_page=True)
    browser.close()
```

4. **Run**: `npx playwright test` (add `--ui` for the inspector, `--headed` to watch).
   Use `npx playwright codegen <url>` to record actions into code.
5. **Harden**: wait on assertions (`expect(...).toBeVisible()`), not `sleep`; set
   `baseURL`, retries and traces in `playwright.config.ts`; keep secrets in env vars.
6. **Report**: for scraping, write results to CSV/JSON in the project; for tests, show the
   `npx playwright test` summary and where the HTML report lives (`npx playwright show-report`).

## Gotchas

- Headless Chromium on Linux servers needs system deps: `npx playwright install-deps chromium`.
- Sites with bot protection may need `use_real_profile` (see `nunmai browser --help`) or a
  headed run; do not attempt to evade CAPTCHAs.
- Respect robots.txt / terms of service for scraping; throttle requests.
