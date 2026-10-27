# SkillCrawl - Claude Code plugin

Checks every page of a website against a source document (PDF / DOCX / TXT / MD / HTML):
spelling, grammar, commas, full stops, and content that does not match the document.
Works through the site **5 pages at a time**, writes a report file per batch for developers,
and can **re-check** later to see what was fixed, what is still open, and what is new.

No uploading each time: the document path and website URL live in a config file.

## 1. Install

Requirements: Claude Code, Python 3.9+, internet access from your terminal.

```bash
# unzip this folder somewhere permanent, then:
pip install -r skillcrawl-marketplace/plugins/skillcrawl/requirements.txt
```

Inside Claude Code:

```
/plugin marketplace add /absolute/path/to/skillcrawl-marketplace
/plugin install skillcrawl@skillcrawl-marketplace
```

Restart Claude Code. Quick test without installing:

```bash
claude --plugin-dir /absolute/path/to/skillcrawl-marketplace/plugins/skillcrawl
```

Plugin commands may be namespaced. Type `/skillcrawl`; if it is not offered, use
`/skillcrawl:skillcrawl`. (Plugin packaging changes between Claude Code versions - if a step
differs, check `/plugin` help or the current Claude Code plugin docs.)

## 2. Configure a project

In the project folder where you run Claude Code, create `skillcrawl.config.json`
(copy `plugins/skillcrawl/examples/skillcrawl.config.json`):

```json
{
  "document": "./docs/content-source.pdf",
  "url": "https://yoursite.com",
  "batch_size": 5,
  "max_pages": 100,
  "ignore_terms": ["YourBrand"]
}
```

Other options: `max_depth`, `use_sitemap`, `respect_robots`, `render_js` (needs Playwright),
`strip_query`, `delay_seconds`, `exclude_patterns` (regex list), `report_dir`,
`notify_webhook` (Slack-style webhook that receives the run summary).

## 3. Use it

| Command | What it does |
|---|---|
| `/skillcrawl` | First run: reads the document, finds pages (sitemap or link crawl), checks 5 at a time |
| `/skillcrawl --recheck` | Re-checks changed pages + pages with open issues; marks fixed / still open / new / regressed |
| `/skillcrawl --fresh` | Throws away old state and starts over |
| `/skillcrawl --url https://other.com --doc ./other.pdf` | Override config for this run |

Output in `skillcrawl-reports/`:

- `runNN_batchMMM.csv` / `.md` - one report per batch of 5 pages
- `open_issues.csv` - always the latest full list of open issues (give this to developers;
  it has empty `assignee`, `dev_status`, `dev_notes` columns)
- `runNN_summary.md` - counts and details per run; says **ALL CLEAR** when nothing is open

State is kept in `.skillcrawl/state.json` (keep it; the re-check needs it).

## 4. Schedule the re-check

`plugins/skillcrawl/scheduler/` contains:

- `run_recheck.sh` - runs `claude -p "/skillcrawl --recheck"` non-interactively
- `crontab.example` - daily cron entry
- `github-action.example.yml` - scheduled GitHub Actions workflow

Check `claude --help` for the exact headless flags and permission options on your version.

## 5. How the re-check decides

Each issue gets a stable ID (hash of page + type + the exact offending text).

- ID no longer found on a re-checked page -> **fixed**
- ID found again -> **still open** (goes into the new report)
- ID not seen before -> **new**
- A fixed ID that comes back -> **regressed**
- Page now 404 -> its issues are closed; page that errors -> `broken_page` issue
- Nothing open -> ALL CLEAR, no new report needed

## 6. Known limits

- Claude's judgment is not perfectly identical between runs. The plugin reduces noise by
  requiring each reported `found_text` to appear verbatim on the page and by using an
  `ignore_terms` list, but expect occasional false positives - review before assigning.
- Scanned/image-only PDFs have no text; OCR them first.
- JavaScript-rendered sites need `"render_js": true` plus `pip install playwright && playwright install chromium`.
- Large sites use many tokens. Start with a small `max_pages`.
- Respect the site's terms of service; only crawl sites you own or have permission to check.
