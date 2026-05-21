#!/usr/bin/env python3
"""Extract page-marked text from a PDF using pypdf (via uvx, no system deps).

Output format:
    ===== PAGE 1 =====
    <text of page 1>
    ===== PAGE 2 =====
    <text of page 2>
    ...

Why this exists: the Read tool's PDF support depends on poppler being
installed on the host. On hosts where it isn't (and there are plenty),
the Read tool fails. pypdf is pure-Python and works everywhere `uvx` is
available, which on most machines is already the default for ad-hoc Python.

Usage:
    uvx --with pypdf python ~/.claude/skills/paper-reader/scripts/extract_pages.py <pdf> [--pages 1-10] [--out file.txt]

If --out is omitted, prints to stdout.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path


def parse_pages(spec: str, total: int) -> list[int]:
    if not spec:
        return list(range(1, total + 1))
    out: list[int] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if "-" in chunk:
            a, b = chunk.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(chunk))
    return [p for p in out if 1 <= p <= total]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="Path to PDF file")
    parser.add_argument("--pages", default="", help="Page range (e.g. '1-10' or '3,5,8-12'); default all")
    parser.add_argument("--out", default="", help="Output file (default stdout)")
    args = parser.parse_args()

    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        print(
            "ERROR: pypdf not available. Run via:\n"
            "  uvx --with pypdf python " + __file__ + " <pdf> [--pages 1-10]",
            file=sys.stderr,
        )
        sys.exit(2)

    pdf_path = Path(args.pdf).expanduser().resolve()
    reader = PdfReader(str(pdf_path))
    total = len(reader.pages)
    pages = parse_pages(args.pages, total)

    chunks: list[str] = []
    for p in pages:
        try:
            text = reader.pages[p - 1].extract_text() or ""
        except Exception as e:
            text = f"[extraction error: {e}]"
        chunks.append(f"===== PAGE {p} =====\n{text}\n")

    output = "".join(chunks)
    if args.out:
        Path(args.out).expanduser().write_text(output)
        print(f"wrote {len(output)} chars across {len(pages)} pages to {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(output)


if __name__ == "__main__":
    main()
