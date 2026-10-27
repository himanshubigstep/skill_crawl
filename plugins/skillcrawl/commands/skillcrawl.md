---
description: Check every page of a website against a document (Word / PDF / image) for spelling, grammar, punctuation and content mismatches. Run it again after developers fix things to re-check automatically.
argument-hint: [website-link] [document-path]   (both optional after the first run; --fresh starts over)
allowed-tools: Bash, Read, Write, Edit
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

If `$ARGUMENTS` contains a website link and/or a document (a file path - `.docx .pdf .xlsx .csv
.png .jpg ...` or a folder of images - OR a link to a Google Sheet / Google Doc / Drive file /
direct file link), save them. Two links: the one for the *website* is the website; the other (or
any `docs.google.com` / `drive.google.com` link) is the document:
`python3 "$SC" setup --url "<link>" --doc "<path>"` (pass only the ones you have).

Then run `python3 "$SC" auto` (add `--fresh` if the user passed `--fresh`).
If it prints `NEEDS_SETUP`, ask the user in plain words for what is missing:
1. "What is the website link?"  2. "Where is the document - a file name, or a link (Google Sheet,
   Google Doc, Drive)? Word, PDF, Excel, CSV and images all work."
(If the document is not in the project folder, ask them for the full path, or to drop the file
into the folder. For a Google link, tell them it must be shared as "Anyone with the link can view"
- the engine prints those steps itself if the link is private.) Optionally ask for brand names that should never be flagged
(`--ignore "Name1,Name2"`). Run `setup`, then `auto` again.

## Step 2 - Follow what `auto` printed

- `MODE=FIRST_RUN` - a new check started. Tell the user how many pages were found
  (`PAGES_FOUND`). If a `WARNING_PAGES_CAPPED` line appears, tell them and how to raise `max_pages`.
- `MODE=RECHECK` - re-check of an earlier run (developers have presumably fixed things).
  Tell the user how many pages will be re-read (`PAGES_TO_CHECK`).
- `MODE=RESUME` - an earlier run was interrupted; continue it.
- `MODE=NEEDS_DOCUMENT_TRANSCRIPTION` or any output containing `DOC_NEEDS_TRANSCRIPTION=n` -
  the document is an image or scan. For EVERY `DOC_IMAGE=<png>` line: `Read` that image (you can
  see images) and replace its `[[TRANSCRIBE: <png>]]` marker inside `.skillcrawl/doc.txt` with the
  complete text of the image, **exactly as printed - copy typos too, never correct them**. Keep
  headings as lines starting with `# `. Then run `python3 "$SC" doc-ready`, then
  `python3 "$SC" auto` again and follow its output.

## Step 3 - Read the rules and the document

Read the `skillcrawl` skill (`skills/skillcrawl/SKILL.md`, next to `commands/`) for the checking
rubric. Then read `.skillcrawl/doc.txt` (the source of truth). If it is over ~40,000 characters,
read `.skillcrawl/doc_chunks/*.txt` selectively per page instead.

## Step 4 - Batch loop (5 pages at a time, ALL pages)

Repeat until the script prints `NO_MORE_BATCHES`:

1. `python3 "$SC" next-batch` prints `BATCH_DIR`, a `PAGE file=... url=...` line per page,
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
     "suggestion": "the exact corrected text a developer can paste in, or what the document says",
     "source_reference": "document heading / [Page N] for content issues, else empty",
     "explanation": "one short plain sentence"
   }
   ```
   `found_text` MUST be copied exactly from the page file, short but unique. The engine drops
   issues whose text it cannot find on the page, and works out the page section by itself.
4. `python3 "$SC" submit <BATCH_DIR>`.
5. Print one short progress line ("Checked 10 of 24 pages - 7 issues so far") and continue.

## Step 5 - Match the document's pages to the website's pages

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
  developers) - and `FIX_REPORT.csv` for Excel
- first run: "Send the report to your developers. When they say it is fixed, just run
  `/skillcrawl` again."
- re-check with open issues: list the headline numbers; ALL_CLEAR: say everything matches.
