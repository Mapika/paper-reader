# Citation discipline

This is the contract that makes the paper-reader skill worth using. Read it before discussing any paper.

## Why this matters

Citations propagate. A claim you make about a paper today might get pasted into a doc, a PR description, a slide, or another paper. If the citation is wrong (wrong page, wrong section, wrong year, wrong author, wrong paper entirely), that error is invisible at the moment of use and very hard to recover from. Hallucinated BibTeX is the worst case: it looks correct, and downstream tools (LaTeX, reference managers, search) will silently accept it.

So the rule isn't "be careful with citations." The rule is **a citation is a verifiable pointer to a location in a specific document**, and if you can't verify the pointer, you don't write the citation.

## Locator format

Default style: inline parenthetical with section and page.

```
(FirstAuthor et al. Year, §<section>, p.<page>)
```

Worked examples:

| What you're citing | Citation |
|---|---|
| A method described in §3.2.2 of Vaswani et al. 2017 | `(Vaswani et al. 2017, §3.2.2, p.6)` |
| A number in Table 2, page 8 | `(Vaswani et al. 2017, Table 2, p.8)` |
| A figure on page 7 | `(Vaswani et al. 2017, Fig. 4, p.7)` |
| The same paper, adjacent claim | `(ibid., §3.3, p.7)` |
| A quoted phrase | `"…multi-head attention allows the model to jointly attend to information from different representation subspaces…" (Vaswani et al. 2017, §3.2.2, p.5)` |
| Two-author paper | `(Devlin & Lee 2019, §4, p.4172)` |
| Single-author paper | `(Schmidhuber 2015, §2.1, p.4)` |

Why this format:

- **Author Year** is unambiguous if you've also got the bib entry. The reader can resolve it.
- **§N** locates the claim semantically (sections rarely move when a paper is revised).
- **p.N** locates the claim physically (pages don't move within a fixed PDF).
- Having both is belt-and-suspenders: if the user wants to verify, they can jump to the page or grep the section heading.

## Ibid. rules

Use `(ibid., …)` when:

- The immediately preceding citation in the same paragraph is the same paper, AND
- There's no ambiguity (no other paper cited between this one and the prior).

If a different paper appears between two citations to the same source, repeat the full author/year. Don't make the reader scan backwards.

## Quotations

Quote when the exact wording matters: definitions, hedges, scope claims, claims you suspect could be misread if paraphrased. Use straight double quotes `"…"`. Always attach a locator. If you trim mid-quote, use `…` (an ellipsis, not three periods).

When you paraphrase, you're still on the hook for the locator. Paraphrase isn't a license to drop citation precision.

## Numbers and tables

Numbers from a paper get cited with the table or figure they came from. **Don't round** without saying so. If the paper reports `28.4 BLEU` and you write `~28 BLEU`, that's a small approximation. Flag it with `~` and keep the precise number nearby.

If the paper reports a number that contradicts a number elsewhere in the same paper (this happens, table vs. text mismatch), cite both and note the discrepancy. Don't pick one silently.

## When the locator is unknown

If you have the paper but can't find which section a claim sits in (common when the claim is in an unlabeled introductory paragraph):

- Give at least the page number: `(Author Year, §unknown, p.<N>)`.
- Or, if the page is also uncertain, prefer to omit the claim over guessing.
- "Close enough" is not a thing here.

## When the bib is missing

If `citation.MISSING` exists in the paper's directory (the fetcher couldn't find a real BibTeX entry from any source), mark every citation as `(Author Year [bib unresolved])` and tell the user. They may have a private bib source, or may want to construct one manually. Do not synthesize a `@article{…}` entry from your knowledge of the paper.

## Multi-paper discussions

When discussing several papers in one paragraph, use the bibkeys (from each paper's `meta.json`) to keep things tight:

```
Both FlashAttention (Dao et al. 2022, §3, p.4) and Memory-Efficient Attention
(Rabe & Staats 2021, §2, p.3) reduce the O(n²) memory footprint of standard
attention, but they differ in how aggressively they recompute during the
backward pass.
```

Don't collapse multiple papers behind a single citation marker like `[1,2]` unless the user has explicitly asked for that style.

## Anti-patterns

These show up when discipline slips. Each one is the same root cause: the citation got disconnected from the source.

- **Citation without locator.** "Vaswani et al. 2017 showed that self-attention is O(n²)." Which section? Page? Table? Add the locator.
- **Locator without verification.** Writing `§3.2.1` because it "sounds right". Never. Open the PDF.
- **Year drift.** The arXiv preprint year and the conference year often differ by 1. Use the year from `citation.bib`, which reflects the version you pulled.
- **Author count drift.** Saying "Vaswani et al." when the paper has two authors. Use `&` for two authors, `et al.` for three or more.
- **First-name guesses.** Don't fill in author first names from memory. Use what's in `meta.json` / `citation.bib`.
- **Cross-paper contamination.** Don't attribute a method from paper A to paper B because they're in the same area. Re-check `meta.json`.

## Trusting yourself less than the file

The whole point of pulling the artifacts to disk is that your memory of the paper is now beside the point. The source of truth is `~/papers/<slug>/`. If your recollection conflicts with the file, the file wins. Re-read the relevant pages.
