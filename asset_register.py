# -*- coding: utf-8 -*-
"""
asset_register.py
=================
The laptop register: one spreadsheet saying who has which machine, what
it is, who gave it to them, and whether they still have it.

It is DERIVED, never edited. Every time a document is generated, edited
or deleted, and every time someone is marked as having left, the whole
sheet is rebuilt from the database. That is slower than patching one row
and worth it: a register that is rebuilt cannot drift from the records it
describes, and there is no state to repair when something goes wrong
halfway. It also means the very first rebuild backfills every document
ever generated, with no import step.

The trade is that hand-edits to the .xlsx are overwritten on the next
document. If a row is wrong, the record behind it is wrong - fix it in
the app and the sheet follows.

Two sheets. LAPTOPS is one row per assignment, so the history is kept:
replacing a laptop marks the old row Replaced and adds a new one rather
than overwriting - filter Status = Held for the current picture. LEAVERS
is one row per person who has gone, with the date and what they were
holding at the time, because "who left and what do we need back" is a
different question from "where is every machine".
"""

from datetime import datetime

# Only the documents that issue a computer. A headset receipt has a
# serial number too and it has no business in a laptop register.
LAPTOP_TEMPLATES = {
    # template id -> where that document's fields keep the machine it
    # ISSUES. A replacement hands over the "new_" one; the machine it
    # takes back is the row already in the register.
    "laptop_handover": "",
    "laptop_replacement": "new_",
}

# Both spellings, side by side. The documents are Arabic and the emails
# are English, so whichever of the two someone is holding when they come
# to the register, the name is there to match against.
COLUMNS = (
    ("Employee (Arabic)", 24), ("Employee (English)", 26),
    ("Employee code", 14), ("Department", 18), ("Email", 26),
    ("Computer name", 16), ("Model", 20), ("Serial number", 18),
    ("CPU", 10), ("RAM", 10), ("Storage", 14), ("Colour", 12),
    ("Document", 20), ("Assigned on", 13), ("Assigned by", 18),
    ("Status", 11), ("Ended on", 13), ("Note", 30),
)

HELD, REPLACED, LEFT = "Held", "Replaced", "Left"

# The leavers sheet: one row per person who has gone, not per machine.
# It answers a different question from the Laptops sheet - "who left,
# when, and what did they have" - so it is a summary, and the machine
# columns stay on the sheet that is about machines.
# The tab the resignation rows go on. Named once: the sheet is looked up
# by this name as well as written under it.
LEAVER_SHEET = "Resignation"

LEAVER_COLUMNS = (
    ("Employee (Arabic)", 24), ("Employee (English)", 26),
    ("Employee code", 14), ("Department", 18), ("Email", 26),
    ("Left on", 13), ("Recorded by", 18), ("Held at the time", 42),
)

# Held is the one worth spotting from across the room; the other two are
# history and should stay quiet.
STATUS_FILL = {
    HELD: "E9F4EE",
    REPLACED: "F1F3F9",
    LEFT: "FDECEB",
}
STATUS_TEXT = {
    HELD: "1F6B4A",
    REPLACED: "5F6577",
    LEFT: "9C2B1F",
}


def parse_date(value):
    """The "D/M/YYYY" the records store, as a date. Anything unparseable
    sorts last rather than raising - a register that refuses to build
    because one row has a typo in it is worse than one odd row."""
    text = (value or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def show_date(value):
    """1-Sep-26, matching how the emails write dates."""
    parsed = parse_date(value)
    if parsed is None:
        return (value or "").strip()
    return f"{parsed.day}-{parsed.strftime('%b')}-{parsed.strftime('%y')}"


def assignment(record, identity):
    """One laptop handed to one person, or None if this document did not
    hand over a laptop."""
    if record.template_id not in LAPTOP_TEMPLATES:
        return None
    prefix = LAPTOP_TEMPLATES[record.template_id]
    fields = record.fields

    def field(key):
        return (fields.get(prefix + key) or "").strip()

    return {
        "identity": identity,
        "record_id": record.id,
        "name": record.name or (fields.get("name") or "").strip(),
        "name_en": (fields.get("name_en") or "").strip(),
        "code": (fields.get("code") or "").strip(),
        "department": (fields.get("department") or record.department or "").strip(),
        "email": (fields.get("email") or "").strip(),
        "computer_name": (fields.get("computer_name") or "").strip(),
        "model": field("model"),
        "serial": field("serial"),
        "cpu": field("cpu"),
        "ram": field("ram"),
        "storage": field("storage"),
        "color": field("color"),
        "document": record.template_label,
        "date": record.handover_date or "",
        "sort_date": parse_date(record.handover_date),
        "by": record.created_by or "",
        "status": HELD,
        "ended": "",
        "note": "",
    }


def build_rows(records, identity_of, departures):
    """Every laptop assignment, newest first, with a status worked out
    per person.

    `departures` maps an employee identity to a Departure-shaped object
    with `.left_on` and `.name`.
    """
    rows = []
    for record in records:
        found = assignment(record, identity_of(record))
        if found and (found["serial"] or found["model"]):
            rows.append(found)

    # Per person, oldest first: everything but their latest machine has
    # been superseded, and the replacement's own date is the day the old
    # one came back.
    by_person = {}
    for row in rows:
        by_person.setdefault(row["identity"], []).append(row)

    for identity, mine in by_person.items():
        mine.sort(key=lambda r: (r["sort_date"] or datetime.min.date(), r["record_id"]))
        for older, newer in zip(mine, mine[1:]):
            older["status"] = REPLACED
            older["ended"] = newer["date"]
            older["note"] = f"Replaced by {newer['model'] or 'a new machine'}".strip()
        gone = departures.get(identity)
        if gone is not None:
            # Leaving trumps holding: the machine is not theirs any more
            # whatever the last document said. Rows already marked
            # Replaced stay that way - they ended before the person did.
            current = mine[-1]
            current["status"] = LEFT
            current["ended"] = gone.left_on or ""
            current["note"] = "Employee left the company"

    rows.sort(key=lambda r: (r["sort_date"] or datetime.min.date(), r["record_id"]),
              reverse=True)
    return rows


def build_leavers(rows, departures):
    """One row per person who has resigned, newest departure first.

    Everyone recorded as having left is here, whether or not they ever
    held a laptop: the sheet is about people. Where they did, their
    equipment is read off the same assignment rows as the main sheet, so
    it cannot drift between the two; someone holding two machines gets
    both in one cell rather than two rows, because the Laptops sheet
    already answers that question better. Where they did not, their
    details come from what was typed when they were recorded - which is
    the only place those exist.
    """
    by_person = {}
    for row in rows:
        by_person.setdefault(row["identity"], []).append(row)

    leavers = []
    for identity, gone in departures.items():
        mine = by_person.get(identity, [])
        newest = max(mine, key=lambda r: (r["sort_date"] or datetime.min.date(),
                                          r["record_id"]), default=None)
        held = ", ".join(
            f"{r['model']} ({r['serial']})" if r["serial"] else r["model"]
            for r in mine if r["status"] == LEFT) or "\u2014"
        newest = newest or {}
        leavers.append({
            "name": newest.get("name") or gone.name or "",
            "name_en": (newest.get("name_en")
                        or getattr(gone, "name_en", "") or ""),
            "code": newest.get("code") or getattr(gone, "code", "") or "",
            "department": (newest.get("department")
                           or getattr(gone, "department", "") or ""),
            "email": newest.get("email") or getattr(gone, "email", "") or "",
            "left_on": gone.left_on or "",
            "sort_date": parse_date(gone.left_on),
            "by": gone.recorded_by or "",
            "held": held,
        })
    leavers.sort(key=lambda r: (r["sort_date"] or datetime.min.date(), r["name"]),
                 reverse=True)
    return leavers


def leaver_values(row):
    return [row["name"], row["name_en"], row["code"], row["department"],
            row["email"], show_date(row["left_on"]), row["by"], row["held"]]


def row_values(row):
    return [row["name"], row["name_en"], row["code"], row["department"],
            row["email"],
            row["computer_name"], row["model"], row["serial"], row["cpu"],
            row["ram"], row["storage"], row["color"], row["document"],
            show_date(row["date"]), row["by"], row["status"],
            show_date(row["ended"]), row["note"]]


def lay_out(ws, columns, values, title):
    """A sheet: bold shaded header, sensible widths, frozen top row and
    filter buttons. Both sheets are the same shape of thing, so they are
    built by the same function rather than by two near-identical blocks."""
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    ws.title = title
    ws.append([heading for heading, _ in columns])
    head_fill = PatternFill("solid", fgColor="E9ECF3")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = head_fill
        cell.alignment = Alignment(vertical="center")

    for row in values:
        ws.append(row)

    for i, (_, width) in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width

    # Filter buttons on the header row and the header frozen, because the
    # first thing anyone does with this is filter it.
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{max(ws.max_row, 1)}"
    return ws


def write_workbook(rows, path, departures=None):
    """The workbook: one sheet of assignments, one of people who have
    left. Written to a neighbouring temporary file and moved into place,
    so a reader never catches it half-written."""
    import os
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = lay_out(wb.active, COLUMNS, [row_values(r) for r in rows], "Laptops")

    # Status is the column people read first, so it carries its colour.
    status_col = [h for h, _ in COLUMNS].index("Status") + 1
    for n, row in enumerate(rows, start=2):
        cell = ws.cell(row=n, column=status_col)
        cell.font = Font(bold=True, color=STATUS_TEXT.get(row["status"], "000000"))
        cell.fill = PatternFill("solid", fgColor=STATUS_FILL.get(row["status"], "FFFFFF"))

    leavers = build_leavers(rows, departures or {})
    lay_out(wb.create_sheet(), LEAVER_COLUMNS,
            [leaver_values(r) for r in leavers], LEAVER_SHEET)

    path = str(path)
    tmp = f"{path}.tmp"
    wb.save(tmp)
    os.replace(tmp, path)
    return len(rows)
