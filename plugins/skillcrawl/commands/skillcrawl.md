---
description: Check every page of a website against a document (Word / PDF / image) for spelling, grammar, punctuation and content mismatches. Run it again after developers fix things to re-check automatically.
argument-hint: [website-link] [document-path]   (both optional after the first run; --fresh starts over)
allowed-tools: Bash, Read, Write, Edit, mcp__claude-in-chrome__tabs_context_mcp, mcp__claude-in-chrome__tabs_create_mcp, mcp__claude-in-chrome__navigate, mcp__claude-in-chrome__get_page_text, mcp__claude-in-chrome__tabs_close_mcp
---

You are running **SkillCrawl**. The user may be non-technical: be friendly, use plain words, never
show raw errors or JSON without explaining them. Arguments: `$ARGUMENTS`

Work through the steps WITHOUT stopping to ask questions, except in Step 1 (missing link /
document). The same command is used for the first check AND for every later re-check.

## Step 0 - Locate the engine

`SC="${CLAUDE_PLUGIN_ROOT}/scripts/skillcrawl.py"`. If that path does not exist, find it with
`find ~/.claude/plugins "$PWD" -name skillcrawl.py -path "*scripts*" 2>/dev/null | head -1`.
Always run `python3 "$SC" <command>` from the user's project folder. The engine installs its
own Python packages on first use - do not ask the user to install anything.

## Step 1 - Setup (only if needed)

QA can share ONE document or SEVERAL (for example `Homepage.docx`, `About-Us.docx`, `Dining.pdf`,
a whole folder, or several links). **The file name is the page name**: the engine matches each
file to the website page with the same name (using the page address, the menu / link text and
the page title), and checks that page against that file only.

If `$ARGUMENTS` (or the user's message) contains a website link and/or documents (file paths
`.docx .pdf .xlsx .csv .png .jpg ...`, a folder, or Google Sheet / Doc / Drive links), save them:
`python3 "$SC" setup --url "<link>" --doc "<file1>" "<file2>" ...` (pass only what you have).
Quote paths that contain spaces. The website link is the one that is not a document.

If the document is a **tracker Google Sheet / Excel that links to the real content docs** (e.g. a
"Content Plan" tab with one Google Doc link per page), do NOT download them by hand: pass the tab
name(s) with `--sheet-links "Content Plan"` (the user says which tab holds the content links; default
to the tab named like "Content"). The engine opens every document link in that tab, skips Figma links,
Drive folders and "Redirection to Taj" rows, and names each file "<hotel> - <page>" (or just the page
name) so it is matched to its own website page. Tell the user how many links it found (`SHEET_LINKS`).

If the user wants only certain pages checked while sharing ONE document (e.g. "Homepage, About
Us, Dining"), work out the matching URLs from the site's menu and pass `--pages "/path1,/path2"`.
With SEVERAL files only the matched pages are checked; add `--all-pages` to also check the rest of
the site. If a Google Sheet only holds *links* to the real content documents, open it, find the
content docs for those pages, download each (`https://docs.google.com/document/d/<id>/export?format=docx`)
into a folder and use those files.

Then run `python3 "$SC" auto` (add `--fresh` if the user passed `--fresh`).
If it prints `NEEDS_SETUP`, ask the user in plain words for what is missing:
1. "What is the website link?"  2. "Which document(s)? Give file names, a folder, or Google links -
   Word, PDF, Excel, CSV and images all work, and you can give several."
Optionally ask for brand names that should never be flagged (`--ignore "Name1,Name2"`).
For a Google link, tell them it must be shared as "Anyone with the link can view".

### Private Google link (fallback: Claude in Chrome)

Before the first `auto` of every run, delete old copies: `rm -rf .skillcrawl/browser_docs`.
If `auto` prints `DOC_PRIVATE=<link>` and `BROWSER_DOC_FILE=<path>`, the link is not shared publicly.
Do not stop - read it through the user's own signed-in Chrome (needs the Claude in Chrome extension):
1. `tabs_context_mcp` (createIfEmpty), then `tabs_create_mcp` for a new tab.
2. Open a plain-text view of the link with `navigate`: a Google Doc
   `https://docs.google.com/document/d/<id>/mobilebasic`; a Google Sheet
   `https://docs.google.com/spreadsheets/d/<id>/htmlview`. (Other Drive files: skip to the fallback below.)
3. `get_page_text` on that tab. Write the text, unchanged and complete, to `BROWSER_DOC_FILE`
   (make the folder first). Keep headings on their own lines. Close the tab with `tabs_close_mcp`.
4. Run `python3 "$SC" auto` again (add `--fresh` only if it was used the first time).
If the browser tools are missing, the page asks the user to sign in, or the text is empty, tell the user
in plain words: share the link as "Anyone with the link", or download the file and give it instead.
Never type passwords or sign in for the user.

## Step 2 - Follow what `auto` printed

- `MODE=FIRST_RUN` - a new check started. Tell the user how many pages will be checked
  (`PAGES_TO_CHECK`). If a `WARNING_PAGES_CAPPED` line appears, tell them and how to raise `max_pages`.
- `MODE=RECHECK` - re-check of an earlier run (developers have presumably fixed things).
  Tell the user how many pages will be re-read (`PAGES_TO_CHECK`).
- `MODE=RESUME` - an earlier run was interrupted; continue it.
- `MODE=NEEDS_DOCUMENT_TRANSCRIPTION` or any output containing `DOC_NEEDS_TRANSCRIPTION=n` -
  the document is an image or scan. For EVERY `DOC_IMAGE=<png>` line: `Read` that image (you can
  see images) and replace its `[[TRANSCRIBE: <png>]]` marker inside `.skillcrawl/doc.txt` with the
  complete text of the image, **exactly as printed - copy typos too, never correct them**. Keep
  headings as lines starting with `# `. Then run `python3 "$SC" doc-ready`, then
  `python3 "$SC" auto` again and follow its output.

### Several documents: confirm the file -> page matching

When `auto` printed `FILE_MATCH name -> url` lines, glance at them and tell the user the pairs in
one short list ("Homepage -> /en-in ..."). If a match is clearly wrong, or a file shows
`FILE_UNMATCHED` although the website HAS that page (find it in the site menu), fix it with
`python3 "$SC" map --file "<file name>" --url "<page URL or /path>"`. Leave `FILE_UNMATCHED` alone
when the page truly does not exist - the report will list it as "page missing from the website".

## Step 3 - Read the rules and the document

Read the `skillcrawl` skill (`skills/skillcrawl/SKILL.md`, next to `commands/`) for the checking
rubric. With ONE document, read `.skillcrawl/doc.txt` (the source of truth; if over ~40,000 characters read
`.skillcrawl/doc_chunks/*.txt` selectively). With SEVERAL documents do NOT read everything up front:
for each page read only the file(s) named in that page's `document=` path in Step 4.

## Step 4 - Batch loop (5 pages at a time, ALL pages)

Repeat until the script prints `NO_MORE_BATCHES`:

1. `python3 "$SC" next-batch` prints `BATCH_DIR`, a `PAGE file=... url=... document=...` line per page
   (`document=` is the source-of-truth file for that page; `NONE` = check spelling/grammar only),
   `PAGE_ERROR` lines for pages that did not load (the engine reports those automatically),
   `PAGE_WARNING` lines, and `WRITE_ISSUES_TO`.
2. `Read` every page file in the batch and check it (rubric in the skill): spelling, grammar,
   commas, full stops and other punctuation, and content versus the document. Check the page
   title, meta description and image alt text too - not only the body.
3. Write a JSON array to the `WRITE_ISSUES_TO` path (`[]` if the batch is clean). Issue shape:
   ```json
   {
     "page_url": "exact URL from the PAGE line",
     "type": "spelling | grammar | punctuation | content_mismatch | missing_content | consistency | other",
     "severity": "high | medium | low",
     "found_text": "EXACT text copied verbatim from the page file (empty only for missing_content)",
     "suggestion": "ONLY the final text: the corrected text, or for missing_content the full text to add, copied from the document",
     "instruction": "one short plain sentence telling the developer what to do",
     "section": "heading the text sits under (only needed for missing_content)",
     "source_reference": "document file + heading, e.g. Homepage.docx: Opening hours",
     "explanation": "one short sentence on why"
   }
   ```
   - The developer reads a report built from these fields, so write them for a person who has not seen
     the document: `suggestion` is copy-paste text (never instructions or "see document"); put the
     words of advice in `instruction`. For missing content paste the COMPLETE text from the document.
   - Use `consistency` / `other` for "someone must decide" items (the `suggestion` then lists the options).
   - `found_text` MUST be copied exactly from the page file, short but unique (a full sentence or
     phrase; never cut mid-word). The engine drops issues whose text it cannot find on the page,
     and works out the page section by itself.
4. `python3 "$SC" submit <BATCH_DIR>`.
5. Print one short progress line ("Checked 10 of 24 pages - 7 issues so far") and continue.

## Step 5 - Match the document's pages to the website's pages

**Skip this step when several documents were shared** (the file -> page matching already covers it).

Run `python3 "$SC" pages` (lists every page that was read: `name | url`). Read the document's
page / section names. Write `.skillcrawl/coverage.json`: one entry per page or major section of
the DOCUMENT:
`[{"doc_page": "Careers", "url": "<matching website URL or null>", "note": "what the document says it contains"}]`
Use `null` only when the website really has no such page. Write `[]` if the document has no
page structure at all. Then `python3 "$SC" coverage-submit`.

## Step 6 - Finish

`python3 "$SC" finalize` writes the developer report and prints `ALL_CLEAR` or `OPEN_ISSUES=n`.

Final message to the user (short, plain, no jargon):
- pages read (`PAGES_READ` of `PAGES_ON_SITE`) and the totals: new / still open / reopened / fixed
- the report to open: `skillcrawl-reports/FIX_REPORT.html` (double-click it, or share it with the
  developers) - and `FIX_REPORT.xlsx` for Excel / Google Sheets
- first run: "Send the report to your developers. When they say it is fixed, just run
  `/skillcrawl` again."
- re-check with open issues: list the headline numbers; ALL_CLEAR: say everything matches.
