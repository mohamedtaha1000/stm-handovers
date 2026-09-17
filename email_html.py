"""
email_html.py
=============
Outlook-safe HTML for the messages this app opens.

Every message here is written twice: plain text for a mailto: link,
which can carry nothing else, and HTML for the drafts Outlook is asked
to open directly, where the details can be a ruled table. This module is
the HTML half, and it is the ONLY place the look of an email is decided
- one paragraph style, one table style, used by every message.

It knows nothing about employees, laptops or leavers. It is handed
headings and (label, value) pairs and gives back markup.

The styling is deliberately old-fashioned. Outlook lays out HTML with
Word's engine, which ignores stylesheets, floats and most of modern CSS,
so every rule is an inline style on the element it applies to and the
tables carry cellspacing/cellpadding attributes as well. Calibri 11pt is
Outlook's own composing font, so the message and the sender's signature
under it read as one email.

Everything that came from a person is escaped on the way in: a name with
an ampersand in it is a name, never markup.
"""
from collections.abc import Iterable
from html import escape

FONT = "font-family:Calibri,'Segoe UI',Arial,sans-serif;font-size:11pt;color:#1a1a1a;"
LINE = "#d4d4d4"
LABEL_BG = "#f2f4f7"

_CELL = f"{FONT}padding:6px 13px;border:1px solid {LINE};"


def paragraph(inner: str) -> str:
    """One line of the message. `inner` is markup, so anything typed has
    already been escaped by whoever built it."""
    return f'<p style="{FONT}margin:0 0 11px;">{inner}</p>'


def heading(text: str) -> str:
    """A section heading above a table - bold, and tight to the table
    under it rather than floating between the two."""
    return (f'<p style="{FONT}margin:0 0 6px;"><b>{escape(text)}</b></p>')


def table(rows: Iterable[tuple[str, str]]) -> str:
    """Label and value, one row each, as a ruled two-column table.

    Rows arrive as (label, value) pairs and are written exactly as given,
    empty values included: whoever built them has already decided what
    belongs in the message.
    """
    body = "".join(
        f'<tr>'
        f'<td style="{_CELL}background:{LABEL_BG};font-weight:bold;'
        f'white-space:nowrap;">{escape(label)}</td>'
        f'<td style="{_CELL}">{escape(value)}</td>'
        f'</tr>'
        for label, value in rows)
    return ('<table cellspacing="0" cellpadding="0" border="0" '
            f'style="border-collapse:collapse;margin:0 0 15px;">{body}</table>')


def section(title: str, rows: Iterable[tuple[str, str]]) -> str:
    """A heading and its table, or nothing at all when there are no rows
    - an empty table is worse than a missing one."""
    return heading(title) + table(rows) if rows else ""
