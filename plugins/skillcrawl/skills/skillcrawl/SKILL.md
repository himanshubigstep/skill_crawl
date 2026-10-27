---
name: skillcrawl
description: Rubric for checking website page text against a source document - spelling, grammar, punctuation (commas, full stops) and factual/content mismatches. Used by the /skillcrawl command; also use when the user asks to proofread web pages against a reference document.
---

# SkillCrawl checking rubric

Goal: produce **accurate, reproducible** issue lists. Developers will fix what you report and
a later re-check will compare results, so consistency matters more than volume. When unsure,
do not report.

## What to check on every page

Page files contain `TITLE`, `META_DESCRIPTION`, `BODY` and `IMAGE ALT TEXTS`. Check all of them.
Headings in the body are tagged `[H1]`..`[H6]` so you can see the page structure. Never include
the `[H2]` tag in `found_text`, and do not flag the tags themselves. The engine uses these tags to
tell the developer which section of the page each issue is in.

1. **Spelling** - misspelled words, wrong word forms, doubled words ("the the").
2. **Grammar** - subject/verb agreement, tense, articles, plurals ("Our plans starts" ->
   "Our plans start"), wrong prepositions, sentence fragments that are clearly errors.
3. **Punctuation** - missing/extra commas, missing full stops at the end of sentences,
   double spaces or double punctuation, wrong apostrophes ("its/it's"), unmatched quotes or
   brackets, missing question marks, comma splices.
   - Headings, buttons, menu items, list items and short labels do not need full stops; do not
     flag their absence. Flag inconsistency only when the same type of element mixes styles
     on one page (type `consistency`, severity low).
   - Oxford comma: do not flag either style unless the page is inconsistent with itself.
4. **Content correctness vs the source document** - compare the page with the relevant part of
   the document:
   - numbers, prices, dates, times, phone numbers, emails, addresses, percentages
   - names, titles, product names, specs, features, claims, policies
   - The document marks its pages / sections with `[Page N]` markers or `# Heading` lines; use
  them to decide which part of the document belongs to which website page.
- `content_mismatch`: page says something that contradicts the document
   - `missing_content`: the document says something the page should contain but does not
     (only when the page clearly covers that topic; do not report an absent topic as missing
     on unrelated pages)
   - Differences in wording that mean the same thing are NOT mismatches.
   Page-level gaps (a document page that has no page on the website at all) are NOT reported
   per batch - the coverage step after the batches handles them.
5. If a page has no relation to the document (e.g. a cookie policy), only run checks 1-3.

## What NOT to flag

- Anything in `IGNORE_TERMS` printed by next-batch (brand names, jargon, codes).
- Style preferences, tone, or rewording that is not an error.
- Regional spelling variants (colour/color) unless the document uses the other one
  consistently - then report as `consistency`, severity low.
- Navigation/footer text repeated on every page: report it ONCE (on the first page where it
  appears in the batch) and skip the repeats.
- Names, addresses and quotes that look intentional.

## Severity

- **high**: wrong price/number/date/contact info, contradicts document, key claim wrong,
  broken page
- **medium**: grammar errors, misspellings in body text, missing required content
- **low**: minor punctuation, consistency, alt text, double spaces

## Accuracy rules (important)

- `found_text` must be copied **verbatim** from the page file, short but unique (one phrase
  or sentence, not a whole paragraph). The same text with the same error must always be
  reported the same way so the re-check can match it.
- One issue per distinct error. Do not merge unrelated errors; do not split one error.
- `suggestion` must be the exact corrected text a developer can paste in.
- For content issues put the document location in `source_reference`
  (e.g. "[Page 3] Pricing table").

## Reading an image / scanned document

When the engine asks for transcription, copy the text from the image **exactly as shown**, including
any typos, odd punctuation and numbers. Do not fix anything while transcribing - the document is the
source of truth. If text is unreadable, write `[unreadable]` for that part and do not use it for
checks.

## Writing issues a developer can act on

The report developers receive shows, per item: the page, the section, an instruction, a red box
("currently on the site") and a green box ("change it to"). So:

- `found_text` = the exact current text (a whole phrase / sentence, never cut mid-word).
- `suggestion` = ONLY the final replacement text, or for missing content the complete text from
  the document. No commentary in it - the report highlights the changed words by comparing the two.
- `instruction` = one plain sentence ("Change the closing time from 5 PM to 6 PM."). Optional for
  simple replacements - it is generated from found_text and suggestion.
- Several documents: compare each page only with the file shown in its `document=` path.
