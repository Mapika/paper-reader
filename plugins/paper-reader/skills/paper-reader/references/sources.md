# Source-specific notes

Per-source URL patterns, bib lookup chains, and gotchas. Most of this is encoded in `scripts/fetch_paper.py`; this file is what you read when the script fails on a particular source and you need to debug or do something by hand.

## Bib lookup chain (overview)

The fetcher tries authoritative and open sources before the rate-limited ones, in this rough order. Specific handlers reorder slightly:

1. **Publisher / venue native bib.** ACL Anthology's `<id>.bib`, Crossref BibTeX for DOIs, arXiv API metadata. These are ground truth for what they cover.
2. **OpenAlex** (`api.openalex.org`). Fully open, no API key required, generous rate limits, indexes about all of scholarly output. Returns rich JSON which the script formats into BibTeX. Also exposes `best_oa_location.pdf_url` so a single OpenAlex hit can resolve both bib AND PDF for paywalled DOIs.
3. **DBLP** (`dblp.org`). CS-specific. The cleanest BibTeX on the web for computer science papers; entries are hand-curated. Use this when the title-search hit on OpenAlex is ambiguous or you want a more compact `@inproceedings`-style entry.
4. **Semantic Scholar** (`api.semanticscholar.org`). Broad coverage, but heavily rate-limited (HTTP 429) without an API key. Kept in the chain as a fallback, not primary.
5. **arXiv API constructed** (arXiv handler only). Deterministic, always works when arXiv API is up. Marked `arXiv API (constructed)` in the trail.

PDF resolution chain (when no canonical PDF URL exists):

1. arXiv: `https://arxiv.org/pdf/<id>.pdf` (always works)
2. ACL: `https://aclanthology.org/<id>.pdf` (always works)
3. OpenReview: `https://openreview.net/pdf?id=<id>` (works for accepted papers)
4. OpenAlex `best_oa_location.pdf_url`. For DOI / title inputs, OpenAlex often knows where the OA copy lives.
5. **Unpaywall** (`api.unpaywall.org`). DOI-keyed lookup for the best legally-OA copy. Free, requires only a contact email in the URL.

If all of these fail for a non-arXiv input, the fetcher writes `PDF.MISSING` and the user must place `paper.pdf` manually (institutional access, etc.).

## arXiv

**ID forms**

- New style: `1706.03762`, optionally with version like `1706.03762v5`.
- Old style: `cs/0612065`, `math.GT/0612065`.

**URLs**

- Abstract page: `https://arxiv.org/abs/<id>`
- PDF: `https://arxiv.org/pdf/<id>.pdf` (also `https://arxiv.org/pdf/<id>v<n>.pdf` for a specific version)
- TeX source (e-print): `https://arxiv.org/e-print/<id>`. Returns either a `.tar.gz` of the source tree or a single gzipped `.tex`. The fetcher tries both.
- Metadata (Atom XML): `http://export.arxiv.org/api/query?id_list=<id>`. Gives title, authors, year, abstract, optional DOI.

**Bib lookup order**

1. Semantic Scholar Graph API: `https://api.semanticscholar.org/graph/v1/paper/arXiv:<id>?fields=…,citationStyles`. Returns a proper BibTeX entry under `citationStyles.bibtex`, with sane author splitting and venue. Rate-limited without an API key; the fetcher retries on 429 with exponential backoff up to about 45s.
2. Crossref `…/transform/application/x-bibtex`. Only works if the arXiv metadata exposes a DOI (newer papers often do, older usually don't).
3. **arXiv API (constructed).** Final fallback. The fetcher reads the same structured fields (title, authors, year, eprint) that arxiv.org's own "BibTeX" export uses, and emits an `@misc{…, archivePrefix={arXiv}, eprint={<id>}}` entry. This is **not** fabrication: every field comes straight from the arXiv API, which is the canonical source for the preprint. The bib_trail records this with the label `arXiv API (constructed): OK` so the source is transparent. When you see this label, the bib is real but represents the *preprint* (no published-venue info). If the paper has a published version with extra metadata (DOI, venue, pages), you'll want to re-resolve through Crossref or by DOI once that's known.

**Versioning**

- If the user gives a versioned ID (`1706.03762v5`), preserve it for the PDF / e-print download (so they get exactly that version) and strip it for API queries (the arXiv API expects bare IDs).
- The version of `paper.pdf` on disk reflects the URL the user supplied. Re-downloading the same paper at a different version produces a different slug if you're not careful. Usually slug stays the same because slug uses title+author+year. Add a `version` field to meta.json to record what was fetched.

**Tex source gotchas**

- Most papers ship a single `main.tex` plus figures and bib files. Some ship many `.tex` files; find the one with `\documentclass` to identify the root.
- A handful of papers withdraw their source; the e-print URL returns 404. Not a hard error. Record in `source.MISSING` and continue with the PDF.
- Source may be encoded weirdly (LaTeX with non-UTF-8). Don't try to parse it; grep it.

## OpenReview (NeurIPS, ICLR, EMNLP review track, etc.)

**URLs**

- Forum: `https://openreview.net/forum?id=<id>`
- PDF: `https://openreview.net/pdf?id=<id>`
- Supplementary: not at a deterministic URL; visible on the forum page.

**Bib lookup**

- OpenReview's own API requires authentication and is finicky. Use Semantic Scholar instead: `https://api.semanticscholar.org/graph/v1/paper/URL:https://openreview.net/forum?id=<id>?fields=…,citationStyles`.
- If Semantic Scholar doesn't have it (very recent papers under review), you may need to construct the bib from DBLP later, but **don't synthesize one from your own knowledge**. Write `citation.MISSING` and tell the user.

**Gotchas**

- Same paper often has both an arXiv version and an OpenReview version with different revision histories. The conference version is usually more polished; the arXiv version may have extra appendices. Prefer the version the user named, and note in `meta.json` which one you fetched.

## ACL Anthology (ACL, EMNLP, NAACL, COLING, etc.)

**URLs**

- Paper page: `https://aclanthology.org/<paperid>/` (e.g. `2023.emnlp-main.123/`)
- PDF: `https://aclanthology.org/<paperid>.pdf`
- Official bib: `https://aclanthology.org/<paperid>.bib`. **Authoritative**, use this first.

**Bib lookup order**

1. `<paperid>.bib` directly. This is the cleanest source of truth in the entire skill. ACL maintains these by hand.
2. Semantic Scholar by `ACL:<paperid>` as fallback.

**Gotchas**

- Paper IDs use the form `<year>.<venue>-<track>.<num>`, e.g. `2023.emnlp-main.123`. Year is the first four characters.
- Some older papers are at `https://aclanthology.org/P19-1234/` (pre-2020 scheme). The fetcher handles both via the same `<id>.pdf` / `<id>.bib` pattern.

## DOI

**Forms**

- Bare DOI: `10.1145/3458817.3476163`
- URL: `https://doi.org/10.1145/3458817.3476163`

**Bib lookup order**

1. Crossref content negotiation: `https://api.crossref.org/works/<doi>/transform/application/x-bibtex`. Returns a full BibTeX entry. This is the publisher-authoritative source.
2. Semantic Scholar `DOI:<doi>` as fallback for papers Crossref doesn't have (very rare).

**Gotchas**

- DOI does **not** give you a deterministic PDF URL. Resolving `https://doi.org/<doi>` lands on the publisher's page, behind a paywall or login wall in most cases. The fetcher writes `PDF.MISSING` so the user knows they need to grab the PDF manually (institutional access, sci-hub, etc., that's the user's call).
- Some preprint servers issue DOIs (bioRxiv, ChemRxiv, SSRN). Those usually do have downloadable PDFs but at non-standard URLs; you may need to follow the resolved page manually.

## Generic PDF URL

When the user pastes a PDF URL that isn't arXiv / OpenReview / ACL:

- Download the PDF directly.
- Look up bib by `URL:<url>` on Semantic Scholar. This works surprisingly often because Semantic Scholar indexes by source URL.
- If that fails, ask the user for the title. `kind=title` resolution is the next escape hatch.

## Title-only

When the user gives only a title:

- Semantic Scholar paper search: `…/paper/search?query=<title>&limit=1&fields=…,citationStyles`.
- If a result comes back, it usually carries `externalIds.ArXiv`. If so, fetch the arXiv PDF + e-print. Otherwise write `PDF.MISSING`.
- For ambiguous titles (multiple papers, common words), the first hit may be wrong. If you're unsure, show the user what was matched and ask before proceeding.

## OpenAlex

**API**: `https://api.openalex.org/works/...`. No authentication needed for normal use. The "polite pool" gets better rate limits if you supply `?mailto=<email>`; the fetcher could be extended to do this but the default pool is fine for human-scale usage.

**Key endpoints**:
- By DOI: `https://api.openalex.org/works/doi:<doi>` (note the `doi:` prefix; the script uses this directly).
- By OpenAlex ID: `https://api.openalex.org/works/W<num>`.
- Title search: `https://api.openalex.org/works?search=<title>&per-page=1`.
- Filter by venue / source / year / OA status, see https://docs.openalex.org/api-entities/works/filter-works

**What you get** (relevant fields):
- `title`, `authorships[].author.display_name`, `publication_year`
- `doi` (as `https://doi.org/...` URL)
- `primary_location.source.display_name` (venue)
- `best_oa_location.pdf_url`. Direct link to the open-access PDF if one exists. This is the magic field; it often resolves Where Is The Paywall-Free Copy.
- `ids` (cross-IDs: openalex, doi, mag, pmid, etc.)

**Gotchas**:
- The OpenAlex entry type guess (`@article` vs `@inproceedings`) the script makes is keyword-based on venue name. If the venue field is unusual, the type may be wrong; users editing the bib by hand can override.
- For arXiv preprints, OpenAlex's venue is typically `arXiv (Cornell University)` and the type is `@article`. If you need a `@misc{eprint=...}` style instead, fall back to the arXiv-API-constructed entry.

## DBLP

**API**: `https://dblp.org/search/publ/api?q=<title>&format=json&h=<hits>` for search; `https://dblp.org/rec/<key>.bib` for the bibtex of a known DBLP key.

**Why CS people love DBLP**:
- Entries are hand-curated, deduplicated, with venue normalization (`ACL`, `EMNLP`, `NeurIPS` instead of "Proceedings of the 60th Annual Meeting…").
- Author names are canonical (handles the same author publishing as both "Y. Bengio" and "Yoshua Bengio").
- Multiple BibTeX formats: append `?param=0` for verbose, `?param=1` for condensed, `?param=2` for crossref-style.

**Gotchas**:
- Coverage is **CS only**. Querying for a biology paper returns no hits.
- Search is loose. For titles that aren't unique to a paper, you may get a top hit that's a different paper with similar words. The fetcher takes the top hit; for ambiguous cases, the user should verify.

## Unpaywall

**API**: `https://api.unpaywall.org/v2/<doi>?email=<contact>`. Free, requires a contact email in the URL (any non-empty value works; doesn't get spammed).

**What it returns**: A JSON record with `best_oa_location` describing the best free legal copy of the paper, if one exists. Fields: `url_for_pdf`, `url`, `host_type` (publisher / repository), `license`, `version` (publishedVersion / acceptedVersion / submittedVersion).

**When this fires**: DOI inputs to a paywalled paper where the author or institution has self-archived an OA copy. This is the difference between `PDF.MISSING` and a usable PDF for huge chunks of the literature.

**Gotchas**:
- Not every paper has an OA copy. Unpaywall tells you honestly when there isn't one (returns null `best_oa_location`).
- Some `url_for_pdf` links go to publisher pages that 30x-redirect; the fetcher's user-agent follows redirects.

## Authoritativeness ranking (when sources conflict)

If two sources give different bib entries (e.g., Semantic Scholar's BibTeX vs. Crossref's, or arXiv's title vs. the published version's title), prefer:

1. Publisher / venue official bib (ACL Anthology, Crossref via DOI registered by publisher)
2. Semantic Scholar (good, but lossy on edge cases)
3. arXiv API (only as a fallback because it omits venue and uses the preprint title)

The fetcher follows this implicitly via its lookup order. If the user notices a discrepancy, the trail in `meta.json["bib_trail"]` shows which source won.

## Rate limits

- **Semantic Scholar**: about 100 requests/5 min unauthenticated. The fetcher retries on 429 with exponential backoff (3 attempts). For batch usage, get an API key and add it as `x-api-key` header.
- **arXiv API**: courtesy limit about 3 req/sec. Not a concern for human-driven use.
- **Crossref**: very lenient, but include a User-Agent (the fetcher does).
- **ACL Anthology**: static files, no real limit.
