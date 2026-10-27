#!/usr/bin/env python3
"""
skillcrawl.py - engine for the /skillcrawl Claude Code plugin.

This script does the mechanical work (crawling, batching 5 pages at a time,
state tracking, report files, re-check diffing). Claude does the judgment work
(spelling / grammar / punctuation / content-vs-document checks) by reading the
batch files this script produces and writing an issues.json for each batch.

Run from your project folder (where skillcrawl.config.json lives).

Commands
  init                      create a starter skillcrawl.config.json
  prepare [--url U] [--doc D] [--force]
                            read the document, discover site pages, start run 1
  next-batch                fetch the next 5 pending pages into .skillcrawl/batches/...
  submit <batch_dir>        read <batch_dir>/issues.json, update state, write batch report
  finalize                  close the run: classify fixed / open, write summary + open_issues.csv
  recheck-start             start a re-check run (only changed pages + pages with open issues)
  status                    show progress
"""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, urldefrag

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("Missing dependencies. Run:  pip install -r requirements.txt  "
             "(file is in the plugin folder)")

CONFIG_NAME = "skillcrawl.config.json"
WORK = ".skillcrawl"
STATE_PATH = os.path.join(WORK, "state.json")
UA = "SkillCrawl/0.1 (content-checker)"
SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".css", ".js",
            ".json", ".xml", ".pdf", ".zip", ".gz", ".mp4", ".mp3", ".woff", ".woff2",
            ".ttf", ".eot", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".rss")
ISSUE_TYPES = {"spelling", "grammar", "punctuation", "content_mismatch",
               "missing_content", "consistency", "broken_page", "other"}

DEFAULT_CONFIG = {
    "document": "",
    "url": "",
    "batch_size": 5,
    "max_pages": 100,
    "max_depth": 4,
    "use_sitemap": True,
    "respect_robots": True,
    "render_js": False,
    "strip_query": True,
    "delay_seconds": 0.5,
    "timeout_seconds": 20,
    "exclude_patterns": [],
    "ignore_terms": [],
    "report_dir": "./skillcrawl-reports",
    "notify_webhook": "",
}


# ----------------------------------------------------------------- helpers
def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def norm(s):
    s = (s or "").replace("\u2019", "'").replace("\u2018", "'")
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", s).strip()


def sha(s):
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()


def die(msg):
    print("ERROR: " + msg)
    sys.exit(1)


def load_config(overrides=None):
    if not os.path.exists(CONFIG_NAME):
        die(f"{CONFIG_NAME} not found in {os.getcwd()}. Run: skillcrawl.py init")
    with open(CONFIG_NAME, encoding="utf-8") as f:
        user = json.load(f)
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(user)
    for k, v in (overrides or {}).items():
        if v:
            cfg[k] = v
    return cfg


def load_state():
    if not os.path.exists(STATE_PATH):
        die("No state found. Run 'prepare' first (or /skillcrawl --fresh).")
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    os.makedirs(WORK, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)


# ------------------------------------------------------------- document
def extract_document(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            die("pypdf missing. pip install pypdf")
        reader = PdfReader(path)
        return "\n\n".join(f"[Page {i + 1}]\n{p.extract_text() or ''}"
                           for i, p in enumerate(reader.pages))
    if ext == ".docx":
        try:
            import docx
        except ImportError:
            die("python-docx missing. pip install python-docx")
        d = docx.Document(path)
        parts = [p.text for p in d.paragraphs]
        for t in d.tables:
            for row in t.rows:
                parts.append(" | ".join(c.text.strip() for c in row.cells))
        return "\n".join(parts)
    if ext in (".html", ".htm"):
        with open(path, encoding="utf-8", errors="replace") as f:
            return BeautifulSoup(f.read(), "html.parser").get_text("\n", strip=True)
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def write_doc_files(text):
    os.makedirs(WORK, exist_ok=True)
    with open(os.path.join(WORK, "doc.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    chunk_dir = os.path.join(WORK, "doc_chunks")
    os.makedirs(chunk_dir, exist_ok=True)
    for old in os.listdir(chunk_dir):
        os.remove(os.path.join(chunk_dir, old))
    chunks, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        if len(cur) + len(para) > 4000 and cur:
            chunks.append(cur)
            cur = ""
        cur += para + "\n\n"
    if cur.strip():
        chunks.append(cur)
    for i, c in enumerate(chunks, 1):
        with open(os.path.join(chunk_dir, f"{i:03d}.txt"), "w", encoding="utf-8") as f:
            f.write(c)
    return len(chunks)


# ---------------------------------------------------------------- fetching
def fetch_js(url, timeout):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        die("render_js is true but playwright is not installed. "
            "pip install playwright && playwright install chromium")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        resp = page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
        html = page.content()
        status = resp.status if resp else 0
        browser.close()
    return status, html


def fetch(url, cfg):
    """Return (status_code, html, error_string)."""
    try:
        if cfg["render_js"]:
            status, html = fetch_js(url, cfg["timeout_seconds"])
            return status, html, ""
        r = requests.get(url, headers={"User-Agent": UA},
                         timeout=cfg["timeout_seconds"])
        ctype = r.headers.get("content-type", "")
        if "html" not in ctype and "xml" not in ctype and "text" not in ctype:
            return r.status_code, "", f"non-HTML content-type: {ctype}"
        r.encoding = r.apparent_encoding if r.encoding in (None, "ISO-8859-1") else r.encoding
        return r.status_code, r.text, ""
    except Exception as e:  # network errors etc.
        return 0, "", f"{type(e).__name__}: {e}"


def extract_page(html, url):
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "template", "svg"]):
        t.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    meta = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    meta_desc = (meta.get("content") or "").strip() if meta else ""
    alts = [i.get("alt").strip() for i in soup.find_all("img") if i.get("alt", "").strip()]
    body = soup.body or soup
    text = body.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    out = [f"URL: {url}", f"TITLE: {title}", f"META_DESCRIPTION: {meta_desc}",
           "--- BODY ---", text]
    if alts:
        out += ["--- IMAGE ALT TEXTS ---"] + alts
    return "\n".join(out)


def extract_links(html, base):
    soup = BeautifulSoup(html, "html.parser")
    return [urljoin(base, a["href"]) for a in soup.find_all("a", href=True)]


# ------------------------------------------------------------- URL logic
def host_key(netloc):
    n = netloc.lower()
    return n[4:] if n.startswith("www.") else n


def norm_url(url, cfg):
    url, _ = urldefrag(url.strip())
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return None
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    query = "" if cfg["strip_query"] else p.query
    out = f"{p.scheme}://{p.netloc.lower()}{path}"
    return out + ("?" + query if query else "")


def allowed_url(url, start, cfg, robots):
    p = urlparse(url)
    if host_key(p.netloc) != host_key(urlparse(start).netloc):
        return False
    if p.path.lower().endswith(SKIP_EXT):
        return False
    for pat in cfg["exclude_patterns"]:
        if re.search(pat, url):
            return False
    if robots and not robots.can_fetch(UA, url):
        return False
    return True


def load_robots(start, cfg):
    if not cfg["respect_robots"]:
        return None
    from urllib.robotparser import RobotFileParser
    p = urlparse(start)
    rp = RobotFileParser()
    try:
        r = requests.get(f"{p.scheme}://{p.netloc}/robots.txt",
                         headers={"User-Agent": UA}, timeout=cfg["timeout_seconds"])
        if r.status_code == 200:
            rp.parse(r.text.splitlines())
            return rp
    except Exception:
        pass
    return None


def sitemap_urls(sm_url, cfg, out, depth=0, seen=None):
    seen = seen if seen is not None else set()
    if depth > 3 or sm_url in seen:
        return
    seen.add(sm_url)
    try:
        r = requests.get(sm_url, headers={"User-Agent": UA}, timeout=cfg["timeout_seconds"])
        if r.status_code != 200:
            return
        root = ET.fromstring(r.content)
    except Exception:
        return
    is_index = root.tag.split("}")[-1] == "sitemapindex"
    for el in root.iter():
        if el.tag.split("}")[-1] == "loc" and el.text:
            loc = el.text.strip()
            if is_index:
                sitemap_urls(loc, cfg, out, depth + 1, seen)
            else:
                out.append(loc)


def discover_urls(cfg):
    start = norm_url(cfg["url"], cfg)
    if not start:
        die("Invalid url in config.")
    robots = load_robots(start, cfg)
    found = []

    if cfg["use_sitemap"]:
        p = urlparse(start)
        sm_list = [f"{p.scheme}://{p.netloc}/sitemap.xml"]
        if robots and hasattr(robots, "site_maps") and robots.site_maps():
            sm_list = list(robots.site_maps()) + sm_list
        raw = []
        for sm in sm_list:
            sitemap_urls(sm, cfg, raw)
        for u in raw:
            nu = norm_url(u, cfg)
            if nu and allowed_url(nu, start, cfg, robots):
                found.append(nu)

    if not found:  # no sitemap -> follow links
        queue, seen = deque([(start, 0)]), {start}
        while queue and len(found) < cfg["max_pages"]:
            url, depth = queue.popleft()
            if not allowed_url(url, start, cfg, robots):
                continue
            status, html, _ = fetch(url, cfg)
            found.append(url)
            time.sleep(cfg["delay_seconds"])
            if status == 200 and depth < cfg["max_depth"]:
                for link in extract_links(html, url):
                    nu = norm_url(link, cfg)
                    if nu and nu not in seen:
                        seen.add(nu)
                        queue.append((nu, depth + 1))

    ordered, seen_o = [start], {start}
    for u in found:
        if u not in seen_o:
            seen_o.add(u)
            ordered.append(u)
    return ordered[: cfg["max_pages"]]


# -------------------------------------------------------------- commands
def cmd_init(_):
    if os.path.exists(CONFIG_NAME):
        die(f"{CONFIG_NAME} already exists.")
    with open(CONFIG_NAME, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2)
    print(f"Created {CONFIG_NAME}. Edit 'document' and 'url', then run /skillcrawl.")


def cmd_prepare(args):
    cfg = load_config({"url": args.url, "document": args.doc})
    if os.path.exists(STATE_PATH) and not args.force:
        die("State already exists. Use --force to start fresh, or recheck-start.")
    if not cfg["url"]:
        die("No 'url' in config (or --url).")
    if not cfg["document"] or not os.path.exists(cfg["document"]):
        die(f"Document not found: {cfg['document']!r}. Set 'document' in {CONFIG_NAME}.")
    text = extract_document(cfg["document"])
    if len(text.strip()) < 20:
        die("Document text looks empty (scanned PDF? OCR it first).")
    n_chunks = write_doc_files(text)
    urls = discover_urls(cfg)
    state = {
        "created": now(), "url": cfg["url"], "document": cfg["document"],
        "doc_hash": sha(text), "run": 1, "mode": "initial", "batch_counter": 0,
        "open_batch": None, "run_seen": {},
        "pages": {u: {"status": "pending", "hash": None, "checked_run": 0} for u in urls},
        "issues": {},
    }
    save_state(state)
    print(f"DOC_CHARS={len(text)} DOC_CHUNKS={n_chunks}")
    print(f"PAGES_FOUND={len(urls)}")
    print(f"BATCHES_EXPECTED={-(-len(urls) // cfg['batch_size'])}")


def pending_urls(state):
    return [u for u, p in state["pages"].items() if p["status"] == "pending"]


def cmd_next_batch(_):
    cfg = load_config()
    state = load_state()

    if state.get("open_batch"):  # resume an unsubmitted batch
        b = state["open_batch"]
        print_batch(b["dir"], state)
        return

    pend = pending_urls(state)
    if not pend:
        print("NO_MORE_BATCHES")
        return

    urls = pend[: cfg["batch_size"]]
    state["batch_counter"] += 1
    bid = f"run{state['run']:02d}_batch{state['batch_counter']:03d}"
    bdir = os.path.join(WORK, "batches", bid)
    os.makedirs(bdir, exist_ok=True)

    pages = []
    for i, url in enumerate(urls, 1):
        status, html, err = fetch(url, cfg)
        time.sleep(cfg["delay_seconds"])
        entry = {"url": url, "http_status": status, "error": err, "file": None, "hash": None}
        if status == 200 and html:
            text = extract_page(html, url)
            fpath = os.path.join(bdir, f"page_{i}.txt")
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(text)
            entry["file"] = fpath
            entry["hash"] = sha(text)
        else:
            entry["error"] = err or f"HTTP {status}"
        pages.append(entry)

    manifest = {"batch_id": bid, "run": state["run"], "created": now(),
                "ignore_terms": cfg["ignore_terms"], "pages": pages}
    with open(os.path.join(bdir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    state["open_batch"] = {"id": bid, "dir": bdir}
    save_state(state)
    print_batch(bdir, state)


def print_batch(bdir, state):
    with open(os.path.join(bdir, "manifest.json"), encoding="utf-8") as f:
        m = json.load(f)
    remaining = len(pending_urls(state))
    print(f"BATCH_DIR={bdir}")
    print(f"BATCH_ID={m['batch_id']}")
    print(f"PAGES_IN_BATCH={len(m['pages'])}")
    print(f"PENDING_TOTAL_INCLUDING_THIS_BATCH={remaining}")
    print(f"IGNORE_TERMS={json.dumps(m['ignore_terms'])}")
    for p in m["pages"]:
        if p["file"]:
            print(f"PAGE file={p['file']} url={p['url']}")
        else:
            print(f"PAGE_ERROR url={p['url']} error={p['error']}")
    print(f"WRITE_ISSUES_TO={os.path.join(bdir, 'issues.json')}")


def make_issue_id(url, itype, found):
    return hashlib.sha1(f"{url}|{itype}|{norm(found).lower()}".encode()).hexdigest()[:8]


CSV_COLS = ["issue_id", "status", "severity", "type", "page_url", "found_text",
            "suggestion", "source_reference", "explanation", "first_seen_run",
            "assignee", "dev_status", "dev_notes"]


def write_csv(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: Excel-friendly
        w = csv.DictWriter(f, fieldnames=CSV_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def issue_row(iid, issue, label):
    return {"issue_id": iid, "status": label, "severity": issue.get("severity", "medium"),
            "type": issue["type"], "page_url": issue["page_url"],
            "found_text": issue.get("found_text", ""), "suggestion": issue.get("suggestion", ""),
            "source_reference": issue.get("source_reference", ""),
            "explanation": issue.get("explanation", ""),
            "first_seen_run": issue.get("first_seen_run", ""),
            "assignee": "", "dev_status": "", "dev_notes": ""}


SEV_ORDER = {"high": 0, "medium": 1, "low": 2}


def write_md(path, title, rows, extra_lines=None):
    lines = [f"# {title}", "", f"Generated: {now()}", ""]
    lines += extra_lines or []
    if not rows:
        lines.append("No issues in this report.")
    for r in sorted(rows, key=lambda r: (SEV_ORDER.get(r["severity"], 1), r["page_url"])):
        lines += [
            f"## [{r['issue_id']}] {r['type']} ({r['severity']}) - {r['status']}",
            f"- **Page:** {r['page_url']}",
            f"- **Found:** {r['found_text']}" if r["found_text"] else "- **Found:** (missing content)",
            f"- **Suggested:** {r['suggestion']}",
        ]
        if r["source_reference"]:
            lines.append(f"- **Source reference:** {r['source_reference']}")
        if r["explanation"]:
            lines.append(f"- **Why:** {r['explanation']}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def cmd_submit(args):
    cfg = load_config()
    state = load_state()
    bdir = args.batch_dir
    with open(os.path.join(bdir, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    ipath = os.path.join(bdir, "issues.json")
    if not os.path.exists(ipath):
        die(f"{ipath} not found. Write the issues file first (use [] if no issues).")
    try:
        with open(ipath, encoding="utf-8") as f:
            raw_issues = json.load(f)
    except json.JSONDecodeError as e:
        die(f"issues.json is not valid JSON: {e}")
    if isinstance(raw_issues, dict):
        raw_issues = raw_issues.get("issues", [])

    page_text = {}
    for p in manifest["pages"]:
        if p["file"]:
            with open(p["file"], encoding="utf-8") as f:
                page_text[p["url"]] = norm(f.read())
    run = state["run"]
    ignore = {t.lower() for t in cfg["ignore_terms"]}
    accepted, dropped = [], []

    # automatic issues for pages that could not be fetched
    for p in manifest["pages"]:
        gone_on_recheck = state["mode"] == "recheck" and p["http_status"] in (404, 410)
        if not p["file"] and not gone_on_recheck:
            accepted.append({"page_url": p["url"], "type": "broken_page", "severity": "high",
                             "found_text": f"HTTP {p['http_status']}",
                             "suggestion": "Page could not be loaded. Fix or remove the link.",
                             "explanation": p["error"]})

    for it in raw_issues:
        url = norm_url(it.get("page_url", ""), cfg) or it.get("page_url", "")
        itype = it.get("type", "other")
        itype = itype if itype in ISSUE_TYPES else "other"
        found = it.get("found_text", "") or ""
        if url not in page_text:
            dropped.append((url, "page not in this batch"))
            continue
        if found and norm(found) not in page_text[url]:
            dropped.append((url, f"found_text not verbatim on page: {found[:60]!r}"))
            continue
        if not found and itype not in ("missing_content", "content_mismatch", "consistency", "other"):
            dropped.append((url, "no found_text"))
            continue
        if itype == "spelling" and norm(found).lower() in ignore:
            continue
        if any(t and t in norm(found).lower() for t in ignore) and itype in ("spelling", "grammar"):
            continue
        sev = it.get("severity", "medium")
        sev = sev if sev in SEV_ORDER else "medium"
        accepted.append({"page_url": url, "type": itype, "severity": sev, "found_text": found,
                         "suggestion": it.get("suggestion", ""),
                         "source_reference": it.get("source_reference", ""),
                         "explanation": it.get("explanation", "")})

    rows = []
    for it in accepted:
        key = it.get("found_text") or it.get("suggestion", "")
        iid = make_issue_id(it["page_url"], it["type"], key)
        existing = state["issues"].get(iid)
        if existing is None:
            it["first_seen_run"] = run
            it["status"] = "open"
            label = "new"
        else:
            label = "regressed" if existing["status"] == "fixed" else "still_open"
            it["first_seen_run"] = existing.get("first_seen_run", run) if label != "regressed" else run
            it["status"] = "open"
        it["last_seen_run"] = run
        state["issues"][iid] = it
        state["run_seen"][iid] = label
        rows.append(issue_row(iid, it, label))

    # update page state
    for p in manifest["pages"]:
        pg = state["pages"].setdefault(p["url"], {})
        gone = (not p["file"]) and p["http_status"] in (404, 410) and state["mode"] == "recheck"
        pg["status"] = "gone" if gone else "done"
        pg["hash"] = p["hash"]
        pg["checked_run"] = run
    state["open_batch"] = None
    save_state(state)

    rdir = cfg["report_dir"]
    base = os.path.join(rdir, manifest["batch_id"])
    write_csv(base + ".csv", rows)
    write_md(base + ".md", f"SkillCrawl report - {manifest['batch_id']}", rows)

    left = len(pending_urls(state))
    print(f"SUBMITTED {manifest['batch_id']}: {len(rows)} issues recorded "
          f"({sum(1 for r in rows if r['status']=='new')} new, "
          f"{sum(1 for r in rows if r['status']=='regressed')} regressed)")
    for url, why in dropped:
        print(f"DROPPED_ISSUE {url}: {why}")
    print(f"REPORT={base}.csv")
    print(f"PENDING_PAGES={left}")


def cmd_finalize(_):
    cfg = load_config()
    state = load_state()
    run = state["run"]
    if state.get("open_batch"):
        die("There is an unsubmitted batch. Submit it first.")
    pend = pending_urls(state)
    if pend:
        die(f"{len(pend)} pages still pending. Keep running next-batch.")

    fixed_now = []
    for iid, it in state["issues"].items():
        if it["status"] != "open" or iid in state["run_seen"]:
            continue
        pg = state["pages"].get(it["page_url"], {})
        if pg.get("checked_run") == run:  # page was re-checked and issue is gone
            it["status"] = "fixed"
            it["fixed_run"] = run
            fixed_now.append(iid)
    save_state(state)

    open_rows = []
    for iid, it in state["issues"].items():
        if it["status"] == "open":
            label = state["run_seen"].get(iid, "still_open")
            open_rows.append(issue_row(iid, it, label))
    counts = {k: sum(1 for r in open_rows if r["status"] == k)
              for k in ("new", "still_open", "regressed")}

    rdir = cfg["report_dir"]
    latest_csv = os.path.join(rdir, "open_issues.csv")
    write_csv(latest_csv, open_rows)
    run_csv = os.path.join(rdir, f"run{run:02d}_open_issues.csv")
    write_csv(run_csv, open_rows)

    pages_total = len(state["pages"])
    pages_checked = sum(1 for p in state["pages"].values() if p.get("checked_run") == run)
    summary = [f"- Run: {run} ({state['mode']})",
               f"- Pages known: {pages_total}; checked this run: {pages_checked}",
               f"- Open issues: {len(open_rows)} (new {counts['new']}, "
               f"still open {counts['still_open']}, regressed {counts['regressed']})",
               f"- Fixed since last run: {len(fixed_now)}", ""]
    if not open_rows:
        summary.append("**ALL CLEAR - no open issues.**")
    write_md(os.path.join(rdir, f"run{run:02d}_summary.md"),
             f"SkillCrawl summary - run {run}", open_rows, summary)

    line = (f"SkillCrawl run {run}: ALL CLEAR ({len(fixed_now)} fixed)" if not open_rows else
            f"SkillCrawl run {run}: {len(open_rows)} open issues "
            f"({counts['new']} new, {counts['still_open']} still open, "
            f"{counts['regressed']} regressed), {len(fixed_now)} fixed. "
            f"Report: {run_csv}")
    if cfg["notify_webhook"]:
        try:
            requests.post(cfg["notify_webhook"], json={"text": line}, timeout=15)
        except Exception as e:
            print(f"(webhook failed: {e})")
    print("ALL_CLEAR" if not open_rows else f"OPEN_ISSUES={len(open_rows)}")
    print(line)
    print(f"OPEN_ISSUES_CSV={latest_csv}")
    print(f"SUMMARY_MD={os.path.join(rdir, f'run{run:02d}_summary.md')}")


def cmd_recheck_start(_):
    cfg = load_config()
    state = load_state()
    if state.get("open_batch"):
        die("Unsubmitted batch exists. Submit it first.")
    if pending_urls(state):
        die("Current run is not finished. Continue with next-batch.")
    if not os.path.exists(cfg["document"]):
        die(f"Document not found: {cfg['document']}")

    state["run"] += 1
    run = state["run"]
    state["mode"] = "recheck"
    state["run_seen"] = {}
    state["batch_counter"] = 0

    text = extract_document(cfg["document"])
    doc_changed = sha(text) != state.get("doc_hash")
    write_doc_files(text)
    state["doc_hash"] = sha(text)

    # add newly discovered pages
    for u in discover_urls(cfg):
        state["pages"].setdefault(u, {"status": "pending", "hash": None, "checked_run": 0})

    open_pages = {it["page_url"] for it in state["issues"].values() if it["status"] == "open"}
    n_pending = n_skipped = n_gone = 0
    for url, pg in state["pages"].items():
        if pg["status"] == "pending":
            n_pending += 1
            continue
        status, html, _err = fetch(url, cfg)
        time.sleep(cfg["delay_seconds"])
        if status in (404, 410):
            pg["status"], pg["checked_run"] = "gone", run
            n_gone += 1
            continue
        new_hash = sha(extract_page(html, url)) if status == 200 and html else None
        changed = new_hash != pg.get("hash")
        if doc_changed or changed or url in open_pages or pg["status"] != "done":
            pg["status"] = "pending"
            n_pending += 1
        else:
            pg["checked_run"] = run  # unchanged and clean -> counts as checked
            n_skipped += 1
    save_state(state)
    print(f"RECHECK_RUN={run}")
    print(f"DOC_CHANGED={doc_changed}")
    print(f"PAGES_TO_CHECK={n_pending} UNCHANGED_SKIPPED={n_skipped} GONE={n_gone}")


def cmd_status(_):
    state = load_state()
    pages = state["pages"]
    by = {}
    for p in pages.values():
        by[p["status"]] = by.get(p["status"], 0) + 1
    open_n = sum(1 for i in state["issues"].values() if i["status"] == "open")
    fixed_n = sum(1 for i in state["issues"].values() if i["status"] == "fixed")
    print(f"run={state['run']} mode={state['mode']} pages={by} "
          f"open_issues={open_n} fixed_issues={fixed_n} "
          f"open_batch={'yes' if state.get('open_batch') else 'no'}")


def main():
    ap = argparse.ArgumentParser(description="SkillCrawl engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(fn=cmd_init)
    p = sub.add_parser("prepare")
    p.add_argument("--url")
    p.add_argument("--doc")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_prepare)
    sub.add_parser("next-batch").set_defaults(fn=cmd_next_batch)
    s = sub.add_parser("submit")
    s.add_argument("batch_dir")
    s.set_defaults(fn=cmd_submit)
    sub.add_parser("finalize").set_defaults(fn=cmd_finalize)
    sub.add_parser("recheck-start").set_defaults(fn=cmd_recheck_start)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
