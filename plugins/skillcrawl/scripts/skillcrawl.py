#!/usr/bin/env python3
"""
skillcrawl.py - engine for the /skillcrawl Claude Code plugin.

This script does the mechanical work (crawling EVERY page, batching 5 pages at a
time, reading the source document - Word / PDF / image / scanned PDF, state
tracking, developer fix reports, re-check diffing). Claude does the judgment work
(spelling / grammar / punctuation / content-vs-document) by reading the batch
files this script produces and writing an issues.json for each batch.

Run from your project folder (where skillcrawl.config.json lives).

Commands
  setup --url U --doc D     create / update skillcrawl.config.json
  auto [--fresh]            decide what to do next (first run / resume / re-check)
  next-batch                fetch the next 5 pending pages into .skillcrawl/batches/...
  submit <batch_dir>        read <batch_dir>/issues.json, update state, write batch csv
  doc-ready                 confirm image/scanned document pages were transcribed
  pages                     list every page checked in this run (name + url)
  coverage-submit           read .skillcrawl/coverage.json (document page -> website page)
  finalize                  close the run, write FIX_REPORT.html / .md / .csv
  status                    show progress
"""
import argparse
import csv
import hashlib
import html as htmllib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, urldefrag

HERE = os.path.dirname(os.path.abspath(__file__))


def _ensure_deps():
    """Install the Python packages on first use so non-technical users never have to."""
    try:
        import requests  # noqa: F401
        import bs4  # noqa: F401
        return
    except ImportError:
        pass
    if os.environ.get("SKILLCRAWL_BOOT"):
        sys.exit("Could not install required packages. Run:  pip install -r "
                 + os.path.join(HERE, "..", "requirements.txt"))
    print("First-time setup: installing required Python packages (one minute)...", flush=True)
    req = os.path.join(HERE, "..", "requirements.txt")
    ok = False
    for extra in ([], ["--user"]):
        if subprocess.call([sys.executable, "-m", "pip", "install", "--quiet"] + extra
                           + ["-r", req]) == 0:
            ok = True
            break
    if not ok:  # one broken optional package must not block the rest
        for line in open(req, encoding="utf-8"):
            pkg = line.split("#")[0].strip()
            if pkg:
                subprocess.call([sys.executable, "-m", "pip", "install", "--quiet", "--user", pkg])
    os.environ["SKILLCRAWL_BOOT"] = "1"
    os.execv(sys.executable, [sys.executable] + sys.argv)


_ensure_deps()
import requests  # noqa: E402
from bs4 import BeautifulSoup, NavigableString  # noqa: E402

CONFIG_NAME = "skillcrawl.config.json"
WORK = ".skillcrawl"
STATE_PATH = os.path.join(WORK, "state.json")
DOC_TXT = os.path.join(WORK, "doc.txt")
IMG_DIR = os.path.join(WORK, "doc_images")
COVERAGE_PATH = os.path.join(WORK, "coverage.json")
UA = "SkillCrawl/0.2 (content-checker)"
SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".css", ".js",
            ".json", ".xml", ".pdf", ".zip", ".gz", ".mp4", ".mp3", ".woff", ".woff2",
            ".ttf", ".eot", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".rss")
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff")
ISSUE_TYPES = {"spelling", "grammar", "punctuation", "content_mismatch", "missing_content",
               "missing_page", "consistency", "broken_page", "other"}
TYPE_LABEL = {"spelling": "Spelling", "grammar": "Grammar", "punctuation": "Punctuation",
              "content_mismatch": "Does not match document", "missing_content": "Content missing",
              "missing_page": "Page missing from website", "consistency": "Inconsistent",
              "broken_page": "Page broken / not loading", "other": "Other"}
STATUS_LABEL = {"new": "NEW", "still_open": "STILL OPEN", "regressed": "REOPENED"}
MISSING_PAGE_URL = "(not found on website)"
TRANSCRIBE_RE = re.compile(r"\[\[TRANSCRIBE: ([^\]]+)\]\]")

DEFAULT_CONFIG = {
    "document": "",
    "url": "",
    "batch_size": 5,
    "max_pages": 300,
    "max_depth": 6,
    "use_sitemap": True,
    "respect_robots": True,
    "render_js": False,
    "strip_query": True,
    "delay_seconds": 0.2,
    "timeout_seconds": 20,
    "exclude_patterns": ["/wp-admin", "/wp-login", "/login", "/cart", "/checkout"],
    "ignore_terms": [],
    "report_dir": "./skillcrawl-reports",
    "notify_webhook": "",
}


# ----------------------------------------------------------------- helpers
def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def norm(s):
    s = (s or "").replace("’", "'").replace("‘", "'")
    s = s.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip()


def sha(s):
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()


def die(msg):
    print("ERROR: " + msg)
    sys.exit(1)


def load_config(overrides=None):
    if not os.path.exists(CONFIG_NAME):
        die(f"{CONFIG_NAME} not found in {os.getcwd()}. Run /skillcrawl and give the "
            f"website link and document.")
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
        die("No previous run found. Run /skillcrawl first.")
    with open(STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    os.makedirs(WORK, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)


# ------------------------------------------------------------- document
def _png_for_transcription(img, n):
    """Save a PIL image as a PNG (max 2200px) Claude can read; return its path."""
    os.makedirs(IMG_DIR, exist_ok=True)
    img = img.convert("RGB")
    img.thumbnail((2200, 2200))
    p = os.path.join(IMG_DIR, f"{n:03d}.png")
    img.save(p, "PNG")
    return p


def _extract_pdf(path, img_counter):
    try:
        from pypdf import PdfReader
    except ImportError:
        die("pypdf missing. Run: pip install pypdf")
    reader = PdfReader(path)
    parts, doc = [], None
    for i, pg in enumerate(reader.pages):
        txt = (pg.extract_text() or "").strip()
        if len(txt) >= 20:
            parts.append(f"[Page {i + 1}]\n{txt}")
            continue
        # scanned / image-only page -> render it so Claude can read it
        try:
            import fitz  # PyMuPDF
            from PIL import Image
        except ImportError:
            die("This PDF has scanned (image-only) pages. Run: pip install pymupdf pillow")
        if doc is None:
            doc = fitz.open(path)
        pix = doc[i].get_pixmap(matrix=fitz.Matrix(1.6, 1.6))
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        img_counter[0] += 1
        parts.append(f"[Page {i + 1}]\n[[TRANSCRIBE: {_png_for_transcription(img, img_counter[0])}]]")
    return "\n\n".join(parts)


def _extract_docx(path):
    try:
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError:
        die("python-docx missing. Run: pip install python-docx")
    d = docx.Document(path)
    parts = []
    for child in d.element.body.iterchildren():  # keeps paragraphs and tables in order
        tag = child.tag.split("}")[-1]
        if tag == "p":
            p = Paragraph(child, d)
            t = p.text
            if not t.strip():
                parts.append("")
                continue
            style = (p.style.name if p.style is not None else "") or ""
            if style.lower().startswith("heading") or style.lower() == "title":
                t = "# " + t
            parts.append(t)
        elif tag == "tbl":
            for row in Table(child, d).rows:
                parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(parts)


def _extract_xlsx(path):
    try:
        import openpyxl
    except ImportError:
        die("openpyxl missing. Run: pip install openpyxl")
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    parts = []
    for ws in wb.worksheets:
        parts.append(f"# [Sheet: {ws.title}]")
        for row in ws.iter_rows(values_only=True):
            cells = ["" if c is None else str(c).strip() for c in row]
            if any(cells):
                parts.append(" | ".join(cells).rstrip(" |"))
        parts.append("")
    return "\n".join(parts)


def _extract_csv(path):
    parts = []
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        for row in csv.reader(f):
            cells = [c.strip() for c in row]
            if any(cells):
                parts.append(" | ".join(cells).rstrip(" |"))
    return "\n".join(parts)


def _extract_one(path, img_counter):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        return _extract_xlsx(path)
    if ext == ".xls":
        die("Old .xls files are not supported. Open it in Excel and Save As .xlsx (or CSV).")
    if ext == ".csv":
        return _extract_csv(path)
    if ext == ".pdf":
        return _extract_pdf(path, img_counter)
    if ext == ".docx":
        return _extract_docx(path)
    if ext == ".doc":
        die("Old .doc files are not supported. Open it in Word and Save As .docx (or PDF).")
    if ext in IMG_EXT:
        try:
            from PIL import Image
        except ImportError:
            die("Pillow missing. Run: pip install pillow")
        img_counter[0] += 1
        png = _png_for_transcription(Image.open(path), img_counter[0])
        return f"[Page {img_counter[0]}]\n[[TRANSCRIBE: {png}]]"
    if ext in (".html", ".htm"):
        with open(path, encoding="utf-8", errors="replace") as f:
            return BeautifulSoup(f.read(), "html.parser").get_text("\n", strip=True)
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


_DOC_CACHE = {}


def _google_export_url(u):
    """Turn a Google Docs / Sheets / Slides / Drive share link into a download link."""
    m = re.search(r"docs\.google\.com/(spreadsheets|document|presentation)/d/([\w-]+)", u)
    if m:
        kind, fid = m.groups()
        fmt = {"spreadsheets": "xlsx", "document": "docx", "presentation": "pdf"}[kind]
        return f"https://docs.google.com/{kind}/d/{fid}/export?format={fmt}", "." + fmt
    m = re.search(r"drive\.google\.com/(?:file/d/|open\?id=|uc\?(?:export=download&)?id=)([\w-]+)", u)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}", ""
    return u, ""


def local_document(cfg):
    """Return a local path for the document. Links (Google Sheet / Doc / Drive file / any
    direct file link) are downloaded fresh on every run so edits are picked up."""
    src = cfg["document"]
    if not re.match(r"^https?://", src or "", re.I):
        return src
    if src in _DOC_CACHE:
        return _DOC_CACHE[src]
    url, ext = _google_export_url(src)
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=60, allow_redirects=True)
    except Exception as e:
        die(f"Could not download the document link ({type(e).__name__}). Check the link and "
            f"your internet connection.")
    ctype = r.headers.get("content-type", "").lower()
    if r.status_code != 200 or ("text/html" in ctype and "accounts.google" in r.url + r.text[:3000]) \
            or (ext and "text/html" in ctype):
        die("The document link needs permission. In Google, click Share -> General access -> "
            "'Anyone with the link' (Viewer) and try again - or download the file "
            "(File -> Download) and give me the file instead.")
    if not ext:
        cd = r.headers.get("content-disposition", "")
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', cd)
        ext = os.path.splitext(m.group(1))[1].lower() if m else ""
        if not ext:
            ext = os.path.splitext(urlparse(url).path)[1].lower()
        if not ext:
            ext = {"application/pdf": ".pdf", "text/csv": ".csv", "image/png": ".png",
                   "image/jpeg": ".jpg", "text/plain": ".txt",
                   "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
                   }.get(ctype.split(";")[0].strip(), "")
        if not ext:
            die("Could not tell what kind of file the document link is. Download it and give "
                "me the file instead.")
    os.makedirs(os.path.join(WORK, "source"), exist_ok=True)
    path = os.path.join(WORK, "source", "document" + ext)
    with open(path, "wb") as f:
        f.write(r.content)
    _DOC_CACHE[src] = path
    return path


def doc_files(path):
    if os.path.isdir(path):
        return sorted(os.path.join(path, f) for f in os.listdir(path)
                      if not f.startswith(".") and os.path.isfile(os.path.join(path, f)))
    return [path]


def source_hash(path):
    h = hashlib.sha256()
    for f in doc_files(path):
        h.update(os.path.basename(f).encode())
        with open(f, "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()


def extract_document(path):
    """Return document text. Image / scanned pages appear as [[TRANSCRIBE: png]] markers."""
    shutil.rmtree(IMG_DIR, ignore_errors=True)
    counter = [0]
    files = doc_files(path)
    if len(files) == 1:
        return _extract_one(files[0], counter)
    return "\n\n".join(f"[File: {os.path.basename(f)}]\n{_extract_one(f, counter)}" for f in files)


def write_doc_files(text):
    os.makedirs(WORK, exist_ok=True)
    with open(DOC_TXT, "w", encoding="utf-8") as f:
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


def print_transcribe_request():
    with open(DOC_TXT, encoding="utf-8") as f:
        todo = TRANSCRIBE_RE.findall(f.read())
    print(f"DOC_NEEDS_TRANSCRIPTION={len(todo)}")
    print(f"DOC_TEXT_FILE={DOC_TXT}")
    for p in todo:
        print(f"DOC_IMAGE={p}")


def load_document(cfg, state):
    """Read the document. Returns (changed, needs_transcription)."""
    path = local_document(cfg)
    if not path or not os.path.exists(path):
        die(f"Document not found: {cfg['document']!r}. Check the file name / link you gave.")
    shash = source_hash(path)
    if state and state.get("doc_source_hash") == shash and os.path.exists(DOC_TXT) \
            and not state.get("awaiting_doc"):
        return False, False  # same file as last time - keep existing text (incl. transcription)
    text = extract_document(path)
    pending = bool(TRANSCRIBE_RE.search(text))
    if not pending and len(text.strip()) < 20:
        die("The document has no readable text.")
    write_doc_files(text)
    return True, pending


# ---------------------------------------------------------------- fetching
def fetch_js(url, timeout):
    from playwright.sync_api import sync_playwright
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
        r = requests.get(url, headers={"User-Agent": UA}, timeout=cfg["timeout_seconds"])
        ctype = r.headers.get("content-type", "")
        if "html" not in ctype and "xml" not in ctype and "text" not in ctype:
            return r.status_code, "", f"non-HTML content-type: {ctype}"
        r.encoding = r.apparent_encoding if r.encoding in (None, "ISO-8859-1") else r.encoding
        return r.status_code, r.text, ""
    except Exception as e:  # network errors etc.
        return 0, "", f"{type(e).__name__}: {e}"


def extract_page(html, url):
    """Return (text for checking, human page name). Headings are tagged [H1]..[H6]."""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "template", "svg"]):
        t.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    meta = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    meta_desc = (meta.get("content") or "").strip() if meta else ""
    alts = [i.get("alt").strip() for i in soup.find_all("img") if i.get("alt", "").strip()]
    body = soup.body or soup
    h1 = ""
    for h in body.find_all(re.compile(r"^h[1-6]$")):
        txt = h.get_text(" ", strip=True)
        if not txt:
            continue
        if h.name == "h1" and not h1:
            h1 = txt
        h.clear()
        h.append(NavigableString(f"[{h.name.upper()}] {txt}"))
    text = body.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    out = [f"URL: {url}", f"TITLE: {title}", f"META_DESCRIPTION: {meta_desc}",
           "--- BODY ---", text]
    if alts:
        out += ["--- IMAGE ALT TEXTS ---"] + alts
    path = urlparse(url).path.strip("/").split("/")[-1].replace("-", " ").replace("_", " ")
    name = h1 or title or path.title() or "Home"
    return "\n".join(out), name


def get_page(url, cfg):
    """Fetch + extract one page. Falls back to a JS-rendered fetch for empty app shells."""
    status, html, err = fetch(url, cfg)
    res = {"status": status, "html": html, "error": err, "text": "", "name": "", "warning": ""}
    if status == 200 and html:
        res["text"], res["name"] = extract_page(html, url)
        if not cfg["render_js"] and len(res["text"]) < 450 and html.lower().count("<script") >= 3:
            try:
                s2, h2 = fetch_js(url, cfg["timeout_seconds"])
                if s2 == 200 and h2:
                    res["html"] = h2
                    res["text"], res["name"] = extract_page(h2, url)
            except Exception:
                res["warning"] = ("page looks JavaScript-rendered and may be incomplete; "
                                  "set render_js to true and install playwright")
    return res


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
    path = re.sub(r"/index\.(html?|php)$", "/", p.path or "/", flags=re.I)  # /index.html == /
    path = path or "/"
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
    """Find EVERY page: follow links from the home page AND merge in the sitemap.

    Using both means pages missing from the sitemap, and pages only reachable by link,
    are all included. Returns (urls, number_dropped_by_max_pages).
    """
    start = norm_url(cfg["url"], cfg)
    if not start:
        die("Invalid website link.")
    robots = load_robots(start, cfg)

    crawled = []
    queue, seen = deque([(start, 0)]), {start}
    while queue:
        url, depth = queue.popleft()
        if not allowed_url(url, start, cfg, robots):
            continue
        crawled.append(url)
        if len(crawled) >= cfg["max_pages"] * 2:  # hard stop for runaway sites
            break
        status, html, _ = fetch(url, cfg)
        time.sleep(cfg["delay_seconds"])
        if status == 200 and html and depth < cfg["max_depth"]:
            for link in extract_links(html, url):
                nu = norm_url(link, cfg)
                if nu and nu not in seen:
                    seen.add(nu)
                    queue.append((nu, depth + 1))

    from_sitemap = []
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
                from_sitemap.append(nu)

    ordered, seen_o = [], set()
    for u in [start] + crawled + from_sitemap:
        if u not in seen_o:
            seen_o.add(u)
            ordered.append(u)
    dropped = max(0, len(ordered) - cfg["max_pages"])
    return ordered[: cfg["max_pages"]], dropped


# -------------------------------------------------------------- commands
def cmd_setup(args):
    cfg = {}
    if os.path.exists(CONFIG_NAME):
        with open(CONFIG_NAME, encoding="utf-8") as f:
            cfg = json.load(f)
    if not cfg:
        cfg = {"document": "", "url": "", "ignore_terms": []}
    if args.url:
        u = args.url.strip()
        if not re.match(r"^https?://", u, re.I):
            local = re.match(r"^(localhost|\d{1,3}(\.\d{1,3}){3})(:\d+)?(/|$)", u, re.I)
            u = ("http://" if local else "https://") + u
        cfg["url"] = u
    if args.doc:
        cfg["document"] = args.doc.strip()
    if args.ignore:
        cfg["ignore_terms"] = [t.strip() for t in args.ignore.split(",") if t.strip()]
    with open(CONFIG_NAME, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    print(f"CONFIG_SAVED url={cfg.get('url')} document={cfg.get('document')}")


def new_state(cfg, urls, shash, text):
    return {
        "created": now(), "url": cfg["url"], "document": cfg["document"],
        "doc_hash": sha(text), "doc_source_hash": shash, "awaiting_doc": False,
        "run": 1, "mode": "initial", "batch_counter": 0, "open_batch": None,
        "run_seen": {}, "coverage_run": 0, "coverage": [],
        "pages": {u: {"status": "pending", "hash": None, "checked_run": 0, "name": ""}
                  for u in urls},
        "issues": {},
    }


def cmd_prepare(args, quiet=False):
    cfg = load_config({"url": getattr(args, "url", None), "document": getattr(args, "doc", None)})
    if os.path.exists(STATE_PATH) and not args.force:
        die("A previous run exists. Use /skillcrawl (re-check) or /skillcrawl --fresh.")
    if not cfg["url"]:
        die("No website link set.")
    changed, pending = load_document(cfg, None)
    with open(DOC_TXT, encoding="utf-8") as f:
        text = f.read()
    print("Finding every page on the website (this can take a minute)...", flush=True)
    urls, dropped = discover_urls(cfg)
    state = new_state(cfg, urls, source_hash(local_document(cfg)), text)
    state["awaiting_doc"] = pending
    save_state(state)
    print(f"DOC_CHARS={len(text)}")
    print(f"PAGES_FOUND={len(urls)}")
    print(f"BATCHES_EXPECTED={-(-len(urls) // cfg['batch_size'])}")
    if dropped:
        print(f"WARNING_PAGES_CAPPED={dropped} more pages exist than max_pages "
              f"({cfg['max_pages']}). Raise max_pages in {CONFIG_NAME} to check them all.")
    if pending:
        print_transcribe_request()


def pending_urls(state):
    return [u for u, p in state["pages"].items() if p["status"] == "pending"]


def cmd_doc_ready(_):
    state = load_state()
    with open(DOC_TXT, encoding="utf-8") as f:
        text = f.read()
    left = TRANSCRIBE_RE.findall(text)
    if left:
        die(f"{len(left)} document image(s) still not transcribed in {DOC_TXT}: "
            + ", ".join(left[:5]))
    write_doc_files(text)
    state["doc_hash"] = sha(text)
    state["awaiting_doc"] = False
    save_state(state)
    print("DOC_READY")


def cmd_next_batch(_):
    cfg = load_config()
    state = load_state()
    if state.get("awaiting_doc"):
        die("The document images have not been transcribed yet. Run: doc-ready after "
            "transcribing.")

    if state.get("open_batch"):  # resume an unsubmitted batch
        print_batch(state["open_batch"]["dir"], state)
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
        res = get_page(url, cfg)
        time.sleep(cfg["delay_seconds"])
        entry = {"url": url, "name": res["name"], "http_status": res["status"],
                 "error": res["error"], "file": None, "hash": None, "warning": res["warning"]}
        if res["status"] == 200 and res["text"]:
            fpath = os.path.join(bdir, f"page_{i}.txt")
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(res["text"])
            entry["file"] = fpath
            entry["hash"] = sha(res["text"])
        else:
            entry["error"] = res["error"] or f"HTTP {res['status']}"
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
    print(f"BATCH_DIR={bdir}")
    print(f"BATCH_ID={m['batch_id']}")
    print(f"PAGES_IN_BATCH={len(m['pages'])}")
    print(f"PENDING_TOTAL_INCLUDING_THIS_BATCH={len(pending_urls(state))}")
    print(f"IGNORE_TERMS={json.dumps(m['ignore_terms'])}")
    for p in m["pages"]:
        if p["file"]:
            print(f"PAGE file={p['file']} url={p['url']}")
            if p.get("warning"):
                print(f"PAGE_WARNING url={p['url']} {p['warning']}")
        else:
            print(f"PAGE_ERROR url={p['url']} error={p['error']}")
    print(f"WRITE_ISSUES_TO={os.path.join(bdir, 'issues.json')}")


def make_issue_id(url, itype, found):
    return hashlib.sha1(f"{url}|{itype}|{norm(found).lower()}".encode()).hexdigest()[:8]


def find_section(raw_text, found):
    """Name of the heading / area of the page that contains `found`."""
    if not found:
        return ""
    ranges, off = [], 0
    for ln in raw_text.split("\n"):
        n = norm(ln)
        if not n:
            continue
        ranges.append((off, n))
        off += len(n) + 1
    joined = " ".join(n for _, n in ranges)
    idx = joined.find(norm(found))
    if idx < 0:
        return ""
    sec = ""
    for o, n in ranges:
        if o > idx:
            break
        m = re.match(r"\[H[1-6]\] (.*)", n)
        if m:
            sec = m.group(1)
        elif n.startswith("TITLE:"):
            sec = "Page title (browser tab)"
        elif n.startswith("META_DESCRIPTION:"):
            sec = "Meta description"
        elif n == "--- BODY ---":
            sec = "Top of page"
        elif n == "--- IMAGE ALT TEXTS ---":
            sec = "Image alt text"
    return sec


CSV_COLS = ["issue_id", "status", "severity", "type", "page_name", "page_url", "section",
            "found_text", "suggestion", "source_reference", "explanation", "first_seen_run",
            "assignee", "dev_status", "dev_notes"]
SEV_ORDER = {"high": 0, "medium": 1, "low": 2}


def write_csv(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: opens cleanly in Excel
        w = csv.DictWriter(f, fieldnames=CSV_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def read_dev_columns(path):
    """Keep what developers typed (assignee / status / notes) across re-runs."""
    keep = {}
    if os.path.exists(path):
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    if r.get("issue_id"):
                        keep[r["issue_id"]] = {k: r.get(k, "") for k in
                                               ("assignee", "dev_status", "dev_notes")}
        except Exception:
            pass
    return keep


def issue_row(iid, it, label, keep=None):
    dev = (keep or {}).get(iid, {})
    return {"issue_id": iid, "status": label, "severity": it.get("severity", "medium"),
            "type": it["type"], "page_name": it.get("page_name", ""), "page_url": it["page_url"],
            "section": it.get("section", ""), "found_text": it.get("found_text", ""),
            "suggestion": it.get("suggestion", ""),
            "source_reference": it.get("source_reference", ""),
            "explanation": it.get("explanation", ""), "first_seen_run": it.get("first_seen_run", ""),
            "assignee": dev.get("assignee", ""), "dev_status": dev.get("dev_status", ""),
            "dev_notes": dev.get("dev_notes", "")}


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

    page_raw, page_text, page_name = {}, {}, {}
    for p in manifest["pages"]:
        page_name[p["url"]] = p.get("name", "")
        if p["file"]:
            with open(p["file"], encoding="utf-8") as f:
                page_raw[p["url"]] = f.read()
            page_text[p["url"]] = norm(page_raw[p["url"]])
    run = state["run"]
    ignore = {t.lower() for t in cfg["ignore_terms"]}
    accepted, dropped = [], []

    # automatic issues for pages that could not be fetched
    for p in manifest["pages"]:
        if not p["file"]:
            accepted.append({"page_url": p["url"], "page_name": p.get("name") or "Broken link: " + (urlparse(p["url"]).path or "/"),
                             "section": "Whole page", "type": "broken_page", "severity": "high",
                             "found_text": f"HTTP {p['http_status']}",
                             "suggestion": "This page does not load. Fix the page or remove the "
                                           "link that points to it.",
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
        section = find_section(page_raw[url], found) or it.get("section", "") or ""
        accepted.append({"page_url": url, "page_name": page_name.get(url, ""), "section": section,
                         "type": itype, "severity": sev, "found_text": found,
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
            label = "new"
        else:
            label = "regressed" if existing["status"] == "fixed" else "still_open"
            it["first_seen_run"] = run if label == "regressed" else existing.get("first_seen_run", run)
        it["status"] = "open"
        it["last_seen_run"] = run
        state["issues"][iid] = it
        state["run_seen"][iid] = label
        rows.append(issue_row(iid, it, label))

    for p in manifest["pages"]:
        pg = state["pages"].setdefault(p["url"], {})
        pg["status"] = "done"
        pg["hash"] = p["hash"]
        pg["name"] = p.get("name", "") or pg.get("name", "")
        pg["checked_run"] = run
    state["open_batch"] = None
    save_state(state)

    write_csv(os.path.join(cfg["report_dir"], "batches", manifest["batch_id"] + ".csv"), rows)
    print(f"SUBMITTED {manifest['batch_id']}: {len(rows)} issues recorded "
          f"({sum(1 for r in rows if r['status'] == 'new')} new, "
          f"{sum(1 for r in rows if r['status'] == 'regressed')} reopened)")
    for url, why in dropped:
        print(f"DROPPED_ISSUE {url}: {why}")
    print(f"PENDING_PAGES={len(pending_urls(state))}")


def cmd_pages(_):
    state = load_state()
    run = state["run"]
    n = 0
    for u, p in state["pages"].items():
        if p["status"] == "done" or (p["status"] == "pending" and p.get("name")):
            print(f"{p.get('name') or '(no name)'} | {u}")
            n += 1
    print(f"PAGES_LISTED={n}  (doc-vs-website coverage: write {COVERAGE_PATH})")


def cmd_coverage_submit(_):
    state = load_state()
    if not os.path.exists(COVERAGE_PATH):
        die(f"{COVERAGE_PATH} not found. Write it (use [] if the document has no page list).")
    with open(COVERAGE_PATH, encoding="utf-8") as f:
        cov = json.load(f)
    run = state["run"]
    known = set(state["pages"])
    missing = 0
    for c in cov:
        c["url"] = (norm_url(c["url"], {"strip_query": True}) or "") if c.get("url") else ""
        if c["url"] and c["url"] not in known:
            c["url"] = ""  # claimed a page we never crawled -> treat as not found
        if c["url"]:
            continue
        name = c.get("doc_page", "").strip()
        if not name:
            continue
        it = {"page_url": MISSING_PAGE_URL, "page_name": name, "section": "",
              "type": "missing_page", "severity": "high", "found_text": "",
              "suggestion": f"Create / publish the page \"{name}\" - it is in the document but "
                            f"was not found anywhere on the website.",
              "source_reference": c.get("note", "") or name,
              "explanation": "Document page with no matching page on the website.",
              "first_seen_run": run, "status": "open", "last_seen_run": run}
        iid = make_issue_id(MISSING_PAGE_URL, "missing_page", name)
        existing = state["issues"].get(iid)
        label = "new" if existing is None else (
            "regressed" if existing["status"] == "fixed" else "still_open")
        if existing is not None and label == "still_open":
            it["first_seen_run"] = existing.get("first_seen_run", run)
        state["issues"][iid] = it
        state["run_seen"][iid] = label
        missing += 1
    state["coverage"] = cov
    state["coverage_run"] = run
    save_state(state)
    print(f"COVERAGE_SAVED document_pages={len(cov)} missing_on_website={missing}")


# ---------------------------------------------------------------- reports
def build_html(title, meta_lines, groups, fixed, pages_table, extra_pages, all_clear):
    e = htmllib.escape
    css = ("body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:0;background:#f4f5f7;"
           "color:#1d2433}main{max-width:1000px;margin:0 auto;padding:24px 16px 60px}"
           "h1{margin:0 0 4px}h2{margin:32px 0 8px}.meta{color:#5b6475;font-size:14px}"
           ".card{background:#fff;border:1px solid #dfe3ea;border-radius:10px;margin:14px 0;"
           "padding:16px}.card h3{margin:0}.url{font-size:13px;color:#5b6475;word-break:break-all}"
           "table{width:100%;border-collapse:collapse;margin-top:10px;font-size:14px}"
           "th,td{text-align:left;vertical-align:top;padding:8px;border-top:1px solid #e8ebf0}"
           "th{font-size:12px;text-transform:uppercase;color:#5b6475}"
           ".b{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;font-weight:600}"
           ".high{background:#fde2e2;color:#a31515}.medium{background:#fff0cc;color:#8a5a00}"
           ".low{background:#e4ecff;color:#1f4fb0}.new{background:#e1f5e5;color:#1b6b34}"
           ".still_open{background:#eee;color:#444}.regressed{background:#fde2e2;color:#a31515}"
           ".bad{background:#fff3f3;border-color:#f0b9b9}.ok{background:#effaf1;border-color:#b7e1c1}"
           "del{background:#fde2e2}ins{background:#dff5e3;text-decoration:none;font-weight:600}"
           ".sec{font-weight:600}small{color:#5b6475}")
    h = [f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' "
         f"content='width=device-width,initial-scale=1'><title>{e(title)}</title>"
         f"<style>{css}</style></head><body><main>",
         f"<h1>{e(title)}</h1>"]
    for m in meta_lines:
        h.append(f"<div class='meta'>{e(m)}</div>")
    if all_clear:
        h.append("<div class='card ok'><h3>All clear - no open issues. Nothing for developers "
                 "to fix.</h3></div>")
    else:
        h.append("<h2>What developers need to fix</h2>")
        h.append("<div class='meta'>Grouped by website page. For each row: go to the page, find "
                 "the section, and change the text as shown.</div>")
    for g in groups:
        h.append(f"<div class='card bad'><h3>Page: {e(g['name'])}</h3>"
                 f"<div class='url'>{e(g['url'])}</div><table><tr><th>#</th><th>Section on page"
                 f"</th><th>Currently says</th><th>Change it to / action</th><th>Type</th>"
                 f"<th>Priority</th><th>Status</th></tr>")
        for i, r in enumerate(g["rows"], 1):
            cur = e(r["found_text"]) if r["found_text"] else "<small>(missing)</small>"
            ref = (f"<br><small>Document: {e(r['source_reference'])}</small>"
                   if r["source_reference"] else "")
            why = f"<br><small>{e(r['explanation'])}</small>" if r["explanation"] else ""
            h.append(f"<tr><td>{i}</td><td class='sec'>{e(r['section'] or '-')}</td>"
                     f"<td><del>{cur}</del></td><td><ins>{e(r['suggestion'])}</ins>{ref}{why}</td>"
                     f"<td>{e(TYPE_LABEL.get(r['type'], r['type']))}</td>"
                     f"<td><span class='b {r['severity']}'>{e(r['severity'])}</span></td>"
                     f"<td><span class='b {r['raw_status']}'>{e(r['status'])}</span>"
                     f"<br><small>ID {e(r['issue_id'])}</small></td></tr>")
        h.append("</table></div>")
    if fixed:
        h.append(f"<h2>Fixed since last run ({len(fixed)})</h2><div class='card ok'><table>"
                 "<tr><th>Page</th><th>Section</th><th>Was</th></tr>")
        for r in fixed:
            h.append(f"<tr><td>{e(r['page_name'])}</td><td>{e(r['section'] or '-')}</td>"
                     f"<td>{e(r['found_text'] or r['suggestion'])}</td></tr>")
        h.append("</table></div>")
    h.append(f"<h2>Pages checked ({len(pages_table)})</h2><div class='card'><table><tr>"
             "<th>Page</th><th>URL</th><th>Open issues</th></tr>")
    for name, url, n in pages_table:
        badge = f"<span class='b high'>{n}</span>" if n else "OK"
        h.append(f"<tr><td>{e(name)}</td><td class='url'>{e(url)}</td>"
                 f"<td>{badge}</td></tr>")
    h.append("</table></div>")
    if extra_pages:
        h.append("<h2>Website pages not mentioned in the document (for information)</h2>"
                 "<div class='card'><ul>")
        for name, url in extra_pages:
            h.append(f"<li>{e(name)} - <span class='url'>{e(url)}</span></li>")
        h.append("</ul></div>")
    h.append("</main></body></html>")
    return "\n".join(h)


def build_md(title, meta_lines, groups, fixed, all_clear):
    L = [f"# {title}", ""] + [f"_{m}_  " for m in meta_lines] + [""]
    if all_clear:
        L.append("**ALL CLEAR - no open issues.**")
    for g in groups:
        L += [f"## Page: {g['name']}", f"{g['url']}", ""]
        for i, r in enumerate(g["rows"], 1):
            L.append(f"{i}. **Section:** {r['section'] or '-'} | **{TYPE_LABEL.get(r['type'], r['type'])}**"
                     f" ({r['severity']}) | {r['status']} | ID {r['issue_id']}")
            if r["found_text"]:
                L.append(f"   - Currently says: \"{r['found_text']}\"")
            L.append(f"   - Change to / action: {r['suggestion']}")
            if r["source_reference"]:
                L.append(f"   - Document: {r['source_reference']}")
            if r["explanation"]:
                L.append(f"   - Why: {r['explanation']}")
        L.append("")
    if fixed:
        L += [f"## Fixed since last run ({len(fixed)})"]
        L += [f"- {r['page_name']} / {r['section'] or '-'}: {r['found_text'] or r['suggestion']}"
              for r in fixed]
    return "\n".join(L)


def cmd_finalize(_):
    cfg = load_config()
    state = load_state()
    run = state["run"]
    if state.get("open_batch"):
        die("There is an unsubmitted batch. Submit it first.")
    pend = pending_urls(state)
    if pend:
        die(f"{len(pend)} pages still pending. Keep running next-batch.")
    if state.get("coverage_run") != run:
        print("WARNING_COVERAGE_NOT_DONE: run `pages`, write coverage.json, then "
              "`coverage-submit` so missing document pages are reported.")

    fixed_ids = []
    for iid, it in state["issues"].items():
        if it["status"] != "open" or iid in state["run_seen"]:
            continue
        if it["type"] == "missing_page":
            if state.get("coverage_run") != run:
                continue  # coverage not re-evaluated this run -> leave as is
        else:
            pg = state["pages"].get(it["page_url"], {})
            if pg.get("checked_run") != run:
                continue
        it["status"] = "fixed"
        it["fixed_run"] = run
        fixed_ids.append(iid)
    save_state(state)

    rdir = cfg["report_dir"]
    keep = read_dev_columns(os.path.join(rdir, "FIX_REPORT.csv"))
    rows = []
    for iid, it in state["issues"].items():
        if it["status"] == "open":
            label = state["run_seen"].get(iid, "still_open")
            r = issue_row(iid, it, STATUS_LABEL[label], keep)
            r["raw_status"] = label
            rows.append(r)
    counts = {k: sum(1 for r in rows if r["raw_status"] == k)
              for k in ("new", "still_open", "regressed")}
    fixed_rows = [issue_row(i, state["issues"][i], "FIXED") for i in fixed_ids]

    groups = {}
    for r in rows:
        g = groups.setdefault(r["page_url"], {"name": r["page_name"] or r["page_url"],
                                              "url": r["page_url"], "rows": []})
        g["rows"].append(r)
    glist = sorted(groups.values(),
                   key=lambda g: (min(SEV_ORDER.get(r["severity"], 1) for r in g["rows"]), g["name"]))
    for g in glist:
        g["rows"].sort(key=lambda r: (SEV_ORDER.get(r["severity"], 1), r["section"]))
    rows = [r for g in glist for r in g["rows"]]

    open_by_page = {}
    for r in rows:
        open_by_page[r["page_url"]] = open_by_page.get(r["page_url"], 0) + 1
    pages_table = [(p.get("name") or u, u, open_by_page.get(u, 0))
                   for u, p in state["pages"].items() if p["status"] == "done"]
    covered = {c.get("url") for c in state.get("coverage", []) if c.get("url")}
    extra_pages = ([(p.get("name") or u, u) for u, p in state["pages"].items()
                    if p["status"] == "done" and u not in covered]
                   if state.get("coverage_run") == run and state.get("coverage") else [])

    pages_checked = sum(1 for p in state["pages"].values() if p.get("checked_run") == run)
    title = f"SkillCrawl fix report - run {run} ({'first check' if run == 1 else 're-check'})"
    meta = [f"Website: {state['url']}", f"Document: {state['document']}", f"Generated: {now()}",
            f"Pages on website: {len(state['pages'])} | read this run: {pages_checked}",
            f"Open issues: {len(rows)} (new {counts['new']}, still open {counts['still_open']}, "
            f"reopened {counts['regressed']}) | fixed since last run: {len(fixed_ids)}"]
    all_clear = not rows

    html_doc = build_html(title, meta, glist, fixed_rows, pages_table, extra_pages, all_clear)
    md_doc = build_md(title, meta, glist, fixed_rows, all_clear)
    hist = os.path.join(rdir, "history", f"run{run:02d}")
    for d in (rdir, hist):
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "FIX_REPORT.html"), "w", encoding="utf-8") as f:
            f.write(html_doc)
        with open(os.path.join(d, "FIX_REPORT.md"), "w", encoding="utf-8") as f:
            f.write(md_doc)
        write_csv(os.path.join(d, "FIX_REPORT.csv"), rows)

    line = (f"SkillCrawl run {run}: ALL CLEAR ({len(fixed_ids)} fixed)" if all_clear else
            f"SkillCrawl run {run}: {len(rows)} open issues ({counts['new']} new, "
            f"{counts['still_open']} still open, {counts['regressed']} reopened), "
            f"{len(fixed_ids)} fixed. Report: {os.path.join(rdir, 'FIX_REPORT.html')}")
    if cfg["notify_webhook"]:
        try:
            requests.post(cfg["notify_webhook"], json={"text": line}, timeout=15)
        except Exception as ex:
            print(f"(webhook failed: {ex})")
    print("ALL_CLEAR" if all_clear else f"OPEN_ISSUES={len(rows)}")
    print(f"PAGES_READ={pages_checked} PAGES_ON_SITE={len(state['pages'])}")
    print(f"NEW={counts['new']} STILL_OPEN={counts['still_open']} REOPENED={counts['regressed']} "
          f"FIXED={len(fixed_ids)}")
    print(line)
    print(f"REPORT_HTML={os.path.join(rdir, 'FIX_REPORT.html')}")
    print(f"REPORT_CSV={os.path.join(rdir, 'FIX_REPORT.csv')}")


def start_recheck(cfg, state):
    """Prepare a re-check run. Returns False if the document needs transcription first."""
    changed, pending = load_document(cfg, state)
    if changed:
        state["doc_source_hash"] = source_hash(local_document(cfg))
        state["force_all"] = True
    if pending:
        state["awaiting_doc"] = True
        save_state(state)
        print_transcribe_request()
        return False
    with open(DOC_TXT, encoding="utf-8") as f:
        text = f.read()
    doc_changed = state.pop("force_all", False) or sha(text) != state.get("doc_hash")
    state["doc_hash"] = sha(text)

    state["run"] += 1
    run = state["run"]
    state["mode"] = "recheck"
    state["run_seen"] = {}
    state["batch_counter"] = 0

    urls, dropped = discover_urls(cfg)
    discovered = set(urls)
    for u in urls:
        state["pages"].setdefault(u, {"status": "pending", "hash": None, "checked_run": 0,
                                      "name": ""})

    open_pages = {it["page_url"] for it in state["issues"].values() if it["status"] == "open"}
    n_pending = n_skipped = n_gone = 0
    for url, pg in state["pages"].items():
        if pg["status"] == "pending":
            n_pending += 1
            continue
        res = get_page(url, cfg)
        time.sleep(cfg["delay_seconds"])
        if res["status"] in (404, 410) and url not in discovered:
            # removed from the site AND nothing links to it any more -> closed
            pg["status"], pg["checked_run"] = "gone", run
            n_gone += 1
            continue
        new_hash = sha(res["text"]) if res["status"] == 200 and res["text"] else None
        changed_page = new_hash != pg.get("hash")
        if doc_changed or changed_page or url in open_pages or pg["status"] != "done":
            pg["status"] = "pending"
            n_pending += 1
        else:
            pg["checked_run"] = run  # unchanged and clean -> counts as checked
            n_skipped += 1
    save_state(state)
    print(f"RECHECK_RUN={run}")
    print(f"DOCUMENT_CHANGED={doc_changed}")
    print(f"PAGES_TO_CHECK={n_pending} UNCHANGED_SKIPPED={n_skipped} GONE={n_gone}")
    if dropped:
        print(f"WARNING_PAGES_CAPPED={dropped} more pages exist than max_pages.")
    return True


def cmd_auto(args):
    """One entry point for QA: decides first run / resume / re-check by itself."""
    if not os.path.exists(CONFIG_NAME):
        print("NEEDS_SETUP: ask the user for the website link and the document path, "
              "then run: setup --url <link> --doc <path>")
        return
    cfg = load_config()
    if not cfg["url"] or not cfg["document"]:
        print("NEEDS_SETUP: website link or document path missing in config.")
        return
    if args.fresh or not os.path.exists(STATE_PATH):
        print("MODE=FIRST_RUN")
        cmd_prepare(argparse.Namespace(url=None, doc=None, force=True))
        return
    state = load_state()
    if state.get("awaiting_doc"):
        print("MODE=NEEDS_DOCUMENT_TRANSCRIPTION")
        print_transcribe_request()
        return
    if state.get("open_batch") or pending_urls(state):
        print("MODE=RESUME")
        print(f"PAGES_PENDING={len(pending_urls(state))}")
        return
    print("MODE=RECHECK")
    start_recheck(cfg, state)


def cmd_status(_):
    state = load_state()
    by = {}
    for p in state["pages"].values():
        by[p["status"]] = by.get(p["status"], 0) + 1
    open_n = sum(1 for i in state["issues"].values() if i["status"] == "open")
    fixed_n = sum(1 for i in state["issues"].values() if i["status"] == "fixed")
    print(f"run={state['run']} mode={state['mode']} pages={by} open_issues={open_n} "
          f"fixed_issues={fixed_n} open_batch={'yes' if state.get('open_batch') else 'no'}")


def main():
    ap = argparse.ArgumentParser(description="SkillCrawl engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup")
    s.add_argument("--url")
    s.add_argument("--doc")
    s.add_argument("--ignore", help="comma-separated brand names / terms to never flag")
    s.set_defaults(fn=cmd_setup)
    a = sub.add_parser("auto")
    a.add_argument("--fresh", action="store_true")
    a.set_defaults(fn=cmd_auto)
    sub.add_parser("next-batch").set_defaults(fn=cmd_next_batch)
    s = sub.add_parser("submit")
    s.add_argument("batch_dir")
    s.set_defaults(fn=cmd_submit)
    sub.add_parser("doc-ready").set_defaults(fn=cmd_doc_ready)
    sub.add_parser("pages").set_defaults(fn=cmd_pages)
    sub.add_parser("coverage-submit").set_defaults(fn=cmd_coverage_submit)
    sub.add_parser("finalize").set_defaults(fn=cmd_finalize)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
