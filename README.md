# SkillCrawl - check a website against a document

Give it a **website link** and a **document** (Word, PDF, or an image / scan of one). It reads
**every page** of the website and tells you, page by page and section by section:

- spelling, grammar, commas, full stops and other punctuation mistakes
- text that **does not match the document** (wrong price, date, phone, name...)
- pages that are **in the document but missing from the website**
- broken pages / dead links

Developers get a clear **fix report**. When they say "fixed", QA runs **the same command again**
and SkillCrawl re-checks, tells you what is fixed, what is still open, and what is new.

---

## Step-by-step guide

### Part A - One-time install (once per computer, about 5 minutes)

1. Install **Claude Code** (https://claude.com/claude-code) and **Python 3.8 or newer**.
   Nothing else is needed - SkillCrawl installs its own helpers the first time it runs.
2. Open a terminal and type `claude` to start Claude Code.
3. Type these two lines, one at a time (replace the first with this repo's GitHub address):
   ```
   /plugin marketplace add <your-github-user>/<this-repo>
   /plugin install skillcrawl@skillcrawl-marketplace
   ```
4. Close Claude Code and open it again (restart).

### How QA gives the website and the document

There is no upload button. QA just **types a link or a file name** after `/skillcrawl`
(or answers Claude's two questions). Three ways to give the document:

| Document is... | What QA types as the document |
|---|---|
| A file on your computer (Word, PDF, Excel, CSV, image) | Put it in the project folder and type its name: `content.docx` - or the full path: `C:\Users\me\Downloads\content.pdf` |
| A **Google Sheet / Google Doc / Google Slides** | Paste the link from the browser address bar. First click **Share -> General access -> "Anyone with the link"** (Viewer). |
| A PDF / Word file in **Google Drive** | Same: set to "Anyone with the link", paste the link. |
| Any file with a direct download link | Paste the link. |

The website is always a link: `https://yoursite.com` (start from the home page).

Examples:

```
/skillcrawl https://yoursite.com content.pdf
/skillcrawl https://yoursite.com https://docs.google.com/spreadsheets/d/1AbC.../edit
/skillcrawl https://yoursite.com "C:\Users\me\Desktop\site content.docx"
```

Notes:
- **Google links are downloaded again on every run**, so when the client edits the Sheet, the
  next `/skillcrawl` re-check automatically uses the new content.
- If a Google link is private, SkillCrawl tells you in plain words to change the sharing
  setting - or use **File -> Download** (as `.xlsx`, `.docx` or `.pdf`) and give it the file.
- **Google Sheet layout:** any layout works, but it reads best with one row per page, e.g.
  column A = page name, column B = the content for that page. Each tab is read as a section.
- Old `.doc` / `.xls` files: open them and **Save As** `.docx` / `.xlsx` first.

### Part B - Run the first check (QA)

1. Create a folder for the project, for example `website-check`.
2. Put the document in that folder (e.g. `content.docx`, `content.pdf`, `content.xlsx` or
   `content.png`) - or have its Google link ready (see the section above).
3. Open a terminal **inside that folder** and type `claude`.
4. Type `/skillcrawl` and press Enter.
   - Claude asks **"What is the website link?"** - paste it, e.g. `https://yoursite.com`
   - Claude asks **"Where is the document?"** - type the file name (`content.docx`) or paste the
     Google Sheet / Doc / Drive link
   - Shortcut: type both at once - `/skillcrawl https://yoursite.com content.docx`
5. Wait. Claude finds every page, reads them five at a time, and shows progress such as
   *"Checked 10 of 24 pages - 7 issues so far"*. Do not close the window until it finishes.
   - If your document is an image or scan, Claude reads it first (you do nothing).
6. When it says it is finished, Claude tells you how many pages were read and how many issues
   were found, and where the report is: **`skillcrawl-reports/FIX_REPORT.html`**.
7. Open the report: double-click `FIX_REPORT.html` (it opens in your browser). Skim it - the
   occasional false alarm is possible, so delete or ignore any row that is not a real problem.

### Part C - Give the issues to developers (QA)

Pick whichever way your team works:

| Way | What to do |
|---|---|
| **Send the report file** | Email or chat `skillcrawl-reports/FIX_REPORT.html` to the developer. It opens in any browser, nothing to install. |
| **Excel / Google Sheets** | Send `skillcrawl-reports/FIX_REPORT.csv`. Upload it to Google Sheets or open it in Excel. Fill the `assignee` column to give each row to a person. |
| **Tickets (Jira, ClickUp, etc.)** | One CSV row = one ticket. Import the CSV, or create one ticket per **page** and paste that page's rows. |
| **Shared folder / Git** | Put the whole `skillcrawl-reports` folder in the team's shared drive or repo. |

Tell the developer:

> "Open the report. For each **page**, find the **Section**, replace the text in *Currently says*
> with the text in *Change it to / action*, and publish. Fix the **high** priority rows first."

**What the developer does with each row**

1. Open the page link shown at the top of the card.
2. Find the **section** named in the row (it is the heading on that page).
3. Find the exact text under **Currently says** (shown struck through).
4. Replace it with the text under **Change it to / action** (shown in green).
5. If the row says **Page missing from website**, create that page - it is in the document but
   not on the website. If it says **Page broken / not loading**, fix the page or remove the link
   pointing to it.
6. Optional: type your name in `assignee` and `done` in `dev_status` in the CSV. These notes are
   kept the next time QA re-checks.

### Part D - After developers say "fixed" (QA re-check)

QA does **not** need to upload anything again.

1. Open a terminal in the **same project folder** and type `claude`.
2. Type `/skillcrawl` again (or `/skillcrawl:recheck`) and press Enter.
3. SkillCrawl remembers the website and document, re-reads the pages that changed or had issues,
   and also picks up any **new pages** developers added.
4. Open the new `skillcrawl-reports/FIX_REPORT.html`. It shows:
   - **FIXED** - the developer fixed it, it is gone from the list
   - **STILL OPEN** - not fixed yet (send back to the developer)
   - **NEW** - a new mistake introduced since last time
   - **REOPENED** - fixed before, but it came back
5. Send the new report to the developers. Repeat Part D until Claude says **ALL CLEAR**.

If the document itself changed (new content from the client), just replace the file with the same
name and run `/skillcrawl` again - every page is re-checked against the new document.

### Quick reference

| I want to... | Type |
|---|---|
| First check, or re-check after fixes | `/skillcrawl` |
| Same thing, other name | `/skillcrawl:recheck` |
| Use another website or document | `/skillcrawl https://other-site.com other.pdf` |
| Throw everything away and start over | `/skillcrawl --fresh` |

(If your Claude Code version namespaces plugin commands, use `/skillcrawl:skillcrawl`.)

### Troubleshooting

| Problem | Fix |
|---|---|
| `/skillcrawl` is not found | Restart Claude Code after installing; run `/plugin` and check `skillcrawl` is enabled. |
| "Document not found" | Put the document in the folder you opened the terminal in, or give the full path. |
| "pip" / install error on first run | Make sure Python 3.8+ is installed (`python3 --version`), then run `/skillcrawl` again. |
| The report says pages look empty | The site needs JavaScript to show text - ask your developer to enable `render_js` (see settings below). |
| Too many false alarms for brand names | Add them to `ignore_terms` in `skillcrawl.config.json`. |

## What the developer sees

`FIX_REPORT.html` lists each **page** (with its link), and under it every problem as one row:

| Section on page | Currently says | Change it to / action | Type | Priority | Status |
|---|---|---|---|---|---|
| Opening Hours | ~~9 AM - 5 PM~~ | **9 AM - 6 PM** (Document: Home: Opening hours) | Does not match document | high | NEW |

It also lists the pages that were checked (so QA can confirm nothing was skipped), what was fixed
since last time, and website pages that the document does not mention. `FIX_REPORT.csv` has the
same rows plus empty `assignee`, `dev_status` and `dev_notes` columns - what developers type
there is kept in the next re-check. Older reports are kept in `skillcrawl-reports/history/`.

## What documents work

| Document | How it is read |
|---|---|
| Word `.docx` | text, headings and tables (old `.doc`: save as `.docx` first) |
| Excel `.xlsx`, CSV, **Google Sheet** | every tab and row is read; cells are joined with `|` |
| **Google Doc / Slides** | downloaded automatically (link must be "Anyone with the link") |
| PDF with text | read directly, page by page |
| Scanned / image-only PDF | each page is turned into an image and **Claude reads it** |
| Image (`.png .jpg .jpeg .webp .gif .bmp .tif`) | **Claude reads the image**; a folder of images = multiple pages |
| `.txt .md .html` | read directly |

Image documents are copied by Claude word for word (typos included), so make sure the image is
sharp and complete.

## How every page is found

SkillCrawl follows every link starting from the home page **and** reads the website's
`sitemap.xml`, then combines both - so pages missing from the sitemap are still checked. Up to 300
pages by default (it warns you if the site is bigger; change `max_pages`). Links that lead
nowhere are reported as broken pages.

## How the re-check decides

Every issue gets a stable ID (page + type + exact text).

- no longer on the page -> **fixed**
- still there -> **still open**
- not seen before -> **new**
- was fixed but came back -> **reopened**
- a page that still returns 404 while links point to it stays a **broken page**
- nothing open -> **ALL CLEAR**

## Optional settings (`skillcrawl.config.json`, created automatically)

`ignore_terms` (brand names never to flag), `max_pages`, `exclude_patterns` (parts of the site to
skip, like `/blog`), `render_js` (sites that only show text with JavaScript - needs
`pip install playwright && playwright install chromium`), `notify_webhook` (Slack message with the
summary), `report_dir`.

## Run it automatically (no QA needed)

`plugins/skillcrawl/scheduler/` has a daily cron example, a script, and a GitHub Actions workflow
that run `/skillcrawl` (= re-check) on a schedule and can post the summary to Slack.

## Try it with the included sample

`plugins/skillcrawl/examples/sample-demo/` has a small website with deliberate mistakes and the
matching document in Word, PDF, scanned-PDF and image form. Serve it with
`cd plugins/skillcrawl/examples/sample-demo/site && python3 -m http.server 8765` and run
`/skillcrawl http://127.0.0.1:8765 ../content.docx` from another folder.

## Honest limits

- Claude does the proofreading, so the occasional false alarm is possible. The engine drops any
  issue whose quoted text is not really on the page, and `ignore_terms` removes known noise, but
  skim the report before assigning it.
- Pages behind a login are not checked.
- Which document page belongs to which website page is judged by Claude from headings and
  content, so it works best when the document has clear page names.
