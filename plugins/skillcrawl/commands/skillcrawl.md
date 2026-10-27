---
description: Check every page of a website against a source document (spelling, grammar, punctuation, content match) in batches of 5 and write developer reports. Use --recheck to verify fixes.
argument-hint: [--recheck] [--fresh] [--url URL] [--doc PATH]
allowed-tools: Bash, Read, Write
---

You are running **SkillCrawl**. Arguments given by the user: `$ARGUMENTS`

The document and website are normally read from `skillcrawl.config.json` in the current
project folder, so the user does NOT need to upload anything. Run the whole workflow
below without stopping to ask questions (this may run unattended from a scheduler).

## Step 0 - Locate the engine script

Use `${CLAUDE_PLUGIN_ROOT}/scripts/skillcrawl.py`. If that path does not exist (variable
empty), find it with:
`find ~/.claude/plugins "$PWD" -name skillcrawl.py -path "*scripts*" 2>/dev/null | head -1`

Call it `SC` below and always run it as `python3 "$SC" <command>` from the project folder.
If Python complains about missing modules, run
`pip install -r <plugin folder>/requirements.txt` once, then retry.

If `skillcrawl.config.json` does not exist, run `python3 "$SC" init`, tell the user to edit
the `document` and `url` fields, and STOP.

## Step 1 - Decide the mode

- `--recheck` in arguments -> run `python3 "$SC" recheck-start`, then go to Step 2.
- `--fresh` in arguments (or `.skillcrawl/state.json` does not exist) -> run
  `python3 "$SC" prepare --force` (add `--url`/`--doc` if the user passed them), then Step 2.
- Otherwise, run `python3 "$SC" status`. If pages are still pending, resume at Step 2.
  If the run is complete, tell the user to use `/skillcrawl --recheck` (verify fixes) or
  `/skillcrawl --fresh` (start over) and STOP.

## Step 2 - Read the rules and the source document

Read the `skillcrawl` skill (`skills/skillcrawl/SKILL.md` in the plugin folder) for the
checking rubric. Then read `.skillcrawl/doc.txt` (the source-of-truth document). If it is
very large (over ~40,000 characters), read `.skillcrawl/doc_chunks/*.txt` selectively per page
instead.

## Step 3 - Batch loop (5 pages at a time)

Repeat until the script prints `NO_MORE_BATCHES`:

1. Run `python3 "$SC" next-batch`. It prints `BATCH_DIR`, one `PAGE file=... url=...` line per
   page, and `WRITE_ISSUES_TO`.
2. Read each page file in the batch and check it (rubric in the skill):
   - spelling, grammar, commas, full stops and other punctuation
   - content correctness against the source document
3. Write a JSON array to the `WRITE_ISSUES_TO` path (use `[]` if the batch is clean).
   Each issue is an object:
   ```json
   {
     "page_url": "exact URL from the PAGE line",
     "type": "spelling | grammar | punctuation | content_mismatch | missing_content | consistency | other",
     "severity": "high | medium | low",
     "found_text": "EXACT text copied verbatim from the page file (empty only for missing_content)",
     "suggestion": "the corrected text, or what the document says",
     "source_reference": "document section / [Page N] marker for content issues, else empty",
     "explanation": "one short sentence"
   }
   ```
   `found_text` MUST be copied exactly from the page file; the script drops issues whose
   text it cannot find on the page.
4. Run `python3 "$SC" submit <BATCH_DIR>`. It writes the batch report
   (`skillcrawl-reports/runNN_batchNNN.csv` and `.md`) for developers.
5. Print one short progress line (batch id, issues found, pages remaining) and continue.

## Step 4 - Finish

Run `python3 "$SC" finalize`. It marks fixed issues, writes `open_issues.csv` and the run
summary, and prints either `ALL_CLEAR` or `OPEN_ISSUES=n`.

Final message to the user (keep it short): pages checked, issues new / still open /
regressed / fixed, and the paths of `skillcrawl-reports/open_issues.csv` and the summary file.
For a first run, remind them to hand the CSV to developers and later run `/skillcrawl --recheck`.
