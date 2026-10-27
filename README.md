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

### How QA gives the website and the document(s)

There is no upload button. QA just **types a link and the file names** after `/skillcrawl`
(or answers Claude's two questions).

**One document** for the whole site, or **several documents - one per page**:

| QA has... | What QA types |
|---|---|
| One file (Word, PDF, Excel, CSV, image) | `content.docx` |
| **Several files, one per page** | `Homepage.docx About-Us.docx Dining.pdf` - or just the **folder** that contains them: `docs` |
| A Google Sheet / Doc / Drive file | paste the link (Share -> "Anyone with the link") |
| A mix of files and links | list them all, separated by spaces |

**The file name is the page name.** SkillCrawl looks at the website (page address, menu names,
page titles) and matches each file to its page by name - `Homepage.docx` to the home page,
`About-Us.docx` to `/about-us`, `Dining.pdf` to the page the menu calls "Dining", and so on. Then
each page is checked against **its own file only**. It prints the pairs it found, so QA can check
them; a wrong or missing pair is fixed by telling Claude ("Dining.pdf belongs to /restaurants").
A file with no matching page on the website is reported as **"Page missing from the website"**.

With several files, only the matching pages are checked. To check the rest of the site as well
(spelling and grammar only), say so: "also check all other pages".

Examples:

```
/skillcrawl https://yoursite.com content.pdf
/skillcrawl https://yoursite.com docs
/skillcrawl https://yoursite.com Homepage.docx About-Us.docx Wellness.pdf
/skillcrawl https://yoursite.com https://docs.google.com/document/d/1AbC.../edit "C:\\Users\\me\\Dining.docx"
```

Notes:
- **Google links are downloaded again on every run**, so when the client edits the Doc, the next
  `/skillcrawl` re-check automatically uses the new content.
- If a Google link is private, SkillCrawl tells you in plain words to change the sharing
  setting - or use **File -> Download** and give it the file.
- **Google Sheet layout:** any layout works, but it reads best with one row per page, e.g.
  column A = page name, column B = the content. Links inside cells are kept.
- Old `.doc` / `.xls` files: open them and **Save As** `.docx` / `.xlsx` first.
- To check only some pages of the website with ONE document, tell Claude which pages
  ("only Homepage, About Us and Dining").

### Part B - Run the first check (QA)

1. Create a folder for the project, for example `website-check`.
2. Put the document(s) in that folder - one file, or one file per page named after the page
   (`Homepage.docx`, `About-Us.docx`...) - or have the Google links ready (see the section above).
3. Open a terminal **inside that folder** and type `claude`.
4. Type `/skillcrawl` and press Enter.
   - Claude asks **"What is the website link?"** - paste it, e.g. `https://yoursite.com`
   - Claude asks **"Which document(s)?"** - type the file name(s) (`Homepage.docx About-Us.docx`),
     the folder name, or paste the Google Sheet / Doc / Drive links
   - Shortcut: type both at once - `/skillcrawl https://yoursite.com content.docx`
5. Wait. Claude finds every page, reads them five at a time, and shows progress such as
   *"Checked 10 of 24 pages - 7 issues so far"*. Do not close the window until it finishes.
   - If your document is an image or scan, Claude reads it first (you do nothing).
6. When it says it is finished, Claude tells you how many pages were read and how many issues
   were found, and where the report is: **`skillcrawl-reports/FIX_REPORT.html`**.
7. Open the report: double-click `FIX_REPORT.html` (it opens in your browser). Skim it - the
   occasional false alarm is possible, so delete or ignore any row that is not a real problem.

### Part C - Give the issues to developers (QA)

Pick whichever way your team works (the HTML report is the easiest to read; the Excel file is best for assigning):

| Way | What to do |
|---|---|
| **Send the report file** | Email or chat `skillcrawl-reports/FIX_REPORT.html` to the developer. It opens in any browser, nothing to install. |
| **Excel / Google Sheets** | Send `skillcrawl-reports/FIX_REPORT.xlsx` (open in Excel or upload to Google Sheets). Fill the `Assignee` column to give each row to a person. |
| **Tickets (Jira, ClickUp, etc.)** | One row = one ticket. Import `FIX_REPORT.csv`, or create one ticket per **page** and paste that page's rows. |
| **Shared folder / Git** | Put the whole `skillcrawl-reports` folder in the team's shared drive or repo. |

Tell the developer:

> "Open the report. For each **page**, go to the **section** named on each card, replace the red
> text with the green text (or paste the green text for 'Add content'), and tick Done. Start with
> the **high priority** cards."

**What the developer does with each row**

1. Click **Open page** at the top of the page's section.
2. Find the **section** named on the card (it is the heading on that page).
3. Find the text in the **red box** (the changed words are struck through).
4. Replace it with the text in the **green box**.
5. If the row says **Page missing from website**, create that page - it is in the document but
   not on the website. If it says **Page broken / not loading**, fix the page or remove the link
   pointing to it.
6. Tick **Done** on the card. Optional: type your name in `Assignee` and `Dev status` in the Excel
   file - these notes are kept the next time QA re-checks.

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

Open `FIX_REPORT.html` in any browser. It is built so a developer can work straight down the page:

1. **Summary boxes** - how many things to fix, how many are high priority, new, fixed.
2. **"Pages and what needs doing"** - one row per page (click to jump), with counts.
3. **One section per page**, with an **Open page** link, split in two:
   - **Fix text already on the page** - listed top-to-bottom in the order they appear on the page.
   - **Add what is missing** - complete text to paste, taken from the document.
4. **Each item is a numbered card**: `#12  REPLACE TEXT  HIGH PRIORITY  NEW`, then
   **Where on the page** (the section heading), a one-line **instruction**
   ("Change the closing time from 5 PM to 6 PM."), and two boxes side by side:

   | CURRENTLY ON THE SITE (red) | CHANGE IT TO (green) |
   |---|---|
   | 9 AM - ~~5~~ PM | 9 AM - **6** PM |

   The changed words are highlighted, so even a long paragraph shows exactly what differs. Below
   the boxes: why it is wrong, which document file/section it comes from, and the issue ID.
5. A **Done** tick box on every card (remembered in the browser while the developer works).
6. At the bottom: what was **fixed since last time**, and the list of **pages checked** so QA can
   confirm nothing was skipped.

Action labels: **Replace text** - change what is there; **Add content** - paste new text;
**Create page** - the page is in the document but not on the website; **Fix page** - the page does
not load; **Review & decide** - the document and site disagree and a person must choose.

Other files in `skillcrawl-reports/`:
- `FIX_REPORT.xlsx` - the same list as a formatted Excel / Google Sheets file (filters, wrapped text,
  colored priority, plus `Assignee`, `Dev status`, `Dev notes` columns - what developers type there
  is kept at the next re-check).
- `FIX_REPORT.csv` - the same list for importing into Jira, ClickUp etc.
- `FIX_REPORT.md` - plain-text copy. Older reports are kept in `skillcrawl-reports/history/`.

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

`page_urls` (check ONLY these pages, e.g. `["/en-in", "/en-in/about-us"]`; or run `/skillcrawl` and tell Claude which pages), `ignore_terms` (brand names never to flag), `max_pages`, `exclude_patterns` (parts of the site to
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
