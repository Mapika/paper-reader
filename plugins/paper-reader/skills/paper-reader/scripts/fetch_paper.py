#!/usr/bin/env python3
"""Fetch a research paper: PDF, tex source (arXiv only), and a real BibTeX entry.

Layout produced under <root>/<slug>/ (default root: ~/papers):
    paper.pdf
    citation.bib          (or citation.MISSING, never fabricated)
    source/               (arXiv tex source, if available)
    meta.json             (canonical metadata + bib_trail)

Inputs accepted (auto-detected):
    - arXiv URL or bare ID  (e.g. https://arxiv.org/abs/1706.03762, 1706.03762, 1706.03762v5)
    - OpenReview URL        (e.g. https://openreview.net/forum?id=XYZ)
    - ACL Anthology URL     (e.g. https://aclanthology.org/2023.emnlp-main.123/)
    - DOI                   (e.g. 10.1145/3458817.3476163 or https://doi.org/...)
    - Direct PDF URL
    - Paper title

The script will NOT invent a BibTeX entry. If every authoritative bib source
fails it writes citation.MISSING with the full lookup trail. The skill body
explains how to surface that to the user.

Stdlib only, no pip install required.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from xml.etree import ElementTree as ET

USER_AGENT = "paper-reader-skill/0.1 (+claude-code)"
PAPERS_ROOT = Path.home() / "papers"
STOPWORDS = {
    "a", "an", "the", "of", "for", "on", "in", "with", "and", "to", "is", "are",
    "by", "via", "from", "as", "at", "into", "over", "under", "through", "without",
    "vs", "using",
}
ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")
ARXIV_OLD_RE = re.compile(r"([a-z\-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?")
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+")


# -----------------------------------------------------------------------------
# HTTP helpers
# -----------------------------------------------------------------------------

def _http_get(url: str, accept: str | None = None, timeout: int = 30, retries: int = 5) -> bytes:
    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        if accept:
            req.add_header("Accept", accept)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429 and attempt < retries - 1:
                # Semantic Scholar rate limit. Back off (3, 6, 12, 24s)
                time.sleep(3 * (2 ** attempt))
                continue
            raise
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(1 + attempt)
                continue
            raise
    raise last_err  # pragma: no cover


def bib_from_arxiv_api(m: dict) -> str:
    """Construct a BibTeX entry from the arXiv API metadata. This is the same
    operation arxiv.org performs when you click 'BibTeX' on the abstract page:
    structured fields straight from the API, no invented data. Marked clearly
    in the bib_trail so the source is transparent.
    """
    authors = " and ".join(m["authors"])
    first_lastname = re.sub(r"[^a-z]", "", m["authors"][0].split()[-1].lower()) if m.get("authors") else "anon"
    words = re.findall(r"[A-Za-z0-9]+", m["title"].lower())
    sig = next((w for w in words if w not in STOPWORDS), "paper")
    key = f"{first_lastname}{m['year']}{sig}"
    return (
        f"@misc{{{key},\n"
        f"  title         = {{{m['title']}}},\n"
        f"  author        = {{{authors}}},\n"
        f"  year          = {{{m['year']}}},\n"
        f"  eprint        = {{{m['arxiv_id']}}},\n"
        f"  archivePrefix = {{arXiv}},\n"
        f"  url           = {{https://arxiv.org/abs/{m['arxiv_id']}}}\n"
        f"}}\n"
    )


def _http_download(url: str, dest: Path, timeout: int = 60) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


# -----------------------------------------------------------------------------
# Input classification
# -----------------------------------------------------------------------------

def classify(s: str) -> tuple[str, str]:
    s = s.strip()
    low = s.lower()
    if "arxiv.org" in low:
        m = ARXIV_ID_RE.search(s) or ARXIV_OLD_RE.search(s)
        if m:
            return ("arxiv", m.group(0))
    if ARXIV_ID_RE.fullmatch(s) or ARXIV_OLD_RE.fullmatch(s):
        return ("arxiv", s)
    if "openreview.net" in low:
        params = urllib.parse.parse_qs(urllib.parse.urlparse(s).query)
        if "id" in params:
            return ("openreview", params["id"][0])
    if "aclanthology.org" in low:
        path = urllib.parse.urlparse(s).path.strip("/")
        for suffix in (".pdf", ".bib"):
            if path.endswith(suffix):
                path = path[: -len(suffix)]
        return ("acl", path)
    if "doi.org" in low:
        m = DOI_RE.search(s)
        if m:
            return ("doi", m.group(0))
    if DOI_RE.fullmatch(s):
        return ("doi", s)
    if low.startswith(("http://", "https://")) and ".pdf" in low:
        return ("pdf", s)
    return ("title", s)


# -----------------------------------------------------------------------------
# arXiv
# -----------------------------------------------------------------------------

ATOM_NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def arxiv_metadata(arxiv_id: str) -> dict:
    bare = re.sub(r"v\d+$", "", arxiv_id)
    data = _http_get(f"http://export.arxiv.org/api/query?id_list={bare}")
    root = ET.fromstring(data)
    entry = root.find("a:entry", ATOM_NS)
    if entry is None:
        raise RuntimeError(f"arXiv API returned no entry for {arxiv_id}")
    title = re.sub(r"\s+", " ", entry.find("a:title", ATOM_NS).text.strip())
    authors = [a.find("a:name", ATOM_NS).text.strip() for a in entry.findall("a:author", ATOM_NS)]
    published = entry.find("a:published", ATOM_NS).text  # e.g. 2017-06-12T17:57:34Z
    year = int(published[:4])
    doi_el = entry.find("arxiv:doi", ATOM_NS)
    doi = doi_el.text.strip() if doi_el is not None else None
    version = arxiv_id[len(bare):] or None
    return {
        "title": title, "authors": authors, "year": year,
        "doi": doi, "arxiv_id": bare, "version": version,
    }


def fetch_arxiv_files(arxiv_id: str, paper_dir: Path) -> dict:
    bare = re.sub(r"v\d+$", "", arxiv_id)
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    eprint_url = f"https://arxiv.org/e-print/{arxiv_id}"
    _http_download(pdf_url, paper_dir / "paper.pdf")
    src_dir = paper_dir / "source"
    src_dir.mkdir(exist_ok=True)
    tmp_path = Path(tempfile.mkstemp(suffix=".tar.gz")[1])
    try:
        _http_download(eprint_url, tmp_path)
        try:
            with tarfile.open(tmp_path, "r:*") as tf:
                tf.extractall(src_dir)
        except tarfile.ReadError:
            # Some e-prints are a single gzipped .tex file, not a tar
            try:
                content = gzip.decompress(tmp_path.read_bytes())
                (src_dir / "main.tex").write_bytes(content)
            except OSError:
                # Could be a raw .tex (very rare)
                (src_dir / "main.tex").write_bytes(tmp_path.read_bytes())
    except Exception as e:
        (paper_dir / "source.MISSING").write_text(
            f"e-print fetch failed: {e}\nurl: {eprint_url}\n"
        )
        try:
            src_dir.rmdir()
        except OSError:
            pass
    finally:
        tmp_path.unlink(missing_ok=True)
    return {"url": f"https://arxiv.org/abs/{bare}", "pdf_url": pdf_url}


# -----------------------------------------------------------------------------
# BibTeX lookups
# -----------------------------------------------------------------------------

def bib_from_semantic_scholar(paper_id: str) -> tuple[str, dict]:
    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/"
        f"{urllib.parse.quote(paper_id, safe=':')}"
        f"?fields=title,authors,year,venue,externalIds,citationStyles"
    )
    obj = json.loads(_http_get(url, accept="application/json"))
    bib = (obj.get("citationStyles") or {}).get("bibtex")
    if not bib:
        raise RuntimeError(f"Semantic Scholar returned no bibtex for {paper_id}")
    return bib, obj


def bib_from_crossref(doi: str) -> str:
    data = _http_get(
        f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='/')}/transform/application/x-bibtex",
        accept="application/x-bibtex",
    )
    return data.decode("utf-8")


def bib_from_acl(paper_id: str) -> str:
    return _http_get(f"https://aclanthology.org/{paper_id}.bib").decode("utf-8")


def _openalex_lookup(spec: str) -> dict:
    """spec: 'doi:<doi>' or 'arxiv:<id>' or raw title for search."""
    if spec.startswith("doi:"):
        url = f"https://api.openalex.org/works/doi:{urllib.parse.quote(spec[4:], safe='/')}"
        return json.loads(_http_get(url, accept="application/json"))
    if spec.startswith("arxiv:"):
        # OpenAlex doesn't expose arxiv lookup by id directly; filter via search
        url = (
            "https://api.openalex.org/works?filter=ids.openalex:!null,"
            f"primary_location.landing_page_url.search:{urllib.parse.quote(spec[6:])}"
            "&per-page=1"
        )
        obj = json.loads(_http_get(url, accept="application/json"))
        if obj.get("results"):
            return obj["results"][0]
        # Fallback: search by query (less precise)
        url = f"https://api.openalex.org/works?search=arxiv+{urllib.parse.quote(spec[6:])}&per-page=1"
        obj = json.loads(_http_get(url, accept="application/json"))
        if obj.get("results"):
            return obj["results"][0]
        raise RuntimeError(f"OpenAlex found no result for {spec}")
    # title search
    url = f"https://api.openalex.org/works?search={urllib.parse.quote(spec)}&per-page=1"
    obj = json.loads(_http_get(url, accept="application/json"))
    if not obj.get("results"):
        raise RuntimeError(f"OpenAlex found no result for {spec!r}")
    return obj["results"][0]


def bib_from_openalex(spec: str) -> tuple[str, dict]:
    """Construct a BibTeX entry from OpenAlex's structured metadata.
    OpenAlex is fully open, no API key needed, and indexes ~all of scholarly
    output. We construct rather than rely on a pre-formatted bib because
    OpenAlex's response is rich and stable.
    """
    w = _openalex_lookup(spec)
    title = w.get("title") or w.get("display_name") or ""
    authors = [a["author"]["display_name"] for a in (w.get("authorships") or []) if a.get("author")]
    year = w.get("publication_year") or 0
    doi = (w.get("doi") or "").replace("https://doi.org/", "")
    venue = ""
    pl = w.get("primary_location") or {}
    src = (pl.get("source") or {}) if isinstance(pl, dict) else {}
    venue = src.get("display_name") or w.get("host_venue", {}).get("display_name") or ""
    oa_pdf = ((w.get("best_oa_location") or {}).get("pdf_url")) or (pl.get("pdf_url") or "")
    first_lastname = re.sub(r"[^a-z]", "", (authors[0].split()[-1].lower() if authors else "anon")) or "anon"
    sig = next((w_ for w_ in re.findall(r"[A-Za-z0-9]+", title.lower()) if w_ not in STOPWORDS), "paper")
    key = f"{first_lastname}{year}{sig}"
    entry_type = "@inproceedings" if venue and any(k in venue.lower() for k in ("conference", "proceedings", "neurips", "icml", "iclr", "acl", "emnlp", "naacl", "cvpr", "iccv", "eccv", "aaai", "ijcai")) else "@article"
    lines = [f"{entry_type}{{{key},"]
    lines.append(f"  title         = {{{title}}},")
    if authors:
        lines.append(f"  author        = {{{' and '.join(authors)}}},")
    if year:
        lines.append(f"  year          = {{{year}}},")
    if venue:
        field = "booktitle" if entry_type == "@inproceedings" else "journal"
        lines.append(f"  {field}     = {{{venue}}},")
    if doi:
        lines.append(f"  doi           = {{{doi}}},")
    if oa_pdf:
        lines.append(f"  url           = {{{oa_pdf}}},")
    lines.append("}\n")
    bib = "\n".join(lines)
    # Stash useful extras on the dict for callers
    w["_oa_pdf_url"] = oa_pdf
    return bib, w


def bib_from_dblp(title: str) -> str:
    """DBLP search → top hit → fetch its .bib. CS-focused, very clean entries."""
    search = _http_get(
        f"https://dblp.org/search/publ/api?q={urllib.parse.quote(title)}&format=json&h=1",
        accept="application/json",
    )
    obj = json.loads(search)
    hits = (((obj.get("result") or {}).get("hits") or {}).get("hit")) or []
    if not hits:
        raise RuntimeError(f"DBLP found no hit for {title!r}")
    key = hits[0].get("info", {}).get("key")
    if not key:
        raise RuntimeError(f"DBLP hit had no key: {hits[0]}")
    return _http_get(f"https://dblp.org/rec/{key}.bib?param=1").decode("utf-8")


def pdf_url_from_unpaywall(doi: str) -> str | None:
    """Given a DOI, return a legally-open PDF URL if Unpaywall knows one."""
    url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi, safe='/')}?email=anonymous@paper-reader.local"
    try:
        obj = json.loads(_http_get(url, accept="application/json"))
    except Exception:
        return None
    loc = obj.get("best_oa_location") or {}
    return loc.get("url_for_pdf") or loc.get("url") or None


def search_semantic_scholar(title: str) -> dict:
    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/search"
        f"?query={urllib.parse.quote(title)}&limit=1"
        f"&fields=title,authors,year,externalIds,citationStyles"
    )
    obj = json.loads(_http_get(url, accept="application/json"))
    if not obj.get("data"):
        raise RuntimeError(f"Semantic Scholar found no paper matching {title!r}")
    return obj["data"][0]


# -----------------------------------------------------------------------------
# Slug + minimal bib parsing
# -----------------------------------------------------------------------------

def make_slug(first_author_lastname: str, year: int, title: str) -> str:
    name = re.sub(r"[^a-z]", "", first_author_lastname.lower()) or "paper"
    words = re.findall(r"[A-Za-z0-9]+", title.lower())
    sig = [w for w in words if w not in STOPWORDS][:4]
    if not sig:
        sig = words[:4]
    year_part = str(year) if year else "0000"
    return f"{name}{year_part}-{'-'.join(sig)}" if sig else f"{name}{year_part}"


def extract_bibkey(bib_text: str) -> str | None:
    m = re.search(r"@\w+\s*\{\s*([^,\s]+)", bib_text)
    return m.group(1) if m else None


def parse_bib_minimal(bib_text: str) -> dict:
    def field(name: str) -> str | None:
        m = re.search(
            rf"{name}\s*=\s*\{{((?:[^{{}}]|\{{[^{{}}]*\}})*)\}}",
            bib_text, re.IGNORECASE | re.DOTALL,
        )
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
        m = re.search(rf'{name}\s*=\s*"([^"]*)"', bib_text, re.IGNORECASE | re.DOTALL)
        return re.sub(r"\s+", " ", m.group(1)).strip() if m else None

    title = re.sub(r"[{}]", "", field("title") or "")
    authors_raw = field("author") or ""
    raw_list = [a.strip() for a in re.split(r"\s+and\s+", authors_raw) if a.strip()]
    authors = []
    for a in raw_list:
        if "," in a:
            last, first = [p.strip() for p in a.split(",", 1)]
            authors.append(f"{first} {last}")
        else:
            authors.append(a)
    year_str = field("year") or "0"
    m_year = re.search(r"\d{4}", year_str)
    year = int(m_year.group(0)) if m_year else 0
    return {"title": title, "authors": authors, "year": year}


# -----------------------------------------------------------------------------
# Per-source handlers
# -----------------------------------------------------------------------------

def handle_arxiv(ident: str, root: Path, meta: dict, trail: list[str]) -> tuple[Path, str | None, str]:
    m = arxiv_metadata(ident)
    meta.update(m)
    meta["url"] = f"https://arxiv.org/abs/{m['arxiv_id']}"
    first_lastname = m["authors"][0].split()[-1] if m["authors"] else "paper"
    slug = make_slug(first_lastname, m["year"], m["title"])
    paper_dir = root / slug
    paper_dir.mkdir(parents=True, exist_ok=True)
    meta.update(fetch_arxiv_files(ident, paper_dir))

    bib = None
    attempts: list[tuple[str, callable]] = []
    if m.get("doi"):
        attempts.append((f"OpenAlex doi:{m['doi']}", lambda: bib_from_openalex(f"doi:{m['doi']}")[0]))
        attempts.append((f"Crossref doi:{m['doi']}", lambda: bib_from_crossref(m["doi"])))
    attempts.append((f"OpenAlex title-search:{m['title'][:40]!r}", lambda: bib_from_openalex(m["title"])[0]))
    attempts.append((f"DBLP title-search:{m['title'][:40]!r}", lambda: bib_from_dblp(m["title"])))
    attempts.append((f"SS arXiv:{m['arxiv_id']}", lambda: bib_from_semantic_scholar(f"arXiv:{m['arxiv_id']}")[0]))
    # Final deterministic fallback: construct from arXiv API metadata
    attempts.append(("arXiv API (constructed)", lambda: bib_from_arxiv_api(m)))
    for label, fn in attempts:
        try:
            bib = fn()
            trail.append(f"{label}: OK")
            break
        except Exception as e:
            trail.append(f"{label}: {e}")
    return paper_dir, bib, slug


def handle_acl(ident: str, root: Path, meta: dict, trail: list[str]) -> tuple[Path, str | None, str]:
    bib = None
    m: dict | None = None
    # ACL's own .bib is authoritative, try it first
    try:
        bib = bib_from_acl(ident)
        trail.append(f"ACL {ident}.bib: OK")
        m = parse_bib_minimal(bib)
    except Exception as e:
        trail.append(f"ACL {ident}.bib: {e}")
    # OpenAlex fallback (open + generous)
    if not bib:
        try:
            bib, obj = bib_from_openalex(f"ACL anthology {ident}")
            trail.append(f"OpenAlex ACL:{ident}: OK")
            m = {"title": obj.get("title") or obj.get("display_name") or "", "authors": [a["author"]["display_name"] for a in (obj.get("authorships") or [])], "year": obj.get("publication_year") or 0}
        except Exception as e:
            trail.append(f"OpenAlex ACL:{ident}: {e}")
    if not bib:
        try:
            bib, obj = bib_from_semantic_scholar(f"ACL:{ident}")
            trail.append(f"SS ACL:{ident}: OK")
            m = {"title": obj["title"], "authors": [a["name"] for a in obj["authors"]], "year": obj["year"]}
        except Exception as e:
            trail.append(f"SS ACL:{ident}: {e}")
    if not m:
        year_guess = int(ident[:4]) if ident[:4].isdigit() else 0
        m = {"title": ident, "authors": ["unknown"], "year": year_guess}
    meta.update(m)
    meta["url"] = f"https://aclanthology.org/{ident}/"
    pdf_url = f"https://aclanthology.org/{ident}.pdf"
    meta["pdf_url"] = pdf_url
    first_lastname = m["authors"][0].split()[-1] if m["authors"] else "paper"
    slug = make_slug(first_lastname, m["year"], m["title"])
    paper_dir = root / slug
    paper_dir.mkdir(parents=True, exist_ok=True)
    _http_download(pdf_url, paper_dir / "paper.pdf")
    return paper_dir, bib, slug


def handle_openreview(ident: str, root: Path, meta: dict, trail: list[str]) -> tuple[Path, str | None, str]:
    pdf_url = f"https://openreview.net/pdf?id={ident}"
    bib = None
    m: dict | None = None
    for label, fn in [
        (f"OpenAlex openreview/{ident}", lambda: bib_from_openalex(f"openreview {ident}")),
        (f"SS openreview/{ident}", lambda: bib_from_semantic_scholar(f"URL:https://openreview.net/forum?id={ident}")),
    ]:
        try:
            bib, obj = fn()
            trail.append(f"{label}: OK")
            if "authorships" in obj:
                m = {"title": obj.get("title") or obj.get("display_name"), "authors": [a["author"]["display_name"] for a in obj.get("authorships") or []], "year": obj.get("publication_year") or 0}
            else:
                m = {"title": obj["title"], "authors": [a["name"] for a in obj["authors"]], "year": obj["year"]}
            break
        except Exception as e:
            trail.append(f"{label}: {e}")
    if not bib:
        try:
            bib = bib_from_dblp(f"openreview {ident}")
            trail.append(f"DBLP openreview/{ident}: OK")
            m = parse_bib_minimal(bib)
        except Exception as e:
            trail.append(f"DBLP openreview/{ident}: {e}")
    if not m:
        m = {"title": f"openreview-{ident}", "authors": ["unknown"], "year": 0}
    meta.update(m)
    meta["url"] = f"https://openreview.net/forum?id={ident}"
    meta["pdf_url"] = pdf_url
    first_lastname = m["authors"][0].split()[-1] if m["authors"] else "paper"
    slug = make_slug(first_lastname, m["year"], m["title"])
    paper_dir = root / slug
    paper_dir.mkdir(parents=True, exist_ok=True)
    _http_download(pdf_url, paper_dir / "paper.pdf")
    return paper_dir, bib, slug


def handle_doi(ident: str, root: Path, meta: dict, trail: list[str]) -> tuple[Path, str | None, str]:
    bib = None
    m: dict | None = None
    oa_pdf_url: str | None = None
    # Try OpenAlex first (gives both bib + OA PDF URL in one call)
    try:
        bib, obj = bib_from_openalex(f"doi:{ident}")
        trail.append(f"OpenAlex doi:{ident}: OK")
        m = {"title": obj.get("title") or obj.get("display_name") or "", "authors": [a["author"]["display_name"] for a in (obj.get("authorships") or [])], "year": obj.get("publication_year") or 0}
        oa_pdf_url = obj.get("_oa_pdf_url") or None
    except Exception as e:
        trail.append(f"OpenAlex doi:{ident}: {e}")
    if not bib:
        try:
            bib = bib_from_crossref(ident)
            trail.append(f"Crossref doi:{ident}: OK")
            m = parse_bib_minimal(bib)
        except Exception as e:
            trail.append(f"Crossref doi:{ident}: {e}")
    if not bib:
        try:
            bib, obj = bib_from_semantic_scholar(f"DOI:{ident}")
            trail.append(f"SS DOI:{ident}: OK")
            m = {"title": obj["title"], "authors": [a["name"] for a in obj["authors"]], "year": obj["year"]}
        except Exception as e:
            trail.append(f"SS DOI:{ident}: {e}")
    if not m:
        m = {"title": f"doi-{ident}", "authors": ["unknown"], "year": 0}
    meta.update(m)
    meta["doi"] = ident
    meta["url"] = f"https://doi.org/{ident}"
    first_lastname = m["authors"][0].split()[-1] if m["authors"] else "paper"
    slug = make_slug(first_lastname, m["year"], m["title"])
    paper_dir = root / slug
    paper_dir.mkdir(parents=True, exist_ok=True)
    # Try to find an open-access PDF (OpenAlex first, Unpaywall as backup)
    if not oa_pdf_url:
        oa_pdf_url = pdf_url_from_unpaywall(ident)
        if oa_pdf_url:
            trail.append(f"Unpaywall doi:{ident}: OA PDF found")
    if oa_pdf_url:
        try:
            _http_download(oa_pdf_url, paper_dir / "paper.pdf")
            meta["pdf_url"] = oa_pdf_url
            trail.append(f"PDF downloaded from OA location: OK")
        except Exception as e:
            trail.append(f"PDF download from {oa_pdf_url}: {e}")
    if not (paper_dir / "paper.pdf").exists():
        (paper_dir / "PDF.MISSING").write_text(
            f"DOI inputs don't yield a deterministic PDF URL and no OA copy was found.\n"
            f"Resolve via https://doi.org/{ident} and place paper.pdf manually.\n"
        )
    return paper_dir, bib, slug


def handle_pdf(ident: str, root: Path, meta: dict, trail: list[str]) -> tuple[Path, str | None, str]:
    bib = None
    try:
        bib, obj = bib_from_semantic_scholar(f"URL:{ident}")
        trail.append(f"SS URL:{ident}: OK")
        m = {"title": obj["title"], "authors": [a["name"] for a in obj["authors"]], "year": obj["year"]}
    except Exception as e:
        trail.append(f"SS URL:{ident}: {e}")
        m = {"title": ident.rsplit("/", 1)[-1].rsplit(".", 1)[0], "authors": ["unknown"], "year": 0}
    meta.update(m)
    meta["pdf_url"] = ident
    first_lastname = m["authors"][0].split()[-1] if m["authors"] else "paper"
    slug = make_slug(first_lastname, m["year"], m["title"])
    paper_dir = root / slug
    paper_dir.mkdir(parents=True, exist_ok=True)
    _http_download(ident, paper_dir / "paper.pdf")
    return paper_dir, bib, slug


def handle_title(ident: str, root: Path, meta: dict, trail: list[str]) -> tuple[Path, str | None, str]:
    # Try OpenAlex first. Open, generous, and includes OA PDF URLs
    bib: str | None = None
    m: dict | None = None
    oa_pdf_url: str | None = None
    arxiv_id: str | None = None
    doi: str | None = None
    try:
        bib, obj = bib_from_openalex(ident)
        trail.append(f"OpenAlex search:{ident[:40]!r}: OK")
        m = {"title": obj.get("title") or obj.get("display_name") or "", "authors": [a["author"]["display_name"] for a in (obj.get("authorships") or [])], "year": obj.get("publication_year") or 0}
        oa_pdf_url = obj.get("_oa_pdf_url") or None
        # Extract DOI + arXiv id if exposed
        for src_id in (obj.get("ids") or {}).values():
            if isinstance(src_id, str):
                if "arxiv.org/abs/" in src_id:
                    arxiv_id = src_id.rsplit("/", 1)[-1]
                if src_id.startswith("https://doi.org/"):
                    doi = src_id.replace("https://doi.org/", "")
    except Exception as e:
        trail.append(f"OpenAlex search:{ident[:40]!r}: {e}")
    if not bib:
        try:
            obj = search_semantic_scholar(ident)
            m = {"title": obj["title"], "authors": [a["name"] for a in obj["authors"]], "year": obj["year"]}
            ext = obj.get("externalIds") or {}
            meta.update({k.lower(): v for k, v in ext.items() if isinstance(v, str)})
            bib = (obj.get("citationStyles") or {}).get("bibtex")
            trail.append(f"SS search: {'OK' if bib else 'no citationStyles.bibtex'}")
            arxiv_id = arxiv_id or ext.get("ArXiv")
            doi = doi or ext.get("DOI")
        except Exception as e:
            trail.append(f"SS search: {e}")
    if not bib:
        try:
            bib = bib_from_dblp(ident)
            trail.append(f"DBLP search: OK")
            if not m:
                m = parse_bib_minimal(bib)
        except Exception as e:
            trail.append(f"DBLP search: {e}")
    if not m:
        m = {"title": ident, "authors": ["unknown"], "year": 0}
    meta.update(m)
    if doi:
        meta["doi"] = doi
    if arxiv_id:
        meta["arxiv_id"] = arxiv_id
    first_lastname = m["authors"][0].split()[-1] if m["authors"] else "paper"
    slug = make_slug(first_lastname, m["year"], m["title"])
    paper_dir = root / slug
    paper_dir.mkdir(parents=True, exist_ok=True)
    # PDF resolution priority: arXiv (has tex source too) > OpenAlex OA URL > Unpaywall
    if arxiv_id:
        meta.update(fetch_arxiv_files(arxiv_id, paper_dir))
    elif oa_pdf_url:
        try:
            _http_download(oa_pdf_url, paper_dir / "paper.pdf")
            meta["pdf_url"] = oa_pdf_url
            trail.append("PDF from OpenAlex OA location: OK")
        except Exception as e:
            trail.append(f"PDF from OpenAlex OA: {e}")
    elif doi:
        oa_pdf_url = pdf_url_from_unpaywall(doi)
        if oa_pdf_url:
            try:
                _http_download(oa_pdf_url, paper_dir / "paper.pdf")
                meta["pdf_url"] = oa_pdf_url
                trail.append("PDF from Unpaywall: OK")
            except Exception as e:
                trail.append(f"PDF from Unpaywall: {e}")
    if not (paper_dir / "paper.pdf").exists():
        (paper_dir / "PDF.MISSING").write_text(
            "Title resolved but no canonical or OA PDF URL was found.\n"
            f"Trail (so far):\n  - " + "\n  - ".join(trail) + "\n"
        )
    return paper_dir, bib, slug


HANDLERS = {
    "arxiv": handle_arxiv,
    "acl": handle_acl,
    "openreview": handle_openreview,
    "doi": handle_doi,
    "pdf": handle_pdf,
    "title": handle_title,
}


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch a research paper's PDF, tex source, and real BibTeX. Never invents citations."
    )
    parser.add_argument("input", help="arXiv URL/ID, OpenReview URL, ACL URL, DOI, PDF URL, or title")
    parser.add_argument("--root", default=str(PAPERS_ROOT), help="papers library root (default ~/papers)")
    args = parser.parse_args()

    root = Path(args.root).expanduser()
    root.mkdir(parents=True, exist_ok=True)

    kind, ident = classify(args.input)
    print(f"[paper-reader] kind={kind} id={ident}", file=sys.stderr)

    meta: dict = {"source_kind": kind, "input": args.input}
    trail: list[str] = []
    handler = HANDLERS[kind]
    paper_dir, bib_text, slug = handler(ident, root, meta, trail)

    if bib_text:
        (paper_dir / "citation.bib").write_text(bib_text.strip() + "\n")
        (paper_dir / "citation.MISSING").unlink(missing_ok=True)
        meta["bibkey"] = extract_bibkey(bib_text)
    else:
        (paper_dir / "citation.MISSING").write_text(
            "Bib lookup failed across all sources.\nTrail:\n  - "
            + "\n  - ".join(trail) + "\n"
        )
        (paper_dir / "citation.bib").unlink(missing_ok=True)
        meta["bibkey"] = None

    meta["slug"] = slug
    meta["bib_trail"] = trail
    (paper_dir / "meta.json").write_text(json.dumps(meta, indent=2, default=str) + "\n")

    print(str(paper_dir))


if __name__ == "__main__":
    main()
