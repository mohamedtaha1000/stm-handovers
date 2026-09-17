"""
notify_email.py
===============
Builds the "this has been handed over" message for the asset owner.

Delivered as a mailto: link, not a file and not an SMTP send: one click
opens a new Outlook message with the address, subject and details
already filled in, and the person reads it and presses Send from their
own mailbox. So the app never needs a mailbox password or an SMTP host.

A mailto: can only carry PLAIN TEXT. That rules out a ruled table and
it rules out bold, so the details are laid out as a labelled list
instead - a framed section heading, then one "Label: value" line per
detail. It is deliberately not space-padded into columns: Outlook
composes in a proportional font (Calibri), where padded columns come out
ragged and look worse than no columns at all. A labelled list reads the
same in every font, and the message opens as an editable draft, so
anyone who wants the headings actually bold can do it before sending.

There is no sign-off in the body: the draft opens in the sender's own
Outlook, which puts their signature under it.

Every value comes from what the handover document already records -
nothing is collected twice, and a field the documents have no source for
(the employee's manager, their personal email, the computer name) is
left out rather than printed as an empty row.
"""

from html import escape
from typing import Any

import email_html
from models import Handover
from templates import TEMPLATES

# The employee lines, in the order the team writes them.
#
# Six, and only these six. A start date and a preferred name used to be
# worked out and added here - the date from the document, the preferred
# name from the first two words of the full name - but neither is
# something the team asked for, and a row nobody reads is a row that
# makes the table harder to scan. They are gone.
#
# The national ID is on the document but deliberately NOT in the email:
# it is masked everywhere else in the app, and an unencrypted mail is not
# the place to widen that.
EMPLOYEE_LINES = (
    ("Employee Name", "name"),
    ("Employee Code", "code"),
    ("Position Title", "role"),
    ("Department", "department"),
    ("Phone Number", "mobile"),
    ("Email", "email"),
)

# "Company" is on every document but is the same Arabic company name
# every time, so it earns no line.
SKIP_DEVICE_KEYS = {"company"}

# Headings the team writes differently from the form's field labels.
HEADING_OVERRIDES = {"serial": "Serial Number", "sim_number": "Data SIM Number"}

# The order the team reads the equipment details in, which is not the
# order the form collects them (the form asks for the CPU next to the
# model and serial; the team reads it last, after the memory). Anything
# not listed keeps the order its template defines, after these.
# Identity first (whose make, which model, which serial), then what it
# is made of, ending with the CPU the way the team writes a laptop.
DEVICE_LINE_ORDER = ("brand", "model", "serial", "sim_number", "capacity",
                     "color", "storage", "ram", "cpu")


def column_heading(label: str) -> str:
    """A field label as a heading: "Serial number" becomes "Serial
    Number", while RAM and CPU are left alone rather than being flattened
    into Ram and Cpu."""
    return " ".join(w.capitalize() if w.islower() else w for w in label.split())


def base_key(key: str) -> str:
    """"old_serial" is a serial; the "old" belongs to the section, not to
    the line."""
    for prefix in ("old_", "new_"):
        if key.startswith(prefix):
            return key[len(prefix):]
    return key


def detail_label(key: str, label: str, heading: str = "") -> str:
    """The label for one equipment line, with anything the section
    heading above it already says stripped off: "Old serial number" under
    OLD DEVICE is just "Serial Number", and "Laptop model" under LAPTOP
    DETAILS is just "Model"."""
    base = base_key(key)
    if base in HEADING_OVERRIDES:
        return HEADING_OVERRIDES[base]
    words = label.split()
    said = {w.lower().strip("&") for w in heading.split()} | {"old", "new"}
    while len(words) > 1 and words[0].lower() in said:
        words.pop(0)
    return column_heading(" ".join(words))


def display_name(record: Handover) -> str:
    """The name this message calls the person.

    The English one, because the message is in English - falling back to
    the Arabic name for records made before that box existed, so an old
    document still produces a usable email rather than a blank line.
    """
    return (record.fields.get("name_en") or "").strip() or record.name


def employee_rows(record: Handover) -> list[tuple[str, str]]:
    """The employee block as (label, value) pairs.

    One description of what the block IS, so the plain-text list and the
    table are two renderings of the same thing and cannot drift apart. A
    detail the documents have no source for is left out rather than
    printed as an empty row.
    """
    fields = record.fields
    rows: list[tuple[str, str]] = []
    for label, key in EMPLOYEE_LINES:
        # The name is a column of its own on the record; everything else
        # is whatever that document type collected.
        value = display_name(record) if key == "name" else (fields.get(key) or "").strip()
        if value:
            rows.append((label, value))
    return rows


def employee_lines(record: Handover) -> list[str]:
    """The employee block as "Label: value" lines, for the plain text."""
    return [f"{label}: {value}" for label, value in employee_rows(record)]


def device_sections(record: Handover) -> list[tuple[str, list[tuple[str, str]]]]:
    """The equipment blocks for one document: (heading, rows) pairs,
    where each row is (label, value).

    Usually one - "Laptop details" - but a replacement has two, the
    device going back and the device going out.
    """
    spec = TEMPLATES.get(record.template_id)
    if spec is None:
        return []
    fields = record.fields
    groups = [(spec.get("device_title") or "Details",
               list(spec.get("device_fields", [])) + list(spec.get("extra_fields", [])))]
    if spec.get("device_fields_2"):
        groups.insert(1, (spec.get("device_title_2") or "Details",
                          list(spec["device_fields_2"])))

    def rank(pair: tuple[int, dict[str, Any]]) -> int:
        index, f = pair
        key = base_key(f["key"])
        return (DEVICE_LINE_ORDER.index(key) if key in DEVICE_LINE_ORDER
                else len(DEVICE_LINE_ORDER) + index)

    sections: list[tuple[str, list[tuple[str, str]]]] = []
    for title, group in groups:
        rows: list[tuple[str, str]] = []
        for _, f in sorted(enumerate(group), key=rank):
            key = f["key"]
            if key in SKIP_DEVICE_KEYS:
                continue
            value = (fields.get(key) or "").strip()
            if value:
                rows.append((detail_label(key, f["label"], title), value))
        if rows:
            sections.append((title, rows))
    return sections


def subject_for(records: list[Handover]) -> str:
    first = records[0]
    spec = TEMPLATES.get(first.template_id)
    label = spec["label"] if spec else first.template_label
    code = (first.fields.get("code") or "").strip()
    shown = display_name(first)
    who = f"{shown} ({code})" if code else shown
    if len(records) > 1:
        return f"Equipment handover — {who}"
    return f"{label} — {who}"


def opening_line(records: list[Handover]) -> str:
    """What was handed over, named the way the document names it."""
    if len(records) > 1:
        items: list[str] = []
        for record in records:
            spec = TEMPLATES.get(record.template_id)
            short = (spec.get("short") if spec else None) or record.template_label
            items.append(short.lower())
        listed = ", ".join(items[:-1]) + " and " + items[-1]
        return (f"Please be informed that the following have been handed over: "
                f"{listed}. The details are as follows:")
    record = records[0]
    spec = TEMPLATES.get(record.template_id)
    short = (spec.get("short") if spec else None) or record.template_label
    thing = short.lower()
    if record.template_id == "laptop_replacement":
        return ("Please be informed that the laptop has been replaced. "
                "The details are as follows:")
    return (f"Please be informed that the {thing} has been handed over. "
            f"The {thing} details are as follows:")


# The heading frame. A mailto: carries plain text, so the headings
# cannot be bold - this is what makes them catch the eye instead. The
# equals signs are safe: Outlook's autoformat only turns a line into a
# page-wide border when the line is NOTHING BUT three or more of
# = - _ ~ * #, and these lines have words between them.
HEADING_FRAME = "==="


def section(heading: str, lines: list[str]) -> list[str]:
    """A block: the framed heading in capitals, then its lines, then a
    blank line."""
    return [f"{HEADING_FRAME} {heading.upper()} {HEADING_FRAME}", *lines, ""]


def short_name(record: Handover) -> str:
    spec = TEMPLATES.get(record.template_id)
    return ((spec.get("short") if spec else None) or record.template_label).lower()


def build_body(
    records: list[Handover], greeting_name: str, detailed: list[Handover] | None = None
) -> str:
    """The whole message as plain text, which is all a mailto: can carry.

    One employee block - a batch is always one person - then one block
    per piece of equipment, so nothing is repeated down the message.

    It ends at the details, with no sign-off: the draft opens in the
    sender's own Outlook, which adds their signature under it.

    `detailed` is the subset to spell out, used only when the full
    message would be longer than a mail client will accept from a link.
    Everything handed over is still named in the opening line; the items
    that lost their block are named again at the end, so the message says
    plainly what it is not showing rather than stopping mid-word.
    """
    detailed = records if detailed is None else detailed
    lines = [f"Dear {greeting_name},", "", opening_line(records), ""]
    lines += section("Employee details", employee_lines(records[0]))
    for record in detailed:
        for title, rows in device_sections(record):
            lines += section(title, [f"{label}: {value}" for label, value in rows])
    left_out = [short_name(r) for r in records[len(detailed):]]
    if left_out:
        listed = (", ".join(left_out[:-1]) + " and " + left_out[-1]
                  if len(left_out) > 1 else left_out[0])
        lines += [f"The {listed} details are on their own handover documents.", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- HTML
#
# The same message for a draft Outlook is asked to open itself, where
# the details can be ruled tables rather than framed lists. The framing
# below exists only because plain text has no bold; in HTML the heading
# simply is bold, so the equals signs go.
#
# How a table looks is not decided here - email_html renders every
# message this app sends, so they all look like they came from the same
# place.

def build_html(
    records: list[Handover], greeting_name: str, detailed: list[Handover] | None = None
) -> str:
    """The whole message as HTML: one employee table, then one table per
    piece of equipment.

    `detailed` exists for the plain-text version, which has a length a
    mail client will refuse. A draft opened through Outlook has no such
    limit, so this is normally called with everything - but it is
    honoured either way rather than quietly disagreeing with the text.
    """
    detailed = records if detailed is None else detailed
    parts = [email_html.paragraph(escape(f"Dear {greeting_name},")),
             email_html.paragraph(escape(opening_line(records))),
             email_html.section("Employee details", employee_rows(records[0]))]
    for record in detailed:
        for title, rows in device_sections(record):
            parts.append(email_html.section(title, rows))
    left_out = [short_name(r) for r in records[len(detailed):]]
    if left_out:
        listed = (", ".join(left_out[:-1]) + " and " + left_out[-1]
                  if len(left_out) > 1 else left_out[0])
        parts.append(email_html.paragraph(
            escape(f"The {listed} details are on their own handover documents.")))
    return "".join(parts)
