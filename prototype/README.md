# OmniXat — Interactive Prototype v0.3

A **working, deliberately fictional** personal-first UK tax/compliance GUI. Version 0.3 adds the Playwright **Browser Lab**: launch a browser workflow, read a practice portal, fill fields, inspect a review screen, require explicit owner approval, and click a **local demo-only submit** button to obtain a fictional receipt.

This is a **prototype, not a tax filing tool**. It has **no authentication** and is **not safe for real financial information or exposure beyond your own computer**.

## Option 1: Docker Compose (recommended on Ubuntu)

```bash
docker compose up --build -d
# Open http://127.0.0.1:8765
docker compose logs -f demo
```

Docker downloads the official Playwright browser image (size is relatively large, typically over 1 GB). No API keys or external accounts needed. Only localhost port 8765 is published.

## Option 2: Python (smallest install)

Requires Python 3.11+; the original dashboard works without additional packages.

```bash
python3 -m pip install 'playwright==1.57.0'  # use a venv on Ubuntu if needed
python3 -m playwright install chromium
python3 app.py
# Open http://127.0.0.1:8765
```

If your system already has Chromium, the driver will detect its path, or you can set `OMNIXAT_CHROMIUM_PATH`. Without Playwright installed the other screens still work; **Browser Lab** shows the install instructions instead of a fake success.

## Test the interface

- **Overview** shows obligations and preparation readiness.
- **Companies** can add *fictional* records.
- **Tax profiles** configures demo Self Assessment and Corporation Tax periods.
- **Questions** saves guided sample answers.
- **Tasks** adds/completes preparation work.
- **Tax calendar** groups dates and exports a `.ics` file.
- **Browser Lab** opens the bundled practice website, fills three fields, reads the review page, captures a real browser screenshot and waits for explicit approval. The final click submits only to a local simulation endpoint and returns a `DEMO-...` receipt. You can click **Open practice website** to inspect the form manually.
- **Reset demo** restores the initial fictional dataset, including browser run history.

The database uses SQLite in a local file and persists changes between restarts. Docker stores it in a named volume. This is intentionally separate from OmniXat's authenticated PostgreSQL application foundation and is not a final architecture choice.

## Development validation

```bash
python3 -m unittest discover -s tests -v
python3 tests/browser_smoke.py
python3 tests/browser_lab_ui_smoke.py
node --check static/app.js  # optional: Node.js only for a syntax check
```

The last two scripts require `playwright` and local Chromium, and the current GUI smoke scripts expect `/usr/bin/chromium`. The server/API tests run the real local HTTP service. In environments that disallow Chromium navigation to localhost, Browser Lab loads the same practice page HTML/CSS/JS *inside a real Chromium tab* and bridges only the local demo receipt; this mode is recorded in the action log.

## Browser access roadmap and restrictions

The general future design is **official API → authorised browser workflow → manual hand-off**. This release accepts **no arbitrary website URLs**, no agent-generated JavaScript and no stored login credentials. Its Playwright driver is allowlisted to the local practice website, blocks other page requests and uses a fresh isolated browser context for every run.

Browser interaction **must not bypass** restrictions, access controls, captchas or MFA. HMRC's published May 2026 policy says tools must **not** simulate human interaction with Government Gateway; use official APIs or a user-controlled manual hand-off for HMRC. Site-specific legal and technical approval is needed before enabling third-party automation.

**Never enter real UK tax identifiers, bank information, personal data, passwords or live accounts in this alpha.** No actual tax calculations or submissions are implemented. No AI agent/model is connected.

## Next production steps

1. Port the tested GUI to the authenticated FastAPI/PostgreSQL application (draft PR #1), with migrations and a secure data model.
2. Introduce an integration registry recording allowed methods, host allowlists, identity and permission rules, risk/approval policy, and evidence provenance for each service.
3. Add opt-in, restricted-site browser drivers where permitted, with durable browser jobs, an interactive user hand-off, screenshots/traces protected as personal data, and correct timeout/retry semantics.
4. Add the ledger, document processing, deterministic tax rules and audited HMRC/Companies House API adapters.
