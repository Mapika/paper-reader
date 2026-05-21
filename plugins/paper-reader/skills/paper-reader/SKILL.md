---
name: paper-reader
description: Use whenever the user wants to read, summarize, discuss, cite, or pull a research paper. Any arXiv / OpenReview / ACL Anthology link, DOI, PDF URL, or a phrase like "read this paper", "pull this paper", "summarize", "what does X say", or "cite X". Always downloads the PDF (and the arXiv tex source when available), fetches a real BibTeX entry from an authoritative source via OpenAlex / Crossref / DBLP / ACL / Semantic Scholar (never fabricated), structures everything under ~/papers/, and enforces strict citation discipline. Every claim about the paper carries an inline locator with section or table/figure plus page number, and citations are never fabricated.
---

# paper-reader

Read research papers carefully and cite them honestly.

The job has two halves. First, fetch and structure the artifacts so the paper is available locally with a real bib entry. Second, talk about the paper with strict locator discipline so every claim is traceable and no citation is ever invented.

## When to use

Trigger on any of these signals. Don't wait for "use the paper-reader skill":

- An arXiv URL (`arxiv.org/abs/...`, `arxiv.org/pdf/...`), OpenReview URL (`openreview.net/...`), ACL Anthology URL (`aclanthology.org/...`), DOI, or direct PDF URL appears in the user's message.
- The user says "read", "summarize", "skim", "pull", "fetch", "look at", "what does X say", "what's in X", "cite X", "the X paper", "this paper".
- The user references a paper by title and wants commentary on it.
- The user asks you to use a result, method, or claim from a paper.

If the artifact already lives under `~/papers/<slug>/`, skip the fetch and go straight to reading.

## Core invariants

These are the rules that justify the skill existing. Keep them in mind on every turn:

1. **Never fabricate a citation.** If `citation.bib` couldn't be fetched from an authoritative source, say so explicitly. Don't synthesize a BibTeX entry from your own knowledge of the paper. A missing bib is a known state. A hallucinated bib is silent corruption that propagates into the user's own writing.
2. **Every claim about a paper gets an inline locator.** Format: `(FirstAuthor et al. Year, §<section>, p.<page>)`, or `(ibid., §..., p....)` for adjacent claims about the same paper. Locators come from the actual PDF. Read the section heading and the page number off the rendered PDF. Don't infer.
3. **Quote when paraphrasing risks distortion.** Use `"…"` for direct quotes from the paper, with the same locator.
4. **Results live in tables and figures.** When stating numbers, cite the table or figure: `(…, Table 3, p.8)` or `(…, Fig. 4, p.7)`. Don't round or restate numbers without checking the source.
5. **No tex source is not no paper.** Tex source is a bonus (lets you search exact wording, equations, and macros). Absence is not a blocker. The PDF plus bib is the floor.

The user picked these rules. The why is that papers get re-cited downstream and a fabricated bib or wrong table number is hard to detect later. See `references/citation-discipline.md` for the full discipline guide and worked examples.

## Workflow

### 1. Resolve the input to a canonical identifier

Take whatever the user gave you (URL, DOI, title, arXiv ID) and resolve to a *source kind* plus *id*:

- `arxiv.org/abs/<id>` or `arxiv.org/pdf/<id>`: kind=`arxiv`, id=`<id>` (strip `v<N>` only if the user clearly wants "latest"; preserve it if they referenced a specific version).
- `openreview.net/forum?id=<id>` or `pdf?id=<id>`: kind=`openreview`, id=`<id>`.
- `aclanthology.org/<paperid>`: kind=`acl`, id=`<paperid>`.
- A DOI (`10.xxxx/...` or `doi.org/...`): kind=`doi`, id=`<doi>`.
- A non-arXiv PDF URL: kind=`pdf`, id=`<url>` (bib lookup will go via Semantic Scholar by title after we read the title page).
- Just a title: kind=`title`, id=`<title>`. Let the fetch script resolve via Semantic Scholar.

### 2. Fetch the artifacts

Run the bundled fetcher. It handles the source-specific download paths, bib lookup with fallbacks, slug computation, and directory layout. Keep this single source of truth instead of reinventing the steps per session:

```bash
python3 ~/.claude/skills/paper-reader/scripts/fetch_paper.py <input>
```

`<input>` can be any of the forms above. The script:

- Picks a slug of the form `<firstauthor_lastname><year>-<first-significant-title-words>` (kebab-case), matching typical BibTeX cite keys so the directory name is memorable.
- Creates `~/papers/<slug>/` if missing.
- Downloads `paper.pdf`.
- For arXiv: also downloads `https://arxiv.org/e-print/<id>` (a `.tar.gz`) and extracts it into `source/`.
- Resolves a BibTeX entry through a fallback chain: **OpenAlex** (open, generous, no key) then publisher/venue native bib (ACL .bib, Crossref via DOI) then **DBLP** (CS-focused, very clean) then Semantic Scholar (rate-limited, used last) then arXiv-API-constructed (deterministic final fallback for arXiv inputs only). If every source fails, the script writes a `citation.MISSING` file with the full lookup trail instead of inventing an entry.
- For inputs without a deterministic PDF URL (DOIs, titles), tries **Unpaywall** and **OpenAlex** OA locations to find a legally-open PDF before giving up.
- Writes `meta.json` with canonical metadata (title, authors, year, venue, arxiv_id, doi, url, slug, bibkey, bib_trail).
- Prints the final path. Read `meta.json` for the bibkey before you start citing.

If the script errors on fetching (paywall, dead URL, no network), report what failed and ask the user how to proceed. Don't paper over it by guessing metadata.

### 3. Read the PDF

The `Read` tool's PDF support depends on **poppler being installed on the host**. On many machines (Linux servers, sandboxed environments, most CI runners) it isn't, and `Read` will fail on `.pdf` files. Don't waste turns probing this. Use the bundled extractor as the primary path:

```bash
uvx --with pypdf python ~/.claude/skills/paper-reader/scripts/extract_pages.py \
    ~/papers/<slug>/paper.pdf --pages 1-10 --out /tmp/<slug>-p1-10.txt
```

The output is page-marked plain text (`===== PAGE N =====` separators), which is exactly what you need to record `p.N` locators. Read the produced `.txt` file with the `Read` tool. That always works since it's plain text. For long papers, fetch in ranges of 10-15 pages per call.

`Read` on the PDF directly is fine as a fallback when poppler *is* installed and you want rendered visuals (figures, equations), but treat the extractor as the default.

For exact equation / wording / macro lookups, grep the tex source:

```bash
grep -rn "self-attention" ~/papers/<slug>/source/
```

The tex source is also the right place to find the exact numbers behind a table (often defined as `\newcommand` or sitting in a `.tex` table fragment) and the bibliography (`.bib` files in the source tree) when the user wants to follow a reference from this paper into another paper.

### 3a. Fast path: delegate the read to Haiku

Reading a 20-page paper end to end costs a lot of tokens on Opus/Sonnet. For the standard "fetch + summarize + cite" workflow, delegate the read to Haiku and use its structured output to write your reply. This is cheaper, faster, and produces better locator coverage because Haiku's job is just the read, not juggling response composition.

Two dispatch mechanisms. Use whichever your environment supports:

**Path A: `Agent` tool (top-level Claude Code session).** When the `Agent` tool is in your toolset, call it with `subagent_type=general-purpose, model=haiku` and the prompt below. The subagent's final text-result comes back as your tool result.

**Path B: `claude -p` via Bash (nested subagent contexts, automation, anywhere).** When you don't see `Agent` in your tools (you're already a subagent, or you're running headlessly), invoke Claude's CLI directly:

```bash
claude -p --model claude-haiku-4-5-20251001 <<'EOF'
<the same prompt as Path A>
EOF
```

Capture stdout. That's the JSON claim-index. The two paths are interchangeable. Pick whichever is available.

**The prompt** (same for both paths):

```
You are a paper-reader subagent. The paper is fully fetched at <paper_dir>.
- meta.json: <paste it>
- citation.bib: <paste it or note bibkey>
- PDF: <paper_dir>/paper.pdf (use the extract_pages.py script. Read tool may fail on PDFs here)
- tex source: <paper_dir>/source/ (grep for exact wording, equation defs, table data)

Produce a single JSON object with this shape:

{
  "bibkey": "<from citation.bib>",
  "sections": [{"num": "3.2", "title": "...", "pages": [5, 6]}, ...],
  "tables": [{"num": "2", "caption": "...", "page": 8, "key_numbers": [{"name": "EN-DE BLEU", "value": "28.4", "model": "Transformer (big)"}]}, ...],
  "figures": [{"num": "1", "caption": "...", "page": 3}, ...],
  "claims": [
    {"claim": "Self-attention is O(n²·d) per layer", "section": "3.2.2", "page": 6, "kind": "complexity"},
    {"claim": "Transformer outperforms ConvS2S by 2.0 BLEU on EN-DE", "table": "2", "page": 8, "kind": "result"}
  ],
  "tldr": "<one-paragraph summary, each sentence ending with the locator that backs it>"
}

No commentary, no markdown, just the JSON. Every claim must have a locator (section or table/figure plus page). If you can't locate it, drop it.
```

When the subagent returns, use its `claims[]` and `tldr` to compose your user-facing reply, with every claim carrying a locator from the index. The Haiku pass typically uses 10-20x fewer tokens than reading the whole PDF yourself.

When *not* to use this:
- The user asks for raw quoted passages. Read the relevant page yourself for verbatim fidelity.
- The user asks for figure interpretation that needs vision. Haiku-text can't see figures.
- The paper is very short (under 6 pages) or you only need one specific section. Direct read is fine.

### 4. Produce `notes.md`

After the first careful read, generate `~/papers/<slug>/notes.md` with this exact structure:

```markdown
# <Paper Title>

<bibkey> · <Author list> · <Venue Year> · [arXiv:<id>](https://arxiv.org/abs/<id>) / [doi:<doi>](...)

## TL;DR
One paragraph, max 4 sentences, every factual claim cited.

## Problem
What problem the paper addresses, why prior work was insufficient. Cite §1, §2.

## Method
Core idea plus the moving parts. Cite §3 (and the relevant subsection). Quote definitions when they matter.

## Key results
Bullet list. Each bullet is one result, cited with (Author Year, Table/Fig N, p.M):
- … (…, Table 2, p.8)
- … (…, Fig. 4, p.7)

## Limitations
What the paper itself flags (§ Limitations / Discussion) plus anything obvious you noticed. Mark the second kind as "[reader note]" so it isn't confused with the paper's own claims.

## Open questions / follow-ups
Free-form. Things to ask, things to verify, related papers worth pulling.
```

Citation format inside notes.md uses the inline-locator style (`(Vaswani et al. 2017, §3.2.2, p.6)`) by default, because the user picked that style. Mirror that style anywhere the paper is discussed elsewhere in the session.

### 5. Discussing the paper later

Once `notes.md` exists, you don't need to re-read the PDF cover to cover. But any specific claim, number, or quotation must still cite the actual source location (§ and page from the PDF, or table/figure number). Don't lift a number from notes.md without the locator that's attached to it.

When the user asks for a comparison across multiple papers, repeat the workflow for each one (each gets its own `~/papers/<slug>/`). Cite each paper with its own bibkey so the discussion stays unambiguous.

## When things go wrong

- **Bib lookup failed everywhere.** Don't fabricate. Write `citation.MISSING` (the script does this). When citing, use `(Author Year [bib unresolved])` and tell the user. They may have a private bib source. Note: for arXiv inputs the fetcher includes a final fallback that *constructs* a `@misc{…, archivePrefix={arXiv}}` entry from the arXiv API's structured metadata. This is logged in `bib_trail` as `arXiv API (constructed): OK`. That's authoritative for the preprint and safe to cite, but represents only the arXiv version (no venue / DOI). Surface this distinction if the user is writing for a venue that expects the published reference.
- **arXiv tex source is missing or encrypted.** Some papers don't publish source. Note it and proceed with PDF only.
- **Locator unknown.** If you can't find which section a claim lives in, say `(Author Year, §unknown, p.<N>)` with at least the page, or omit the claim. Never round a page number "close enough".
- **PDF is scanned / no text layer.** Read tool will still see the rendered image. Locators by page still work, but searching tex source or grepping won't. Tell the user.
- **User asks you to cite something you don't have.** Pull the paper first. Don't cite from your own training memory. That's the exact failure mode this skill exists to prevent.

## References

- `references/citation-discipline.md`: the strict locator format, worked examples, common failure modes, and how to handle "ibid." and multi-paper discussions.
- `references/sources.md`: per-source fetch URLs, bib lookup chains, and gotchas (arXiv versioning, OpenReview supplementary, ACL official .bib, Crossref vs Semantic Scholar for DOIs).
