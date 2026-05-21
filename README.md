# paper-reader

Claude Code skill for reading research papers without making things up.

Pulls the PDF (and the arXiv tex source if available), fetches a real BibTeX entry from open sources, and forces every claim in your answer to carry a section or table/figure plus page number. If the bib can't be resolved, it says so instead of inventing one.

## Install

In Claude Code:

```
/plugin marketplace add Mapika/paper-reader
/plugin install paper-reader@mapika
```

The first command registers this repo as a marketplace (named `mapika`). The second pulls the `paper-reader` plugin from it.

Or just clone the skill folder directly:

```bash
git clone https://github.com/Mapika/paper-reader /tmp/pr && \
  cp -r /tmp/pr/plugins/paper-reader/skills/paper-reader ~/.claude/skills/
```

Restart Claude Code and the skill loads automatically.

## What it does

Give it any of:

* arXiv URL or ID (`1706.03762`, `arxiv.org/abs/...`)
* OpenReview, ACL Anthology, DOI, or a plain PDF URL
* Just a paper title

It runs `scripts/fetch_paper.py`, which puts the artifacts under `~/papers/<slug>/`:

```
~/papers/dao2022-flashattention-fast-memory-efficient/
  paper.pdf
  citation.bib       real, sourced via the chain below
  meta.json          title, authors, year, bibkey, bib_trail
  source/            arXiv tex tree (extracted)
  notes.md           generated on first read
```

Bib lookup chain, in order:

1. OpenAlex (open, no API key, generous limits)
2. Publisher native (ACL `.bib`, Crossref by DOI)
3. DBLP (CS specific, very clean entries)
4. Semantic Scholar (last because of 429s)
5. arXiv API constructed (deterministic fallback for arXiv inputs)

If none of those return anything, the script writes `citation.MISSING` with the full trail. It will not synthesize a BibTeX entry from training memory.

For DOI inputs without an obvious PDF URL, it tries Unpaywall and the OpenAlex `best_oa_location.pdf_url` field before giving up.

## Citation discipline

Default style is inline locators:

```
Self-attention runs in O(n²·d) per layer (Vaswani et al. 2017, §3.2.2, p.6).
The Transformer outperforms ConvS2S by 2.0 BLEU on EN-DE (ibid., Table 2, p.8).
```

Every factual claim about a paper gets one. Numbers cite the table or figure they came from. If a locator can't be found, the claim gets dropped rather than rounded into a guess.

## Numbers

Three test prompts (FlashAttention summary, GPT-3 title-only bibtex, "Attention Is All You Need" answer-from-memory), with the skill vs. no skill, single run each:

| | with skill | no skill | delta |
|---|---|---|---|
| Pass rate | 0.93 | 0.70 | +23 pts |
| Wall clock | 170 s | 42 s | +128 s |
| Tokens | 61 k | 18 k | +43 k |

The skill is slower and more expensive. That's the deal. If you want a vague summary, don't load it.

What the gap actually looks like, on the same prompt:

> baseline: *"FlashAttention is 15% faster on BERT, 3x on GPT-2, 2.4x on LRA."*
>
> with skill: *"BERT-large in 17.4 min vs 20.0 min for the MLPerf 1.1 record (Dao et al. 2022, Table 1, p.7). GPT-2 small reaches 18.2 ppl on OpenWebText in 2.7 days vs 9.5 for HuggingFace and 4.7 for Megatron-LM (ibid., Table 2, p.8). LRA 2.4x on the vanilla Transformer at lengths 1K-4K (ibid., Table 3, p.8)."*

## Optional fast path: Haiku reviewer

Reading a 20-page paper end to end is expensive on Opus/Sonnet. The skill can dispatch the read to Haiku and use a returned JSON claim-index to compose the reply. Two ways to invoke it:

* `Agent` tool with `model=haiku` (top-level Claude Code session)
* `claude -p --model claude-haiku-4-5-20251001` via Bash (works inside subagents, headless contexts, automation)

The skill picks whichever is available. If neither is, it falls back to reading directly via the bundled `extract_pages.py`.

## Dependencies

Python 3.9+ for the fetcher (stdlib only, no pip install needed). `uvx` for PDF text extraction via pypdf. No system packages required, specifically no poppler.

Network access to: `arxiv.org`, `api.openalex.org`, `dblp.org`, `api.crossref.org`, `aclanthology.org`, `api.semanticscholar.org`, `api.unpaywall.org`.

## License

MIT.
