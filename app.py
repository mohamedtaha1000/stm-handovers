#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
STM Handover Documents — web app
==================================
A small internal Flask site that fills STM's handover/receipt Word
documents from a web form instead of the command line, and keeps a
searchable, deletable history of every document it has generated.

Supports multiple document templates (laptop handover, laptop
replacement, keyboard/mouse receipt, screen handover, ...) - see
templates.py's TEMPLATES registry, which is the single source of truth
for what documents exist and what fields each one's form collects. Adding
a new document type later means adding one entry there plus a .docx file
in doc_templates/ - nothing in this file needs to change.

Run locally:
    pip install -r requirements.txt
    python app.py
    -> open http://127.0.0.1:5000

See README.md for environment variables and deployment notes.
"""

import json
import os
import re
import secrets
from datetime import datetime, date, timedelta
from functools import wraps
from urllib.parse import quote, urlencode
from pathlib import Path

from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, send_from_directory, flash, abort,
)
from werkzeug.security import check_password_hash, generate_password_hash

from templates import (
    EMPLOYEE_KEYS, TEMPLATES, TEMPLATE_GROUPS,
    all_fields, required_field_keys, template_path,
)
import builders
import notify_email
import leaver_email
import outlook_com
import asset_register
import documents
import employees
import settings
import templates
from documents import (
    batch_records, collect_values, display_filename, form_data_from_record,
    generated_filename, rebuild_document, scoped_form, stamp_record, write_document,
)
from employees import (
    departures_by_identity, employee_identity, equipment_summary, find_duplicate,
    known_employees, leaver_lookup, matching_laptops, register_rows,
    typed_identity,
)
from models import Handover, Departure, User, create_all_and_migrate, db

app = Flask(__name__)

# Everything configurable lives in settings.py. Read through the module
# (settings.X) rather than importing the names, so a test that points the
# app at a temporary folder is actually seen by the code that writes
# there.
app.config["SECRET_KEY"] = settings.SECRET_KEY or secrets.token_hex(32)
app.config["SQLALCHEMY_DATABASE_URI"] = settings.DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# The two leaver addresses as one lookup, so a message can ask for its
# own recipient by name. Built here rather than in settings.py because
# it pairs a setting with a message key, which is an app-level idea.
LEAVER_RECIPIENTS = {"ems": settings.EMS_TO, "resignation": settings.LEAVER_TO}

db.init_app(app)
with app.app_context():
    create_all_and_migrate()


@app.context_processor
def notify_details():
    """Who the handover email goes to, available to every template so the
    buttons and the optional section can name them rather than saying
    "the asset owner"."""
    return {"notify_name": settings.NOTIFY_NAME, "notify_to": settings.NOTIFY_TO}


@app.template_filter("initials")
def initials(value):
    """One or two initials for the topbar badge. Takes the first letter
    of the first and last word, which works for an Arabic name as well as
    a Latin one."""
    parts = [p for p in str(value or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


@app.template_filter("mask_id")
def mask_id(value):
    """Show only the last 4 characters of a sensitive value (national ID)
    in list views, so it isn't fully exposed to everyone who can see the
    history page. The full value is still in the generated .docx and on
    the confirmation page right after creating it."""
    if not value:
        return ""
    value = str(value)
    if len(value) <= 4:
        return "•" * len(value)
    return "•" * (len(value) - 4) + value[-4:]


# ----------------------------------------------------------------------
# Auth - individual accounts, two roles (Admin, Staff)
#
# Only an Admin can create an account (from /admin/users), and every
# account they create - or reset - starts with the same fixed password
# (settings.DEFAULT_USER_PASSWORD), never one the Admin makes up per
# person. must_change_password is what turns that shared starting
# password into something only the account holder knows, before they
# can do anything else at all.
# ----------------------------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        # Nothing else works until this is cleared - a forced stop, not
        # a suggestion, since the account's password is still the one
        # every other new account also starts with.
        if (session.get("must_change_password")
                and request.endpoint not in ("change_password", "logout")):
            return redirect(url_for("change_password"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        if (session.get("must_change_password")
                and request.endpoint not in ("change_password", "logout")):
            return redirect(url_for("change_password"))
        if session.get("role") != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def is_owner_or_admin(owner_user_id):
    """Whether the signed-in person may act on a record with this owner.

    An Admin may act on anything. Otherwise the record needs a verified
    owner (see Handover.created_by_user_id's docstring) that matches
    the signed-in account - a record with no owner at all (made before
    accounts existed) belongs to nobody until an Admin claims it via the
    edit form's "Owner account" field, so it can never match a Staff
    member by accident."""
    if session.get("role") == "admin":
        return True
    return owner_user_id is not None and owner_user_id == session.get("user_id")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        # One message for "no such account", "wrong password", and
        # "deactivated" alike - which of the three it was is not
        # something a login form should ever confirm to whoever is
        # typing.
        if (not username or not password or user is None
                or not user.is_active
                or not check_password_hash(user.password_hash, password)):
            error = "Wrong username or password"
        else:
            session["logged_in"] = True
            session["user_id"] = user.id
            session["role"] = user.role
            session["display_name"] = user.display_name
            session["must_change_password"] = user.must_change_password
            nxt = request.args.get("next") or url_for("index")
            return redirect(nxt)
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/account/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    error = None
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        user = User.query.get(session["user_id"])
        if not check_password_hash(user.password_hash, current):
            error = "Current password is wrong."
        elif len(new) < 8:
            error = "New password must be at least 8 characters."
        elif new != confirm:
            error = "New password and confirmation don't match."
        elif check_password_hash(user.password_hash, new):
            error = "That's your current password - pick a different one."
        else:
            user.password_hash = generate_password_hash(new)
            user.must_change_password = False
            db.session.commit()
            session["must_change_password"] = False
            flash("Password changed.", "success")
            return redirect(url_for("index"))
    return render_template(
        "change_password.html", error=error,
        forced=session.get("must_change_password", False),
    )


@app.errorhandler(403)
def forbidden(_error):
    # A plain redirect, not a 403 response with a Location header - a
    # browser only follows a Location header on a 3xx status, so keeping
    # the 403 here would leave the tab stuck on an error page instead of
    # actually landing back in the app.
    flash("You don't have permission to do that.", "error")
    return redirect(url_for("index"))


# ----------------------------------------------------------------------
# Manage users (Admin only)
#
# The only way an account is ever created. Every new or reset account
# gets the same fixed starting password (settings.DEFAULT_USER_PASSWORD)
# rather than one an Admin makes up per person - see the auth section
# above for why.
# ----------------------------------------------------------------------

@app.route("/admin/users")
@admin_required
def admin_users():
    return render_template(
        "admin_users.html",
        users=User.query.order_by(User.username).all(),
        default_password=settings.DEFAULT_USER_PASSWORD,
    )


@app.route("/admin/users", methods=["POST"])
@admin_required
def admin_users_create():
    username = request.form.get("username", "").strip().lower()
    display_name = request.form.get("display_name", "").strip()
    role = request.form.get("role", "staff").strip().lower()

    if not username or not display_name:
        flash("A username and a display name are both needed.", "error")
    elif role not in ("admin", "staff"):
        flash("Not a real role.", "error")
    elif User.query.filter_by(username=username).first() is not None:
        flash(f'The username "{username}" is already taken.', "error")
    else:
        db.session.add(User(
            username=username, display_name=display_name, role=role,
            password_hash=generate_password_hash(settings.DEFAULT_USER_PASSWORD),
        ))
        db.session.commit()
        flash(f'{display_name} can now sign in as "{username}" with the '
              f"starting password {settings.DEFAULT_USER_PASSWORD} - they'll "
              f"be asked to change it the moment they log in.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/role", methods=["POST"])
@admin_required
def admin_users_role(user_id):
    user = User.query.get_or_404(user_id)
    role = request.form.get("role", "").strip().lower()
    if role not in ("admin", "staff"):
        flash("Not a real role.", "error")
    elif role != "admin" and user.role == "admin" and _last_active_admin(user):
        flash(f"{user.display_name} is the only active Admin - promote someone "
              f"else first.", "error")
    else:
        user.role = role
        db.session.commit()
        flash(f"{user.display_name} is now {role}.", "success")
    return redirect(url_for("admin_users"))


def _last_active_admin(user):
    """Whether `user` is the only active Admin left - used to block the
    one action (demoting or deactivating them) that would leave nobody
    able to manage accounts at all."""
    return (User.query.filter_by(role="admin", is_active=True).count() <= 1
            and user.is_active and user.role == "admin")


@app.route("/admin/users/<int:user_id>/deactivate", methods=["POST"])
@admin_required
def admin_users_deactivate(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == session.get("user_id"):
        flash("You can't deactivate your own account.", "error")
    elif _last_active_admin(user):
        flash(f"{user.display_name} is the only active Admin - there would be "
              f"nobody left to manage accounts.", "error")
    else:
        user.is_active = False
        db.session.commit()
        flash(f"{user.display_name} can no longer sign in.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/reactivate", methods=["POST"])
@admin_required
def admin_users_reactivate(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = True
    db.session.commit()
    flash(f"{user.display_name} can sign in again.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<int:user_id>/reset-password", methods=["POST"])
@admin_required
def admin_users_reset_password(user_id):
    user = User.query.get_or_404(user_id)
    user.password_hash = generate_password_hash(settings.DEFAULT_USER_PASSWORD)
    user.must_change_password = True
    db.session.commit()
    flash(f"{user.display_name}'s password has been reset to "
          f"{settings.DEFAULT_USER_PASSWORD} - they'll be asked to change it "
          f"on their next login.", "success")
    return redirect(url_for("admin_users"))


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
        employee=request.args.get("employee", type=int),
    )


# ----------------------------------------------------------------------
# Document form (one per template)
# ----------------------------------------------------------------------

FILENAME_UNSAFE_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')




# ----------------------------------------------------------------------
# What the screens need to know beyond the records themselves
# ----------------------------------------------------------------------

def grouped_templates():
    """The ten document types arranged for the picker, in group order."""
    groups = []
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


# The fields worth showing in the history table's equipment column, in
# the order we would rather have them: what the thing is, then which one.



def active_filters(q, type_filter, date_from, date_to):
    """The filters currently narrowing the history, each as a label plus
    the query string that removes just that one - so they can be read back
    in words and cleared individually."""
    current = {"q": q, "type": type_filter, "from": date_from, "to": date_to}
    chips = []
    def add(key, label):
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


# ----------------------------------------------------------------------
# Employees already on file
#
# Every template asks for the same seven employee fields, and somebody
# collecting a laptop usually collects a mouse, a keyboard and a headset
# too - so the same national ID was being typed out four times, each one
# a fresh chance to get a digit wrong on a document that gets signed.
# The details are already in the history; these helpers hand them back.
# ----------------------------------------------------------------------

# Fields that describe the person rather than the equipment. Only these
# are ever copied from a previous document - the serial number of the
# laptop they were given last year must not follow them onto a new one.




def matches_query(person, query):
    """Whether a lookup entry answers to what was typed.

    Both names are searched. Someone whose documents are in Arabic is
    still found by typing the English spelling - which is the one on
    most keyboards, and the one people remember from the mailbox.
    """
    return any(query in (person.get(key) or "").lower()
               for key in ("name", "name_en", "code", "department"))


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



def save_document(template_id, values, fill_data, date_obj, record=None):
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


def render_form(template_id, data, record=None, duplicate=None, owners=None):
    spec = TEMPLATES[template_id]
    return render_template(
        "form.html", spec=spec, template_id=template_id,
        data=data, today=date.today().isoformat(), record=record,
        duplicate=duplicate, owners=owners,
    )




# ----------------------------------------------------------------------
# Create a document
# ----------------------------------------------------------------------

@app.route("/new/<template_id>", methods=["GET", "POST"])
@login_required
def new_document(template_id):
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
    source_id = request.args.get("employee", type=int)
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

@app.route("/edit/<int:record_id>", methods=["GET", "POST"])
@login_required
def edit_document(record_id):
    record = Handover.query.get_or_404(record_id)
    if not is_owner_or_admin(record.created_by_user_id):
        abort(403)
    template_id = record.template_id
    if template_id not in TEMPLATES:
        flash("That document was made from a template this site no longer has.", "error")
        return redirect(url_for("history"))

    # Admin-only: who this record counts as belonging to, editable here
    # rather than as its own page, since opening this form for an
    # unowned (pre-accounts) record already requires Admin - claiming it
    # for the right person is a natural extra step while already here.
    is_admin = session.get("role") == "admin"
    owners = User.query.filter_by(is_active=True).order_by(User.display_name).all() if is_admin else None

    if request.method == "POST":
        # What this document already says is allowed to stay, so a record
        # made before a list was closed is still editable.
        values, fill_data, date_obj, errors = collect_values(
            template_id, request.form, existing=record.fields)
        if errors:
            for message in errors:
                flash(message, "error")
            return render_form(template_id, request.form, record=record, owners=owners)

        record, problem = save_document(template_id, values, fill_data, date_obj,
                                        record=record)
        if problem:
            flash(problem, "error")
            return render_form(template_id, request.form, record=record, owners=owners)

        if is_admin and "owner_user_id" in request.form:
            raw = request.form.get("owner_user_id", "").strip()
            record.created_by_user_id = int(raw) if raw else None
            db.session.commit()

        flash(f"Saved. The document for {record.name} has been generated again.", "success")
        return redirect(url_for("done", record_id=record.id))

    return render_form(template_id, form_data_from_record(record), record=record, owners=owners)


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
    employee = request.args.get("employee", type=int)
    if len(chosen) == 1:
        return redirect(url_for("new_document", template_id=chosen[0], employee=employee))
    return redirect(url_for("new_batch", types=",".join(chosen), employee=employee))


@app.route("/new-batch", methods=["GET", "POST"])
@login_required
def new_batch():
    chosen = [t for t in request.values.get("types", "").split(",") if t in TEMPLATES]
    if len(chosen) < 2:
        return redirect(url_for("index"))

    def show(data, duplicates=None, per_template_errors=None):
        return render_template(
            "batch_form.html", chosen=chosen, templates=TEMPLATES,
            data=data, today=date.today().isoformat(),
            types=",".join(chosen), duplicates=duplicates or {},
            errors=per_template_errors or {},
        )

    if request.method == "POST":
        collected, errors, duplicates = {}, {}, {}
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
            for template_id, problems in errors.items():
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
        created = []
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
    source_id = request.args.get("employee", type=int)
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
    if session.get("role") != "admin":
        records = [r for r in records if r.created_by_user_id == session.get("user_id")]
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


def build_mailto(records, detailed):
    # No sender is passed and no sign-off is written: the draft opens in
    # whoever's Outlook clicked the link, and their own signature goes
    # under it.
    body = notify_email.build_body(
        records, greeting_name=settings.NOTIFY_NAME, detailed=detailed)
    query = urlencode({"subject": notify_email.subject_for(records), "body": body},
                      quote_via=quote)
    return (f"mailto:{quote(','.join(settings.addresses(settings.NOTIFY_TO)), safe='@.,')}"
            f"?{query}")


def mailto_link(records):
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


@app.route("/done/<int:record_id>")
@login_required
def done(record_id):
    record = Handover.query.get_or_404(record_id)
    return render_template("done.html", record=record,
                           mailto=mailto_link([record]))


@app.route("/file/<int:record_id>")
@login_required
def get_file(record_id):
    record = Handover.query.get_or_404(record_id)
    if not is_owner_or_admin(record.created_by_user_id):
        abort(403)
    file_path = settings.GENERATED_DIR / record.filename
    if not file_path.exists():
        abort(404)
    return send_from_directory(
        settings.GENERATED_DIR, record.filename,
        as_attachment=True, download_name=display_filename(record.template_id, record.name),
    )


@app.route("/history/<int:record_id>/regenerate", methods=["POST"])
@login_required
def regenerate_file(record_id):
    """Rebuild this record's .docx from what is stored on it, for when the
    file under generated/ has gone missing on its own - deleted from the
    folder by hand, or lost to an interrupted OneDrive sync - while the
    record itself is still on file.

    A deliberate action from History, not something that happens quietly
    on download: the row is found by searching, same as anything else
    here, and the button only appears once the file is confirmed missing."""
    record = Handover.query.get_or_404(record_id)
    if not is_owner_or_admin(record.created_by_user_id):
        abort(403)
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

    # Staff only ever see what they made - a record with no verified
    # owner (made before accounts existed) or owned by someone else
    # simply never appears here for them, same as if it didn't exist.
    # An Admin sees everything, unfiltered.
    is_admin = session.get("role") == "admin"
    if not is_admin:
        query = query.filter(Handover.created_by_user_id == session.get("user_id"))

    total = query.count()
    pages = max(1, (total + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE)
    page = min(page, pages)
    records = query.offset((page - 1) * HISTORY_PAGE_SIZE).limit(HISTORY_PAGE_SIZE).all()

    grand_total = (Handover.query.count() if is_admin else
                   Handover.query.filter_by(created_by_user_id=session.get("user_id")).count())

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
        # size of what this person can see overall, or it reads as though
        # filtering deleted everything else.
        grand_total=grand_total,
    )


def _filtered_history_query():
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


def refresh_register():
    """Rebuild the sheet. Returns None on success, or a sentence saying
    why not.

    This is called from the middle of generating a document, so it must
    never raise: a register that could not be written is a nuisance, and
    losing the document that was just signed is not. The usual cause on
    Windows is the file being open in Excel, which locks it - worth
    saying plainly rather than reporting as an error.
    """
    try:
        asset_register.write_workbook(register_rows(), settings.REGISTER_PATH,
                                      departures=departures_by_identity())
        return None
    except PermissionError:
        return (f"The laptop register ({settings.REGISTER_PATH.name}) is open in Excel, "
                f"so it could not be updated. Close it and the next document "
                f"will bring it up to date.")
    except Exception as problem:            # noqa: BLE001 - never block the document
        app.logger.exception("register rebuild failed")
        return f"The laptop register could not be updated: {problem}"


def register_updated():
    """Rebuild, and flash only if something went wrong. Success is
    silent: it happens on every single document and a message saying so
    every time would be noise the person learns to ignore."""
    problem = refresh_register()
    if problem:
        flash(problem, "info")


def notify_draft(records):
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
    wanted = [int(i) for i in request.form.getlist("id") if i.isdigit()]
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


# ----------------------------------------------------------------------
# Someone is leaving
#
# Two messages go out when an employee resigns. Every detail is typed
# here rather than looked up: people leave who never had a document
# generated for them, and a page that could only describe employees on
# file would be useless exactly when it was needed.
#
# The form is plain GET, so it works with JavaScript off - the details
# come back in the URL and the links are rebuilt server-side. With
# JavaScript on, the links carry a token per field and are rewritten as
# the boxes are typed, so the buttons are live and nothing has to be
# submitted at all.
# ----------------------------------------------------------------------

# Where a computer's serial number lives, per document type. A
# replacement issues a new machine, so its NEW serial is the one the
# person is still holding on the day they leave. A headset receipt has a
# serial too and it is not the one the security team is asking about, so
# only these two count.



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


def leaver_drafts(person):
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


def leaver_links(person):
    """The same two messages as a mailto: each, for the page's fallback
    links and for browsers that have to open them one at a time."""
    return {d["key"]: "mailto:{}?{}".format(
                # A mailto: URL separates them with commas, not semicolons.
                quote(",".join(settings.addresses(d["to"])), safe="@.,"),
                urlencode({"subject": d["subject"], "body": d["body"]},
                          quote_via=quote))
            for d in leaver_drafts(person)}


def open_drafts_here(drafts):
    """Put these drafts in front of the person. Returns (opened, reason)
    - reason being why not, for the page to show.

    Only for a browser on this machine: the drafts open in the Outlook
    the APP is running next to, so a colleague opening this page from
    their own desk would otherwise pop windows up on somebody else's
    screen. They get the mailto: fallback instead, which opens on theirs.
    """
    setting = settings.OUTLOOK_DRAFTS
    if setting == "never":
        return False, ("Opening drafts in Outlook is switched off "
                       "(HANDOVER_OUTLOOK=never in your .env file).")
    if setting != "always" and request.remote_addr not in ("127.0.0.1", "::1"):
        # Reached over the network. That is usually a colleague at
        # another desk, but it is also what it looks like when this app
        # is opened on its OWN machine by its network name or IP rather
        # than localhost - which "auto" has no way to tell apart. Hence
        # the address in the message, and the setting to override it.
        return False, (f"This page was opened from {request.remote_addr} rather "
                       f"than from this machine, so the draft would appear on "
                       f"this app's Outlook rather than yours. If this IS the "
                       f"same machine, set HANDOVER_OUTLOOK=always in your .env "
                       f"file and restart.")
    problem = outlook_com.open_drafts(drafts)
    return problem is None, problem or ""


def opened_in_outlook(typed):
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


def record_departure(typed):
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


def departure_rows():
    """Every recorded resignation, newest first, with where each one's
    details actually come from.

    A person who has handover documents on file is described BY those
    documents on the register, so correcting their name means correcting
    the document - fixing the resignation record would change nothing
    anyone can see. The list says which of the two it is rather than
    letting someone edit the wrong one.
    """
    by_identity = {}
    for row in register_rows():
        by_identity.setdefault(row["identity"], []).append(row)
    out = []
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


@app.route("/resignation/<int:departure_id>/edit", methods=["GET", "POST"])
@login_required
def edit_departure(departure_id):
    """Correct a recorded resignation.

    The register is a report, not a record: it is rewritten from this
    database every time anything changes, so a correction typed into the
    spreadsheet is gone by the next document. This is where it sticks.
    """
    gone = Departure.query.get_or_404(departure_id)
    if not is_owner_or_admin(gone.recorded_by_user_id):
        abort(403)
    is_admin = session.get("role") == "admin"
    owners = User.query.filter_by(is_active=True).order_by(User.display_name).all() if is_admin else None

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
                                   typed=typed, gone=gone, owners=owners)

        for key, value in typed.items():
            setattr(gone, key, value)
        if wanted:
            gone.identity = wanted
        gone.recorded_by = session.get("display_name", "-")
        if gone.recorded_by_user_id is None:
            gone.recorded_by_user_id = session.get("user_id")
        if is_admin and "owner_user_id" in request.form:
            raw = request.form.get("owner_user_id", "").strip()
            gone.recorded_by_user_id = int(raw) if raw else None
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
                           gone=gone, owners=owners)


@app.route("/resignation/<int:departure_id>/remove", methods=["POST"])
@admin_required
def remove_departure(departure_id):
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


@app.route("/delete/<int:record_id>", methods=["POST"])
@admin_required
def delete_history(record_id):
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


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))



