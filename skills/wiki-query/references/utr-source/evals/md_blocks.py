#!/usr/bin/env python3
"""Markdown block splitting shared by ste_lint.py and utr_lint.py.

A sentence counter that splits only on `.!?:` merges every line of a markdown
table or of a tight list into one giant "sentence", because those lines carry
no terminal punctuation. That inflates the over-limit counter on exactly the
structures both standards ask for (vertical lists: STE 4.4, УТР 8.2.3.16).

So split by block first, then by punctuation inside each block:

- a table row is a block, and each of its cells is a separate text unit;
- a list item, a quote line, and a heading are each one block;
- consecutive plain lines are ONE block, so hard-wrapped prose stays whole.
"""
import re

# A line that opens its own block: list marker, table row, quote, heading.
BLOCK_START = re.compile(r"^\s*(?:[-*•—+]\s|\d+[.)]\s|\||>|#)")
# The |---|:--:| separator row of a table. Not text.
TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]*\|[\s:|-]*$")
# Leading marker to drop once a block is isolated.
MARKER = re.compile(r"^\s*(?:[-*•—+]|\d+[.)]|>|#+)\s*")


def blocks(text):
    """Split text into block-level units, joining soft-wrapped lines."""
    units, para = [], []

    def flush():
        if para:
            units.append(" ".join(para))
            para.clear()

    for line in text.split("\n"):
        if not line.strip() or TABLE_SEP.match(line):
            flush()
            continue
        if BLOCK_START.match(line):
            flush()
            units.append(line)
        else:
            para.append(line.strip())
    flush()
    return units


def units(text):
    """Block units with table rows exploded into cells and markers removed."""
    out = []
    for block in blocks(text):
        if block.lstrip().startswith("|"):
            out += [c.strip() for c in block.strip().strip("|").split("|")]
        else:
            out.append(MARKER.sub("", block))
    return [u for u in out if u.strip()]
