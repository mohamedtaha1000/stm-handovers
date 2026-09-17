#!/usr/bin/env python3
"""
routes/documents.py
=====================
The document-generation side of the app: the home page/picker, making
one document or several at once, correcting one already made, History
(search, download, regenerate, delete), the laptop register downloads,
and the "tell the asset owner" notification email.

Not a Blueprint, and routes are registered directly on the shared `app`
object - see routes/auth.py's module docstring for why.
"""

import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlencode

from flask import (
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

import notify_email
import settings
from app import app
from documents import (
    batch_records,
    collect_values,
    display_filename,
    form_data_from_record,
    generated_filename,
    rebuild_document,
    scoped_form,
    stamp_record,
    write_document,
)
from employees import (
    equipment_summary,
    find_duplicate,
    known_employees,
    matches_query,
    register_rows,
)
from models import Handover, db
from routes.auth import admin_required, login_required
from routes.common import open_drafts_here, refresh_register, register_updated
from templates import EMPLOYEE_KEYS, TEMPLATE_GROUPS, TEMPLATES, all_fields

FILENAME_UNSAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# ----------------------------------------------------------------------
# Template picker (home page)
# ----------------------------------------------------------------------

@app.route("/")
@login_required
def index():
    # ?employee=<record id> carries "another document for this person"
    # through the picker, so whichever type is chosen next opens with the
    # employee half already filled in.
    return render_template(
        "picker.html", templates=TEMPLATES, groups=grouped_templates(),
        employee=request.args.get("employee"),
    )


def grouped_templates() -> list[tuple[str, list[tuple[str, dict[str, Any]]]]]:
    """The ten document types arranged for the picker, in group order."""
    groups: list[tuple[str, list[tuple[str, dict[str, Any]]]]] = []
    for name in TEMPLATE_GROUPS:
        members = [(tid, spec) for tid, spec in TEMPLATES.items()
                   if spec.get("group") == name]
        if members:
            groups.append((name, members))
    # A type whose group was mistyped still has to appear somewhere.
    loose = [(tid, spec) for tid, spec in TEMPLATES.items()
             if spec.get("group") not in TEMPLATE_GROUPS]
    if loose:
        groups.append(("Other", loose))
    return groups


def active_filters(
    q: str, type_filter: str, date_from: str, date_to: str
) -> list[dict[str, str]]:
    """The filters currently narrowing the history, each as a label plus
    the query string that removes just that one - so they can be read back
    in words and cleared individually."""
    current = {"q": q, "type": type_filter, "from": date_from, "to": date_to}
    chips: list[dict[str, str]] = []
    def add(key: str, label: str) -> None:
        remaining = {k: v for k, v in current.items() if v and k != key}
        chips.append({"label": label, "remove": url_for("history", **remaining)})
    if q:
        add("q", f'"{q}"')
    if type_filter and type_filter in TEMPLATES:
        add("type", TEMPLATES[type_filter]["label"])
    if date_from and date_to:
        chips.append({"label": f"{date_from} to {date_to}",
                      "remove": url_for("history", **{k: v for k, v in current.items()
                                                      if v and k not in ("from", "to")})})
    elif date_from:
        add("from", f"from {date_from}")
    elif date_to:
        add("to", f"until {date_to}")
    return chips


@app.route("/api/employees")
@login_required
def api_employees():
    """Feeds the "reuse a previous employee" suggestions on the form."""
    query = request.args.get("q", "").strip().lower()
    people = known_employees()
    if query:
        people = [p for p in people if matches_query(p, query)]
    return {"employees": people[:8]}


# ----------------------------------------------------------------------
# Shared form handling
#
# Creating a document and correcting one are the same job apart from what
# happens at the end, so both routes go through the helpers below rather
# than each carrying their own copy of the rules. That matters more than
# it saves typing: a validation rule or a normalisation that lived in
# only one of the two would mean a value the form rejects on the way in
# could still be edited back in afterwards.
# ----------------------------------------------------------------------

def save_document(
    template_id: str,
    values: dict[str, str],
    fill_data: dict[str, Any],
    date_obj: datetime,
    record: Handover | None = None,
) -> tuple[Handover | None, str | None]:
    """Generate the .docx and store it, as one step.

    Returns (record, problem). `problem` is a sentence to show the person
    and means nothing was saved - the file is written before the row is
    touched, so a template that fails to fill cannot leave a row pointing
    at a document that was never made.

    Pass `record` to regenerate an existing one; leave it out to make a
    new one.
    """
    editing = record is not None
    internal_name = generated_filename(
        template_id, values["name"], date_obj,
        exclude=record.filename if editing else None)

    problem = write_document(template_id, fill_data, internal_name)
    if problem:
        return None, problem

    if editing:
        # The old file is only removed once the new one exists, and only
        # if the name actually changed.
        if record.filename and record.filename != internal_name:
            old_file = settings.GENERATED_DIR / record.filename
            if old_file.exists():
                old_file.unlink()
        stamp_record(record, template_id, values, fill_data, date_obj, internal_name)
        record.updated_by = session.get("display_name", "-")
        record.updated_at = datetime.utcnow()
    else:
        record = stamp_record(Handover(), template_id, values, fill_data,
                              date_obj, internal_name)
        record.created_by = session.get("display_name", "-")
        record.created_by_user_id = session.get("user_id")
        db.session.add(record)

    db.session.commit()
    register_updated()
    return record, None


def render_form(
    template_id: str,
    data: Mapping[str, Any],
    record: Handover | None = None,
    duplicate: Handover | None = None,
) -> str:
    spec = TEMPLATES[template_id]
    return render_template(
        "form.html", spec=spec, template_id=template_id,
        data=data, today=date.today().isoformat(), record=record,
        duplicate=duplicate,
    )


# ----------------------------------------------------------------------
# Create a document
# ----------------------------------------------------------------------

@app.route("/new/<template_id>", methods=["GET", "POST"])
@login_required
def new_document(template_id: str):
    spec = TEMPLATES.get(template_id)
    if spec is None:
        abort(404)

    if request.method == "POST":
        values, fill_data, date_obj, errors = collect_values(template_id, request.form)
        if errors:
            for message in errors:
                flash(message, "error")
            return render_form(template_id, request.form)

        # Stored on disk under a human-readable, collision-safe name (see
        # generated_filename()) so the generated/ folder is browsable on
        # its own - e.g. "Yasmin Mohamed - Laptop Handover - 2026-09-10.docx".
        # The name a person sees when they download from the site is
        # computed separately in display_filename() and can differ (it
        # follows STM's Arabic document-naming convention).
        # Ask once before making a second document of the same type for
        # the same person. The answer travels back in a hidden field, so
        # confirming doesn't lose anything already typed.
        if not request.form.get("confirm_duplicate"):
            duplicate = find_duplicate(template_id, values)
            if duplicate is not None:
                return render_form(template_id, request.form, duplicate=duplicate)

        record, problem = save_document(template_id, values, fill_data, date_obj)
        if problem:
            flash(problem, "error")
            return render_form(template_id, request.form)

        return redirect(url_for("done", record_id=record.id))

    # "Another document for this person" arrives as ?employee=<record id>,
    # which pre-fills the employee half of the form and leaves the
    # equipment half empty.
    prefill = {}
    source_id = request.args.get("employee")
    if source_id:
        source = db.session.get(Handover, source_id)
        if source is not None:
            fields = source.fields
            prefill = {k: fields.get(k, "") for k in EMPLOYEE_KEYS if fields.get(k)}
            prefill.setdefault("name", source.name or "")
            prefill.setdefault("department", source.department or "")
            prefill.setdefault("role", source.role or "")
            prefill.setdefault("govid", source.govid or "")
            for f in all_fields(template_id):
                suffix = f.get("suffix")
                value = prefill.get(f["key"], "")
                if suffix and isinstance(value, str) and value.endswith(suffix):
                    prefill[f["key"]] = value[: -len(suffix)]
    return render_form(template_id, prefill)


# ----------------------------------------------------------------------
# Correct a document that has already been generated
#
# Re-generates the .docx in place rather than adding a second one: a
# correction is the same handover, not a new one, so the record keeps a
# single current document and the history keeps a single row. The old
# file is removed when the correction changes the employee name or the
# date, since those are what the filename is built from.
# ----------------------------------------------------------------------

@app.route("/edit/<string:record_id>", methods=["GET", "POST"])
@admin_required
def edit_document(record_id: str):
    record = Handover.query.get_or_404(record_id)
    template_id = record.template_id
    if template_id not in TEMPLATES:
        flash("That document was made from a template this site no longer has.", "error")
        return redirect(url_for("history"))

    if request.method == "POST":
        # What this document already says is allowed to stay, so a record
        # made before a list was closed is still editable.
        values, fill_data, date_obj, errors = collect_values(
            template_id, request.form, existing=record.fields)
        if errors:
            for message in errors:
                flash(message, "error")
            return render_form(template_id, request.form, record=record)

        record, problem = save_document(template_id, values, fill_data, date_obj,
                                        record=record)
        if problem:
            flash(problem, "error")
            return render_form(template_id, request.form, record=record)

        flash(f"Saved. The document for {record.name} has been generated again.", "success")
        return redirect(url_for("done", record_id=record.id))

    return render_form(template_id, form_data_from_record(record), record=record)


# ----------------------------------------------------------------------
# Several documents for one person, in one pass
#
# A new joiner typically collects a laptop, a mouse, a keyboard and a
# headset on their first morning - four documents whose employee half is
# identical. This collects that half once and each piece of equipment
# separately, then generates the lot.
#
# Device fields are namespaced per template ("headset_handover__model")
# because the templates genuinely collide: nearly all of them ask for a
# "model", "serial" and "color", and without the prefix the headset's
# serial would overwrite the laptop's.
# ----------------------------------------------------------------------

@app.route("/new", methods=["POST"])
@login_required
def new_batch_start():
    """Picker -> combined form. A single tick just goes to the normal
    one-document form, which is a better page for that job."""
    chosen = [t for t in request.form.getlist("template_id") if t in TEMPLATES]
    if not chosen:
        flash("Pick at least one document to create.", "error")
        return redirect(url_for("index"))
    employee = request.args.get("employee")
    if len(chosen) == 1:
        return redirect(url_for("new_document", template_id=chosen[0], employee=employee))
    return redirect(url_for("new_batch", types=",".join(chosen), employee=employee))


@app.route("/new-batch", methods=["GET", "POST"])
@login_required
def new_batch():
    chosen = [t for t in request.values.get("types", "").split(",") if t in TEMPLATES]
    if len(chosen) < 2:
        return redirect(url_for("index"))

    def show(
        data: Mapping[str, Any],
        duplicates: dict[str, Handover] | None = None,
        per_template_errors: dict[str, list[str]] | None = None,
    ) -> str:
        return render_template(
            "batch_form.html", chosen=chosen, templates=TEMPLATES,
            data=data, today=date.today().isoformat(),
            types=",".join(chosen), duplicates=duplicates or {},
            errors=per_template_errors or {},
        )

    if request.method == "POST":
        collected: dict[str, tuple[dict[str, str], dict[str, Any], datetime]] = {}
        errors: dict[str, list[str]] = {}
        duplicates: dict[str, Handover] = {}
        for template_id in chosen:
            values, fill_data, date_obj, problems = collect_values(
                template_id, scoped_form(template_id, request.form))
            if problems:
                errors[template_id] = problems
            collected[template_id] = (values, fill_data, date_obj)
            if not request.form.get("confirm_duplicate"):
                found = find_duplicate(template_id, values)
                if found is not None:
                    duplicates[template_id] = found

        if errors:
            # The employee half is shared, so the same missing name would
            # otherwise be reported once per document.
            seen = set()
            for problems in errors.values():
                for message in problems:
                    if message not in seen:
                        seen.add(message)
                        flash(message, "error")
            return show(request.form, duplicates=None, per_template_errors=errors)
        if duplicates:
            return show(request.form, duplicates=duplicates)

        # Each document is saved as it is made, rather than all of them at
        # the end. It means a batch that fails on its third document
        # keeps the first two - file and row together - instead of
        # leaving two .docx files on disk that no record points at, which
        # is what the single commit at the end used to do. The person is
        # told exactly where it stopped so they can finish the rest.
        created: list[str] = []
        for template_id in chosen:
            values, fill_data, date_obj = collected[template_id]
            record, problem = save_document(template_id, values, fill_data, date_obj)
            if problem:
                flash(problem, "error")
                if created:
                    done = ", ".join(TEMPLATES[t]["label"] for t in chosen[:len(created)])
                    flash(f"{len(created)} of {len(chosen)} were made and saved "
                          f"({done}). Only the rest still need doing.", "info")
                return show(request.form)
            created.append(record.id)
        return redirect(url_for("done_batch", ids=",".join(str(i) for i in created)))

    prefill = {}
    source_id = request.args.get("employee")
    if source_id:
        source = db.session.get(Handover, source_id)
        if source is not None:
            fields = source.fields
            prefill = {k: fields.get(k, "") for k in EMPLOYEE_KEYS if fields.get(k)}
            if prefill.get("email", "").endswith("@stm.com.eg"):
                prefill["email"] = prefill["email"].split("@")[0]
    return show(prefill)


@app.route("/done-batch")
@login_required
def done_batch():
    records = batch_records(request.args.get("ids", ""))
    if not records:
        return redirect(url_for("history"))
    return render_template("done_batch.html", records=records,
                           ids=request.args.get("ids", ""),
                           # What each document actually handed over, so
                           # the list reads as equipment rather than as
                           # ten repetitions of the same date.
                           equipment={r.id: equipment_summary(r) for r in records},
                           mailto=mailto_link(records))


@app.route("/files.zip")
@login_required
def download_batch():
    """All of a batch's documents in one download, named the way a single
    download names them."""
    import zipfile
    from io import BytesIO

    from flask import send_file

    records = batch_records(request.args.get("ids", ""))
    if not records:
        abort(404)

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as bundle:
        used = set()
        for record in records:
            path = settings.GENERATED_DIR / record.filename
            if not path.exists():
                continue
            name = display_filename(record.template_id, record.name)
            # Two documents of the same type for the same person would
            # otherwise collide inside the zip and one would be lost.
            stem, n = name[:-5], 2
            while name in used:
                name = f"{stem} ({n}).docx"
                n += 1
            used.add(name)
            bundle.write(path, name)
    buf.seek(0)

    safe = FILENAME_UNSAFE_RE.sub("", records[0].name).strip() or "documents"
    return send_file(buf, as_attachment=True, download_name=f"{safe}.zip",
                     mimetype="application/zip")


# ----------------------------------------------------------------------
# Telling the asset owner
#
# A mailto: link rather than a file to download: one click opens Outlook's
# new-message window with the address, subject and details already in it,
# and the person sends it from their own mailbox. Plain text is all a
# mailto can carry - no ruled table, no attachment - which is the trade
# for not having to open a downloaded file first. notify_email lays the
# details out as labelled sections, which read the same in any font.
# ----------------------------------------------------------------------

# Outlook on Windows stops honouring a mailto around 2,000 characters.
# One handover encodes to well under half that even with an Arabic name;
# a batch of seven or more is what can reach it.
MAILTO_LIMIT = 1900


def build_mailto(records: list[Handover], detailed: list[Handover]) -> str:
    # No sender is passed and no sign-off is written: the draft opens in
    # whoever's Outlook clicked the link, and their own signature goes
    # under it.
    body = notify_email.build_body(
        records, greeting_name=settings.NOTIFY_NAME, detailed=detailed)
    query = urlencode({"subject": notify_email.subject_for(records), "body": body},
                      quote_via=quote)
    return (f"mailto:{quote(','.join(settings.addresses(settings.NOTIFY_TO)), safe='@.,')}"
            f"?{query}")


def mailto_link(records: list[Handover]) -> str | None:
    """The mailto: URL for these documents, or None if there is nothing to
    describe.

    A long batch loses detail blocks from the end until the URL fits -
    the message then names those items instead of describing them, which
    is better than handing the mail client a URL it cuts off mid-word.
    """
    if not records:
        return None
    link = build_mailto(records, records)
    detailed = list(records)
    while len(link) > MAILTO_LIMIT and len(detailed) > 1:
        detailed.pop()
        link = build_mailto(records, detailed)
    return link


@app.route("/done/<string:record_id>")
@login_required
def done(record_id: str):
    record = Handover.query.get_or_404(record_id)
    return render_template("done.html", record=record,
                           mailto=mailto_link([record]))


@app.route("/file/<string:record_id>")
@login_required
def get_file(record_id: str):
    record = Handover.query.get_or_404(record_id)
    file_path = settings.GENERATED_DIR / record.filename
    if not file_path.exists():
        abort(404)
    return send_from_directory(
        settings.GENERATED_DIR, record.filename,
        as_attachment=True, download_name=display_filename(record.template_id, record.name),
    )


@app.route("/history/<string:record_id>/regenerate", methods=["POST"])
@login_required
def regenerate_file(record_id: str):
    """Rebuild this record's .docx from what is stored on it, for when the
    file under generated/ has gone missing on its own - deleted from the
    folder by hand, or lost to an interrupted OneDrive sync - while the
    record itself is still on file.

    A deliberate action from History, not something that happens quietly
    on download: the row is found by searching, same as anything else
    here, and the button only appears once the file is confirmed missing."""
    record = Handover.query.get_or_404(record_id)
    problem = rebuild_document(record)
    if problem:
        flash(problem, "error")
    else:
        flash(f"The document for {record.name} has been recreated from its saved record.",
              "success")
    keep = {}
    for key in ("q", "type", "from", "to", "page"):
        val = request.form.get(key, "")
        if val:
            keep[key] = val
    return redirect(url_for("history", **keep))


# ----------------------------------------------------------------------
# History (search + permanent delete)
# ----------------------------------------------------------------------

HISTORY_PAGE_SIZE = 50


@app.route("/history")
@login_required
def history():
    q = request.args.get("q", "").strip()
    type_filter = request.args.get("type", "").strip()
    date_from = request.args.get("from", "").strip()
    date_to = request.args.get("to", "").strip()
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1

    query = Handover.query.order_by(Handover.created_at.desc())
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Handover.name.like(like),
                Handover.department.like(like),
                Handover.role.like(like),
            )
        )
    if type_filter and type_filter in TEMPLATES:
        query = query.filter(Handover.template_id == type_filter)
    # Date range filters on created_at (a real datetime column) rather
    # than handover_date (a free-form "D/M/YYYY" string the person typed
    # in the form, not reliably sortable/comparable) - this is "when the
    # document was generated", which is what a person browsing history
    # usually means by a date range anyway.
    if date_from:
        try:
            query = query.filter(Handover.created_at >= datetime.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            date_from = ""
    if date_to:
        try:
            end = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(Handover.created_at < end)
        except ValueError:
            date_to = ""

    total = query.count()
    pages = max(1, (total + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE)
    page = min(page, pages)
    records = query.offset((page - 1) * HISTORY_PAGE_SIZE).limit(HISTORY_PAGE_SIZE).all()

    return render_template(
        "history.html", records=records, q=q, type_filter=type_filter,
        date_from=date_from, date_to=date_to, templates=TEMPLATES,
        page=page, pages=pages, total=total, page_size=HISTORY_PAGE_SIZE,
        equipment={r.id: equipment_summary(r) for r in records},
        mailto={r.id: mailto_link([r]) for r in records},
        # So the row can offer "Regenerate" instead of "Download" for the
        # rare case where the .docx is gone from generated/ but the record
        # is not - lost from the folder some other way, since History's
        # own Delete removes both together.
        missing_file={r.id for r in records
                      if not (settings.GENERATED_DIR / r.filename).exists()},
        filters=active_filters(q, type_filter, date_from, date_to),
        matching=total,
        # `total` is what the current filters match; the heading wants the
        # size of the whole log, or it reads as though filtering deleted
        # everything else.
        grand_total=Handover.query.count(),
    )


def _filtered_history_query() -> Any:
    """Builds the same filtered (but unpaginated) query used by both the
    history page and the Excel export, so the two can never drift apart -
    whatever's currently filtered/searched on screen is exactly what gets
    exported."""
    q = request.args.get("q", "").strip()
    type_filter = request.args.get("type", "").strip()
    date_from = request.args.get("from", "").strip()
    date_to = request.args.get("to", "").strip()

    query = Handover.query.order_by(Handover.created_at.desc())
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Handover.name.like(like),
                Handover.department.like(like),
                Handover.role.like(like),
            )
        )
    if type_filter and type_filter in TEMPLATES:
        query = query.filter(Handover.template_id == type_filter)
    if date_from:
        try:
            query = query.filter(Handover.created_at >= datetime.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            pass
    if date_to:
        try:
            end = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            query = query.filter(Handover.created_at < end)
        except ValueError:
            pass
    return query


# ----------------------------------------------------------------------
# The laptop register
#
# A spreadsheet rebuilt from the database whenever anything changes, so
# it can never drift from the records behind it. See asset_register.py
# for the shape of it.
# ----------------------------------------------------------------------

def notify_draft(records: list[Handover]) -> dict[str, str]:
    """The handover notification, addressed and written out both ways.

    The plain text is trimmed to what a mailto: link can carry; this is
    not, because Outlook opened directly has no such limit. So the draft
    that opens here is the whole message, tables and all, even where the
    link would have had to leave equipment out.
    """
    return {"to": "; ".join(settings.addresses(settings.NOTIFY_TO)),
            "subject": notify_email.subject_for(records),
            "body": notify_email.build_body(records, settings.NOTIFY_NAME),
            "html": notify_email.build_html(records, settings.NOTIFY_NAME)}


@app.route("/notify/open", methods=["POST"])
@login_required
def open_notification():
    """Open the handover notification in Outlook itself.

    The page falls back to its own mailto: link when this says no, so a
    refusal is an answer rather than an error: the only real failure is
    being asked about documents that are not there.
    """
    wanted = [i for i in request.form.getlist("id") if i.strip()]
    records = (Handover.query.filter(Handover.id.in_(wanted)).all()
               if wanted else [])
    if not records:
        return {"opened": False,
                "reason": "Those documents could not be found."}, 404
    # Back into the order they were asked for, so the message reads the
    # way the page that asked for it does.
    records.sort(key=lambda r: wanted.index(r.id))
    opened, reason = open_drafts_here([notify_draft(records)])
    return {"opened": opened, "reason": reason}


@app.route("/register.xlsx")
@login_required
def download_register():
    """The file itself. It lives beside the app, but the app may be on a
    different machine from whoever wants to read it.

    Rebuilt before it is sent rather than only when missing. It used to
    only build the file if it was absent, which meant a register written
    by an older version of this app - a column short, or a sheet short -
    was handed over unchanged and looked like a bug in the app. If the
    rebuild fails because the file is open in Excel, the copy already on
    disk is sent instead: slightly stale beats nothing.
    """
    from flask import send_file
    problem = refresh_register()
    if problem and not settings.REGISTER_PATH.exists():
        flash(problem, "error")
        return redirect(url_for("history"))
    return send_file(
        settings.REGISTER_PATH, as_attachment=True,
        download_name=f"laptop-register-{date.today().isoformat()}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/register/rebuild", methods=["POST"])
@login_required
def rebuild_register():
    problem = refresh_register()
    if problem:
        flash(problem, "error")
    else:
        flash(f"Laptop register rebuilt — {len(register_rows())} assignments.",
              "success")
    return redirect(request.form.get("next") or url_for("history"))


@app.route("/delete/<string:record_id>", methods=["POST"])
@admin_required
def delete_history(record_id: str):
    record = Handover.query.get_or_404(record_id)
    file_path = settings.GENERATED_DIR / record.filename
    if file_path.exists():
        file_path.unlink()
    name = record.name
    db.session.delete(record)
    db.session.commit()
    register_updated()
    flash(f"Deleted the record for {name}, and its generated file.", "success")
    # Preserve whatever search/filter/page the delete was performed from,
    # so deleting a row from page 3 of a filtered view doesn't bounce the
    # person back to an unfiltered page 1.
    keep = {}
    for key in ("q", "type", "from", "to", "page"):
        val = request.form.get(key, "")
        if val:
            keep[key] = val
    return redirect(url_for("history", **keep))
