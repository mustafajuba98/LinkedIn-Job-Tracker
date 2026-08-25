# LinkedIn Job Tracker

Copyright (c) 2026 Juba

Local Python app that checks saved LinkedIn job searches, stores new jobs in SQLite, shows them in a simple web UI, and sends a desktop notification when a genuinely new job appears.

It runs entirely on your machine. There is no AI, auto-apply, email, Telegram, Docker, or cloud deployment.

## Installation

```bash
python -m venv venv
```

Windows activation:

```bash
venv\Scripts\activate
```

Install:

```bash
pip install -r requirements.txt
playwright install chromium
```

Run:

```bash
python app.py
```

Then open:

```text
http://127.0.0.1:8000
```

The app tries to open that address in your browser automatically.

## How searches work

Each saved search has a name, keywords, and location. The app turns those fields into a normal LinkedIn job-search URL, for example:

```text
https://www.linkedin.com/jobs/search/?keywords=Python%20Backend&location=Egypt
```

On first run it creates these default searches, all with location `Egypt`:

- Python Backend
- Django Developer
- Backend Engineer Python
- FastAPI Developer

You can change or delete them later.

## How to change searches

Open **Saved Searches** at [http://127.0.0.1:8000/settings](http://127.0.0.1:8000/settings).

From there you can:

- Add a search
- Edit a search
- Delete a search
- Enable or disable a search

Disabled searches are skipped by both the scheduler and **Check Now**.

## How the scheduler works

APScheduler runs every `CHECK_INTERVAL_MINUTES` minutes. The default is 5 minutes, set in `config.py`.

Each cycle:

1. Load enabled saved searches
2. Open each LinkedIn search in Chromium (Playwright)
3. Read job cards from the results
4. Insert jobs whose `linkedin_id` is not already in SQLite
5. Send a desktop notification only for jobs that are actually new

Use **Check Now** on the web UI if you do not want to wait for the next interval.

## How new-job detection works

Every job is stored with a unique `linkedin_id`.

- If LinkedIn exposes a job id, that id is used
- Otherwise the app derives a stable id from the job URL

If `linkedin_id` already exists, the job is ignored. Restarting the app does not notify again for jobs that are already in `jobs.db`.

The first scan of a search saves whatever is currently listed and does **not** send notifications. That avoids a flood of alerts for jobs that were already on LinkedIn. Later scans notify only for jobs that were not stored before.

## How notifications work

New jobs trigger a native desktop notification through `plyer`, for example:

```text
New LinkedIn Job

Backend Engineer
ABC Company
Egypt

Click/Open the application to view it.
```

If the operating system cannot show notifications, the error is logged and the app keeps running.

## Configuration

Edit `config.py`:

```python
CHECK_INTERVAL_MINUTES = 5
HEADLESS = True
DATABASE_URL = "sqlite:///./jobs.db"
MAX_JOBS_PER_SEARCH = 50
```

Set `HEADLESS = False` if you want to watch the browser while it opens LinkedIn. That is often useful when LinkedIn shows a login wall or blocks headless Chromium.

## Known LinkedIn limitations

LinkedIn is not a public API, and it may:

- Show a login / auth wall
- Limit or empty-out results for automated browsers
- Change its HTML, which can break card parsing
- Rate-limit or block repeated checks

This app does **not** try to bypass authentication, CAPTCHA, rate limits, or bot detection. It only opens the public job search page and reads visible results. If LinkedIn blocks access, that search fails with a clear error and the rest of the app keeps running.

Other limits of this first version:

- It reads search-result cards, not the full job description page
- Remote / hybrid / on-site is recorded only when the listing says so
- Results per search are capped by `MAX_JOBS_PER_SEARCH`
- You still open LinkedIn yourself and apply manually

## Tests

```bash
pytest
```

## License

Copyright (c) 2026 Juba

This project is owned by **Juba**, the copyright holder.

It is licensed under the [GNU Affero General Public License v3.0 (AGPL-3.0)](LICENSE).
You may use, modify, and share it under the terms of that license.
