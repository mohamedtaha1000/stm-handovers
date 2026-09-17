#!/usr/bin/env python3
"""
routes/resignation.py
=======================
Someone is leaving: recording it, releasing their laptop in the
register, and the two emails that go with it (EMS deactivation,
resignation notice) - plus correcting a resignation record already on
file.

Every detail is typed on the page rather than looked up: people leave
who never had a document generated for them, and a page that could only
describe employees on file would be useless exactly when it was needed.

The form is plain GET, so it works with JavaScript off - the details
come back in the URL and the links are rebuilt server-side. With
JavaScript on, the links carry a token per field and are rewritten as
the boxes are typed, so the buttons are live and nothing has to be
submitted at all.

Not a Blueprint, and routes are registered directly on the shared `app`
object - see routes/auth.py's module docstring for why.
"""

import re
from datetime import date
from typing import Any
from urllib.parse import quote, urlencode

from flask import flash, redirect, render_template, request, session, url_for

import asset_register
import leaver_email
import settings
import templates
from app import app
from employees import (
    leaver_lookup,
    matches_query,
    matching_laptops,
    register_rows,
    typed_identity,
)
from models import Departure, db
from routes.auth import admin_required, login_required
from routes.common import open_drafts_here, refresh_register

# The two leaver addresses as one lookup, so a message can ask for its
# own recipient by name.
LEAVER_RECIPIENTS = {"ems": settings.EMS_TO, "resignation": settings.LEAVER_TO}


@app.route("/api/leavers")
@login_required
def api_leavers():
    """Feeds the suggestions on the leaver page. Deliberately a different
    endpoint from /api/employees: that one must never hand a serial
    number to a handover form, and this one exists to hand one over."""
    query = request.args.get("q", "").strip().lower()
    people = leaver_lookup()
    if query:
        people = [p for p in people if matches_query(p, query)]
    return {"employees": people[:8]}


def leaver_drafts(person: dict[str, Any]) -> list[dict[str, str]]:
    """The two messages, addressed and written out both ways, from one
    set of details. Everything that opens them starts here, so the
    wording cannot drift between the two: Outlook takes the HTML, where
    the details are a table, and a mailto: link takes the plain text,
    where they are bullets."""
    return [{"key": m["key"],
             # Outlook's own separator, whatever was typed in .env.
             "to": "; ".join(settings.addresses(LEAVER_RECIPIENTS.get(m["key"], ""))),
             "subject": m["subject"](person),
             "body": m["body"](person),
             "html": m["html"](person)}
            for m in leaver_email.MESSAGES]


def leaver_links(person: dict[str, Any]) -> dict[str, str]:
    """The same two messages as a mailto: each, for the page's fallback
    links and for browsers that have to open them one at a time."""
    return {d["key"]: "mailto:{}?{}".format(
                # A mailto: URL separates them with commas, not semicolons.
                quote(",".join(settings.addresses(d["to"])), safe="@.,"),
                urlencode({"subject": d["subject"], "body": d["body"]},
                          quote_via=quote))
            for d in leaver_drafts(person)}


def opened_in_outlook(typed: dict[str, str]) -> tuple[bool, str]:
    """The leaver page's own press: both drafts at once, but only when
    the page asked for it."""
    if request.form.get("open") != "outlook":
        return False, ""
    return open_drafts_here(leaver_drafts(typed))


@app.route("/api/holdings")
@login_required
def api_holdings():
    """What the leaver page shows under its two email buttons, refreshed
    as the boxes are typed."""
    rows = matching_laptops(request.args.get("name", ""),
                            request.args.get("serial", ""),
                            request.args.get("code", ""))
    return {
        "laptops": [{"model": r["model"], "serial": r["serial"],
                     "status": r["status"], "assigned_on": asset_register.show_date(r["date"]),
                     "assigned_by": r["by"], "name": r["name"]}
                    for r in rows],
        "open": sum(1 for r in rows if r["status"] == asset_register.HELD),
    }


@app.route("/resignation/record", methods=["POST"])
@login_required
def mark_left():
    """Close someone out: record that they have gone, and - when this
    machine can - open both drafts in Outlook from the same press."""
    # The page's own button asks for JSON: it stays where it is and shows
    # the answer, rather than navigating away to a redirect. The plain
    # form POST (no JavaScript) still gets the redirect and the flash.
    wants_json = request.form.get("format") == "json"

    # The page greys its buttons out until every detail is there. That is
    # a courtesy, not a guard: anything a browser enforces can be turned
    # off in the developer tools, and this request writes to the
    # register. So the same rule is checked here, where it cannot be
    # edited away, and the request is refused rather than half-applied.
    typed = {f["key"]: request.form.get(f["key"], "").strip()
             for f in leaver_email.FORM_FIELDS}
    missing = [f["label"] for f in leaver_email.REQUIRED_FIELDS if not typed[f["key"]]]
    # The two name boxes each refuse the other's script. Checked here as
    # well as in the browser, for the same reason everything else on this
    # page is: a pattern attribute can be deleted in the developer tools.
    wrong = [f["pattern_msg"] for f in leaver_email.FORM_FIELDS
             if f.get("pattern") and typed[f["key"]]
             and not re.fullmatch(f["pattern"], typed[f["key"]])]
    if wrong and not missing:
        message = "Nothing was changed: " + " ".join(wrong)
        if wants_json:
            return {"marked": 0, "message": message, "incomplete": wrong}, 400
        flash(message, "error")
        return redirect(url_for("resignation", **request.form.to_dict(flat=True)))
    if missing:
        # Counted rather than written out, so adding a field to the form
        # can never leave this sentence saying the wrong number.
        message = ("Nothing was changed: " + ", ".join(missing)
                   + (" is" if len(missing) == 1 else " are")
                   + f" still empty, and all {len(leaver_email.REQUIRED_FIELDS)} are "
                     "needed before anyone can be recorded as resigned.")
        if wants_json:
            return {"marked": 0, "message": message, "incomplete": missing}, 400
        flash(message, "error")
        return redirect(url_for("resignation", **request.form.to_dict(flat=True)))

    # The register first, Outlook second. Opening Outlook can take
    # seconds on a cold start and can go wrong in ways this app does not
    # control; the departure is the part that must survive either way.
    marked, message, problem = record_departure(typed)
    opened, reason = opened_in_outlook(typed)

    if wants_json:
        # "marked" is laptops moved and is often nought; "recorded" is
        # the person, and by this point always happened.
        return {"marked": marked, "recorded": True, "message": message,
                "problem": problem, "opened": opened, "reason": reason}
    if problem:
        flash(problem, "info")
    flash(message, "success")
    return redirect(url_for("resignation", **request.form.to_dict(flat=True)))


def record_departure(typed: dict[str, str]) -> tuple[int, str, str]:
    """Write the departure and rebuild the register around it. Returns
    (how many laptops moved, a sentence for whoever pressed the button,
    anything that went wrong writing the spreadsheet).

    Resigning is a fact about a PERSON, not about a laptop. Someone can
    leave who never had a document generated for them - a phone-only
    starter, someone who joined before this tool existed - and they
    belong on the resignation sheet exactly like anyone else. So the
    departure is always written; how many laptops it moved is a separate
    question, and often nought.

    It is filed against the identity the rest of the app uses, so it
    follows the person rather than one document: everything they were
    ever issued flips together, and a document generated for them later
    lands on the same person.
    """
    code = typed.get("code", "")
    rows = matching_laptops(typed["name"], typed["serial"], code)
    identities = {r["identity"] for r in rows} or {typed_identity(typed["name"], code)}
    name = rows[0]["name"] if rows else typed["name"]

    today = date.today()
    left_on = f"{today.day}/{today.month}/{today.year}"
    for identity in identities:
        gone = Departure.query.filter_by(identity=identity).first()
        if gone is None:
            gone = Departure(identity=identity)
            db.session.add(gone)
        gone.name = name
        # What was typed, kept for the people with no documents behind
        # them - without it their row on the sheet is a name and blanks.
        gone.code = code
        gone.name_en = typed.get("name_en", "")
        gone.department = typed.get("department", "")
        gone.email = typed.get("email", "")
        gone.left_on = left_on
        gone.recorded_by = session.get("display_name", "-")
        # Claimed once, kept afterwards - re-marking an already-recorded
        # departure (correcting a detail through this same flow) must
        # not silently hand it to whoever happens to press the button
        # this time.
        if gone.recorded_by_user_id is None:
            gone.recorded_by_user_id = session.get("user_id")
    db.session.commit()

    problem = refresh_register()
    if not rows:
        return 0, (f"{name} recorded as resigned. Nothing on file matches "
                   f"those details, so no laptop changed hands."), (problem or "")
    machines = ", ".join(f"{r['model']} ({r['serial']})" for r in rows if r["serial"])
    return len(rows), (f"{name} recorded as resigned. "
                       f"{len(rows)} laptop{'' if len(rows) == 1 else 's'} in the "
                       f"register released{': ' + machines if machines else ''}."), \
           (problem or "")


@app.route("/leaver")
@login_required
def leaver():
    """The page's old address. Kept so a bookmark or a link somebody
    pasted into a message still lands somewhere."""
    return redirect(url_for("resignation", **request.args), code=301)


@app.route("/resignation")
@login_required
def resignation():
    typed = {f["key"]: request.args.get(f["key"], "").strip()
             for f in leaver_email.FORM_FIELDS}
    return render_template(
        "leaver.html",
        fields=leaver_email.FORM_FIELDS, typed=typed,
        holdings=matching_laptops(typed.get("name", ""), typed.get("serial", "")),
        messages=leaver_email.MESSAGES,
        # Tidied for reading: whatever separator was typed in .env, the
        # page shows one comma-spaced list.
        recipients={key: ", ".join(settings.addresses(raw))
                    for key, raw in LEAVER_RECIPIENTS.items()},
        links=leaver_links(typed),
        # The same two links with a token wherever a value goes, for the
        # browser to fill in as the boxes are typed.
        token_links=leaver_links({**leaver_email.TOKENS,
                                  "dept_clause": leaver_email.CLAUSE_TOKEN}),
        tokens=leaver_email.TOKENS,
        optional_keys=leaver_email.OPTIONAL_KEYS,
        clause_token=leaver_email.CLAUSE_TOKEN,
        clause_template=leaver_email.CLAUSE_TEMPLATE,
        recorded=departure_rows(),
    )


# The details a resignation record keeps, in the order the page asks for
# them. Separate from leaver_email.FORM_FIELDS because that list is about
# writing the two emails - this one is about correcting a record that has
# already been written, so it has the date and not the equipment.
DEPARTURE_FIELDS = (
    {"key": "name", "label": "Full name (Arabic)", "hint": "Arabic"},
    {"key": "name_en", "label": "Name in English", "hint": "English"},
    {"key": "code", "label": "Employee code"},
    {"key": "department", "label": "Department", "options": templates.DEPARTMENTS},
    {"key": "email", "label": "Email"},
    {"key": "left_on", "label": "Left on", "placeholder": "16/9/2026"},
)
# The two names keep the rules the rest of the app uses for them.
for _f in DEPARTURE_FIELDS:
    _rule = {x["key"]: x for x in templates.EMPLOYEE_FIELDS_WITH_EMAIL}.get(_f["key"])
    if _rule and _rule.get("pattern"):
        _f["pattern"] = _rule["pattern"]
        _f["pattern_msg"] = _rule["pattern_msg"]


def departure_rows() -> list[dict[str, Any]]:
    """Every recorded resignation, newest first, with where each one's
    details actually come from.

    A person who has handover documents on file is described BY those
    documents on the register, so correcting their name means correcting
    the document - fixing the resignation record would change nothing
    anyone can see. The list says which of the two it is rather than
    letting someone edit the wrong one.
    """
    by_identity: dict[str, list[dict[str, Any]]] = {}
    for row in register_rows():
        by_identity.setdefault(row["identity"], []).append(row)
    out: list[dict[str, Any]] = []
    for gone in Departure.query.all():
        mine = by_identity.get(gone.identity, [])
        newest = max(mine, key=lambda r: (r["sort_date"] or date.min, r["record_id"]),
                     default=None)
        out.append({
            "id": gone.id,
            "identity": gone.identity,
            "name": (newest or {}).get("name") or gone.name or "",
            "name_en": (newest or {}).get("name_en") or gone.name_en or "",
            "code": (newest or {}).get("code") or gone.code or "",
            "department": (newest or {}).get("department") or gone.department or "",
            "email": (newest or {}).get("email") or gone.email or "",
            "left_on": gone.left_on or "",
            "by": gone.recorded_by or "",
            "from_document": newest["record_id"] if newest else None,
            "laptops": len(mine),
        })
    out.sort(key=lambda r: (asset_register.parse_date(r["left_on"]) or date.min,
                            r["name"]), reverse=True)
    return out


@app.route("/resignation/<string:departure_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_departure(departure_id: str):
    """Correct a recorded resignation.

    The register is a report, not a record: it is rewritten from this
    database every time anything changes, so a correction typed into the
    spreadsheet is gone by the next document. This is where it sticks.
    """
    gone = Departure.query.get_or_404(departure_id)

    if request.method == "POST":
        typed = {f["key"]: request.form.get(f["key"], "").strip()
                 for f in DEPARTURE_FIELDS}
        errors = [f["pattern_msg"] for f in DEPARTURE_FIELDS
                  if f.get("pattern") and typed[f["key"]]
                  and not re.fullmatch(f["pattern"], typed[f["key"]])]
        if not typed["name"] and not typed["name_en"]:
            errors.append("A resignation needs a name, in one script or the other.")

        # The employee code is the identity. Changing it moves the record
        # onto a different person, so it must not land on one that is
        # already there.
        wanted = typed_identity(typed["name"], typed["code"])
        clash = (Departure.query.filter_by(identity=wanted).first()
                 if wanted and wanted != gone.identity else None)
        if clash is not None:
            errors.append(f"{clash.name or wanted} is already recorded as resigned "
                          f"under that code, so this one cannot take it too.")
        if errors:
            for message in errors:
                flash(message, "error")
            return render_template("departure_edit.html", fields=DEPARTURE_FIELDS,
                                   typed=typed, gone=gone)

        for key, value in typed.items():
            setattr(gone, key, value)
        if wanted:
            gone.identity = wanted
        gone.recorded_by = session.get("display_name", "-")
        if gone.recorded_by_user_id is None:
            gone.recorded_by_user_id = session.get("user_id")
        db.session.commit()
        problem = refresh_register()
        if problem:
            flash(problem, "info")
        flash(f"{gone.name_en or gone.name} updated on the resignation sheet.",
              "success")
        return redirect(url_for("resignation"))

    return render_template("departure_edit.html", fields=DEPARTURE_FIELDS,
                           typed={f["key"]: getattr(gone, f["key"], "") or ""
                                  for f in DEPARTURE_FIELDS},
                           gone=gone)


@app.route("/resignation/<string:departure_id>/remove", methods=["POST"])
@admin_required
def remove_departure(departure_id: str):
    """Take somebody off the resignation sheet - because they were
    recorded by mistake, or twice. Anything they were holding goes back
    to Held, since the only reason it said Left was this record."""
    gone = Departure.query.get_or_404(departure_id)
    who = gone.name_en or gone.name or gone.identity
    db.session.delete(gone)
    db.session.commit()
    problem = refresh_register()
    if problem:
        flash(problem, "info")
    flash(f"{who} taken off the resignation sheet. Anything they held is "
          f"back to Held in the register.", "success")
    return redirect(url_for("resignation"))
