# OmniXat — Interactive Prototype v0.4 (Fictional Family Workspace)

This is a **working, local, deliberately fictional** UK tax and compliance prototype. The interface supports **unlimited manually created people, companies and self-employment activities**, with independently recorded Self Assessment years, company tax periods, company-person roles, subject-scoped questions/tasks, due-date views and a **self-reported filing-status register**. The Playwright Browser Lab from v0.3 is retained.

**Not a tax-filing product. No authentication, individual logins, permission controls, encryption of family financial data, official filing-status checks, HMRC filing, tax calculations or remote access. Do not enter real names, tax IDs, accounts, credentials, financial data or personal documents.** The selector is **filtering only**, not authorisation. Run on your own local machine with **fictional information**.

## Start on Ubuntu

Use the Docker Compose service (includes Chromium for Browser Lab):

```bash
docker compose up --build -d
# open http://127.0.0.1:8765
docker compose ps
```

The browser image is large. The app uses a Docker-managed SQLite database volume which survives container restart. Port `8765` is bound to localhost only.

Alternatively, use Python 3.11+ (no dependencies except for optional Browser Lab):

```bash
python3 app.py
# open http://127.0.0.1:8765
# Optional for Browser Lab:
python3 -m pip install 'playwright==1.57.0'
python3 -m playwright install chromium
```

Do not publish this service to the internet or a home-network interface. If you switch from v0.3, back up the old demo SQLite database before upgrading.

## Interactive tour

1. **People & businesses:** Add fictional people, register their self-employed activities, and link one or more people to companies as directors, shareholders, etc. One company can be linked to several people.
2. **Viewing selector (top bar):** Choose *Entire workspace*, one person, a company, or an individual self-employment activity. The dashboard, calendar, questions, tasks, activity and filing records change to match that subject.
3. **Tax profiles:** Each person's Self Assessment year is stored independently; two people may both have year 2025–26. Corporation Tax periods belong to companies.
4. **Return statuses:** Enter a fictional status and evidence note against a person or company and a specified return period. The statuses `Submitted`, `Accepted` and `Rejected` are **self-reported demo labels only**—they are not checked or acknowledged by a government service. Tracked filing dates appear separately as **not independently checked**, not automatically overdue/unfiled.
5. **Questions and tasks:** New subject profiles get their own questions. Tasks created under a selected person/company/activity attach to that subject; shared workspace tasks appear when viewing all.
6. **Calendar:** Dates filter by the selected subject; exporting `.ics` only exports the visible subject's dates.
7. **Browser Lab:** Retains v0.3's **fictional localhost-only Playwright workflow**, including a review screen, separate approval and demo receipt. Real government site automation is not enabled.
8. **Reset demo:** Deletes the demo changes and restores the fictional example dataset. It is destructive; the UI requests confirmation.

## Migration from v0.3

Opening an existing v0.3 SQLite file upgrades the schema in place **without deleting existing company profiles, questions, tasks, browser runs, or historic shared Self Assessment-year settings**. The old `years` records were not associated with people and are deliberately **preserved as unassigned legacy data**. A warning appears when viewing the entire workspace's tax profiles. Add the relevant fictional person and re-enter each tax-year obligation under them after reviewing it; the app never silently assumes which family member a legacy record belonged to.

When starting with a new database, the demo seeds two explicitly fictional people, two self-employed activities, two roles linked to one company and one company Corporation Tax period. These are examples, not hard-coded restrictions. Later people and companies receive UUID identifiers. A user/person distinction and role-based access control **are not implemented yet**.

## Test the prototype

```bash
python3 -m unittest discover -s tests -p 'test*.py' -v
python3 tests/browser_smoke.py
python3 tests/browser_household_ui.py
python3 tests/browser_lab_ui_smoke.py
node --check static/app.js
```

The GUI tests use the actual HTML/CSS/JS in Chromium with a local API bridge if the hosted environment does not permit browser navigation to loopback. The API and Browser Lab real-HTTP paths have separate integration tests. The scripts currently expect `/usr/bin/chromium` for the GUI tests; the Browser Lab itself can use Playwright-managed Chromium.

## Architecture / future milestone

`household.py` contains the fictional multi-subject schema, subject-aware state queries and mutations. `app.py` remains the v0.3 demo server. It uses SQLite now solely for ease of local testing, not as a decision to abandon the **authenticated PostgreSQL foundation** in [draft PR #1](https://github.com/EnigmaThe1/OmniXat/pull/1).

Before any genuine family records: build authenticated accounts separate from taxpayer identities, per-subject access rights, migrations, encrypted documents/credentials, tested backups, audits, safe deletion/retention and data provenance. All tax calculations must remain deterministic and versioned, and official HMRC submissions require supported API workflows and explicit approvals. Public SaaS billing/multi-tenancy are still deferred.
