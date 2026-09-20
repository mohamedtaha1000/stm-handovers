#!/usr/bin/env python3
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

The routes themselves live in routes/ - one file per area (auth,
documents, resignation, admin), plus routes/common.py for the handful
of things more than one of them needs. This file builds the Flask app
and wires up the database; each routes/*.py module then registers its
own routes directly on this same `app` object (imported back for that
one purpose) via the ordinary @app.route(...), once `app` exists below.
Not Blueprints: see routes/auth.py's module docstring for why - in
short, every existing url_for()/request.endpoint reference across every
template would otherwise need to change, for no benefit to this being a
purely organisational split.

Run locally:
    pip install -r requirements.txt
    python app.py
    -> open http://127.0.0.1:5000

See README.md for environment variables and deployment notes.
"""

import os
import secrets
from typing import Any

from flask import Flask, Response, flash, redirect, url_for

import settings
from models import create_all_and_migrate, db

app = Flask(__name__)

# Everything configurable lives in settings.py. Read through the module
# (settings.X) rather than importing the names, so a test that points the
# app at a temporary folder is actually seen by the code that writes
# there.
app.config["SECRET_KEY"] = settings.SECRET_KEY or secrets.token_hex(32)
app.config["SQLALCHEMY_DATABASE_URI"] = settings.DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
with app.app_context():
    create_all_and_migrate()

# Imported for their side effect (registering routes on `app` above via
# @app.route(...)), not for any name used here - each does `from app
# import app` in turn, which is safe specifically because `app` is
# already fully created by this point. auth first: the others import
# login_required/admin_required from it.
import routes.admin  # noqa: E402,F401
import routes.auth  # noqa: E402,F401
import routes.documents  # noqa: E402,F401
import routes.resignation  # noqa: E402,F401


@app.context_processor
def notify_details() -> dict[str, str]:
    """Who the handover email goes to, available to every template so the
    buttons and the optional section can name them rather than saying
    "the asset owner"."""
    return {"notify_name": settings.NOTIFY_NAME, "notify_to": settings.NOTIFY_TO}


@app.template_filter("initials")
def initials(value: Any) -> str:
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
def mask_id(value: Any) -> str:
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


@app.errorhandler(403)
def forbidden(_error: Exception) -> Response:
    # A plain redirect, not a 403 response with a Location header - a
    # browser only follows a Location header on a 3xx status, so keeping
    # the 403 here would leave the tab stuck on an error page instead of
    # actually landing back in the app.
    flash("You don't have permission to do that.", "error")
    return redirect(url_for("index"))


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
