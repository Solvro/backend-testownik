"""Line diff of two Markdown texts with changed words marked, rendered as HTML for the admin."""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import zip_longest

from django.utils.html import escape, format_html, format_html_join
from django.utils.safestring import SafeString, mark_safe

TOKEN = re.compile(r"\s+|[^\s]+")


@dataclass
class TextDiff:
    html: SafeString
    added: int
    removed: int

    @property
    def is_empty(self):
        return self.added == 0 and self.removed == 0


def _mark_words(old, new):
    """Both lines with the words that differ wrapped in <del> and <ins>."""
    old_tokens, new_tokens = TOKEN.findall(old), TOKEN.findall(new)
    old_html, new_html = [], []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, old_tokens, new_tokens, autojunk=False).get_opcodes():
        old_part, new_part = escape("".join(old_tokens[i1:i2])), escape("".join(new_tokens[j1:j2]))
        if tag == "equal":
            old_html.append(old_part)
            new_html.append(new_part)
            continue
        if old_part:
            old_html.append(f"<del>{old_part}</del>")
        if new_part:
            new_html.append(f"<ins>{new_part}</ins>")
    return mark_safe("".join(old_html)), mark_safe("".join(new_html))  # noqa: S308 – parts are escaped


def _row(kind, old_number, new_number, text):
    sign = {"add": "+", "del": "−", "ctx": ""}[kind]
    return format_html(
        '<div class="ld-row ld-{}"><span class="ld-num">{}</span><span class="ld-num">{}</span>'
        '<span class="ld-sign">{}</span><span class="ld-text">{}</span></div>',
        kind,
        old_number or "",
        new_number or "",
        sign,
        text,
    )


def _gap(count):
    return format_html('<div class="ld-gap">⋯ {} unchanged</div>', f"{count} lines" if count != 1 else "1 line")


def diff_texts(old, new, context=2):
    old_lines, new_lines = old.splitlines(), new.splitlines()
    rows, added, removed = [], 0, 0
    opcodes = SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_opcodes()
    for index, (tag, i1, i2, j1, j2) in enumerate(opcodes):
        if tag == "equal":
            lines = list(range(i2 - i1))
            keep_start = context if index > 0 else 0
            keep_end = context if index < len(opcodes) - 1 else 0
            if len(lines) > keep_start + keep_end + 1:
                shown = lines[:keep_start] + [None] + (lines[len(lines) - keep_end :] if keep_end else [])
            else:
                shown = lines
            for offset in shown:
                if offset is None:
                    rows.append(_gap(len(lines) - keep_start - keep_end))
                else:
                    rows.append(_row("ctx", i1 + offset + 1, j1 + offset + 1, old_lines[i1 + offset]))
            continue
        old_chunk, new_chunk = old_lines[i1:i2], new_lines[j1:j2]
        removed += len(old_chunk)
        added += len(new_chunk)
        deleted_rows, inserted_rows = [], []
        for offset, (old_line, new_line) in enumerate(zip_longest(old_chunk, new_chunk)):
            if old_line is not None and new_line is not None:
                old_line, new_line = _mark_words(old_line, new_line)
            if old_line is not None:
                deleted_rows.append(_row("del", i1 + offset + 1, None, old_line))
            if new_line is not None:
                inserted_rows.append(_row("add", None, j1 + offset + 1, new_line))
        rows += deleted_rows + inserted_rows
    html = format_html('<div class="legal-diff">{}</div>', format_html_join("", "{}", ((row,) for row in rows)))
    return TextDiff(html=html, added=added, removed=removed)
