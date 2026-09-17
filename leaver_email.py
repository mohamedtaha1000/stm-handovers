# -*- coding: utf-8 -*-
"""
leaver_email.py
===============
The two messages that go out when someone leaves, built from the same
records the handover documents were generated from.

Each message is written twice, from one description of what is in it.
Outlook, asked directly, takes an HTML body, so the employee details are
a table; a mailto: link can carry nothing but plain text, so the same
details are a bulleted list. Which one is used depends on how the
message is opened, and this module does not care which.

The wording is the team's own, kept as it was given. Two small things
were normalised: a stray double space after "Email:", and the missing
blank line under "Dear Team," in the resignation note. The department in
the resignation sentence is the employee's own rather than a fixed
"Development", since the same message is used for every department.

Everything is typed on the page rather than looked up: someone can leave
without ever having had a document generated for them, so requiring a
record on file would make the buttons useless exactly when they matter.

TOKENS is what lets the two links stay live as the boxes are typed in.
Each link is rendered once with a token where each value goes, and the
browser swaps the typed values in - so the message wording lives here,
in Python, and the page only does substitution. A link that reached
Outlook still carrying a token would be a bug, so the page substitutes
every token on every keystroke, empty values included.
"""

from html import escape

import email_html
from templates import DEPARTMENTS, EMPLOYEE_FIELDS_WITH_EMAIL

# What the page asks for, in the order it asks.
# The patterns come from the document forms rather than being written
# out again: the same two names, so the same two rules.
_NAME_RULES = {f["key"]: f for f in EMPLOYEE_FIELDS_WITH_EMAIL
               if f["key"] in ("name", "name_en")}

FORM_FIELDS = (
    {"key": "name", "label": "Full name (Arabic)",
     "placeholder": "محمد شعبان ابراهيم", "wide": True,
     "pattern": _NAME_RULES["name"]["pattern"],
     "pattern_msg": "This is the name the register matches on, and it is "
                    "Arabic on the documents — so Arabic letters only.",
     "hint": "Arabic"},
    # What the two emails call them, for the same reason the handover
    # notification uses it: the messages are in English.
    {"key": "name_en", "label": "Name in English",
     "placeholder": "Mohamed Shaban Ibrahim", "wide": True,
     "pattern": _NAME_RULES["name_en"]["pattern"],
     "pattern_msg": _NAME_RULES["name_en"]["pattern_msg"],
     "hint": "English"},
    # The employee code is what the rest of the app recognises a person
    # by, so asking for it here is what makes a resignation land on the
    # right person - and fills the column the sheet was leaving blank
    # for anyone with no documents behind them. Optional: someone can
    # leave without ever having been assigned one, or without whoever is
    # filling this in knowing it offhand.
    {"key": "code", "label": "Employee code", "placeholder": "10142",
     "optional": True, "hint": "optional"},
    {"key": "department", "label": "Department",
     "placeholder": "Pick one, or type a new one", "options": DEPARTMENTS},
    {"key": "email", "label": "Email", "placeholder": "asarour@stm.com.eg"},
    {"key": "computer_name", "label": "Computer name", "placeholder": "STM-LT-0142"},
    {"key": "serial", "label": "Serial number", "placeholder": "PK5PJ7T"},
)

FIELD_KEYS = tuple(f["key"] for f in FORM_FIELDS)
TOKENS = {key: f"__{key.upper()}__" for key in FIELD_KEYS}

# Everything but the code has to be there before the buttons light up or
# the register accepts the post. The code is the one box that can stay
# blank - not everyone has one to hand - so it is carved out here rather
# than checked field-by-field wherever FORM_FIELDS is walked for that.
OPTIONAL_KEYS = tuple(f["key"] for f in FORM_FIELDS if f.get("optional"))
REQUIRED_FIELDS = tuple(f for f in FORM_FIELDS if f["key"] not in OPTIONAL_KEYS)

# The department is named twice in the resignation note - once in the
# sentence, once in the details - and the sentence has to lose its whole
# clause when there is no department rather than read "from the
# department". So the clause gets a token of its own, and this is the
# shape the page fills in: its wording stays here rather than in the
# browser.
CLAUSE_TOKEN = "__DEPT_CLAUSE__"
CLAUSE_TEMPLATE = f" from the {TOKENS['department']} department"

# The lines both messages share, in the order the team writes them. The
# employee code sits right after the name, matching where it is asked for
# on the form; it prints blank rather than disappearing when nobody typed
# one, same as every other detail here.
DETAIL_LINES = (
    ("Name", "name_en"),
    ("Employee Code", "code"),
    ("Department", "department"),
    ("Email", "email"),
    ("Computer Name", "computer_name"),
    ("Serial Number", "serial"),
)


def detail_rows(person):
    """The details as (label, value) pairs.

    One description of what the details ARE, so the bulleted list and the
    table are two renderings of the same thing and cannot drift apart.
    Every pair is present even when its value is missing: these go to a
    team that reads the same lines every time, and a gap is a clearer
    prompt to fill something in than a silently absent row.
    """
    return [(label, (person.get(key) or "").strip())
            for label, key in DETAIL_LINES]


def detail_block(person):
    """The details as bullets, for the plain-text body."""
    return [f"* {label}: {value}" for label, value in detail_rows(person)]


def dept_clause(department):
    """" from the Technical Office department", or nothing at all."""
    value = (department or "").strip()
    return CLAUSE_TEMPLATE.replace(TOKENS["department"], value) if value else ""


def person_name(person):
    """What the messages call them: the English name, with the Arabic one
    behind it for anyone recorded before that box existed."""
    return ((person.get("name_en") or "").strip()
            or (person.get("name") or "").strip())


def ems_subject(person):
    return f"EMS deactivation — {person_name(person)}".strip(" —")


def ems_body(person):
    return "\n".join([
        "Dear Team,",
        "",
        "Kindly provide the FortiClient deactivation code.",
        "",
        "Employee Details:",
        "",
        *detail_block(person),
        "",
        "Your support is highly appreciated.",
    ])


def resignation_subject(person):
    return f"Resignation — {person_name(person)}".strip(" —")


def resignation_body(person):
    name = person_name(person)
    where = person.get("dept_clause")
    if where is None:
        where = dept_clause(person.get("department"))
    return "\n".join([
        "Dear Team,",
        "",
        f"I would like to inform you that the employee {name}{where} "
        f"has left the company.",
        "",
        "Employee Details:",
        "",
        *detail_block(person),
    ])


# ---------------------------------------------------------------- HTML
#
# Outlook, asked directly, takes an HTML body - so the details can be a
# ruled table instead of a bulleted list. A mailto: link cannot carry
# anything but plain text, so both renderings are kept: same words, same
# order, same rows, and the plain one is what the fallback links and any
# other mail client get.
#
# How a table LOOKS is not decided here: email_html renders every
# message this app sends, so they all look like they came from the same
# place.

def detail_table(person):
    """The details as a two-column table: label, then value."""
    return email_html.table(detail_rows(person))


def ems_html(person):
    return "".join([
        email_html.paragraph("Dear Team,"),
        email_html.paragraph("Kindly provide the FortiClient deactivation code."),
        email_html.section("Employee Details:", detail_rows(person)),
        email_html.paragraph("Your support is highly appreciated."),
    ])


def resignation_html(person):
    name = escape(person_name(person))
    where = person.get("dept_clause")
    if where is None:
        where = dept_clause(person.get("department"))
    return "".join([
        email_html.paragraph("Dear Team,"),
        email_html.paragraph(
            f"I would like to inform you that the employee <b>{name}</b>"
            f"{escape(where)} has left the company."),
        email_html.section("Employee Details:", detail_rows(person)),
    ])

# What each button sends, so the route and the page can loop over one
# list instead of repeating themselves per message.
MESSAGES = (
    {
        "key": "ems",
        "label": "EMS deactivation",
        "hint": "Asks for the FortiClient deactivation code",
        "subject": ems_subject,
        "body": ems_body,
        "html": ems_html,
    },
    {
        "key": "resignation",
        "label": "Resignation",
        "hint": "Tells the team the employee has left",
        "subject": resignation_subject,
        "body": resignation_body,
        "html": resignation_html,
    },
)
