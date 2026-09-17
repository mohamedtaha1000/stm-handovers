#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
models.py
=========
What the app stores, and nothing else: two tables, and the small
migration that keeps an older database readable.

Split out of app.py so "what is a Handover" is answerable without
reading past thirty routes, and so the domain modules can be handed rows
to work on without importing the web application. The SQLAlchemy object
is created unbound here and attached to the app in app.py, which is what
lets this module be imported on its own.
"""

import json
import logging
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from werkzeug.security import generate_password_hash

import settings
from templates import TEMPLATES

log = logging.getLogger(__name__)

db = SQLAlchemy()


class Handover(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.String(60), nullable=False, default="laptop_handover")
    name = db.Column(db.String(200), nullable=False)
    department = db.Column(db.String(120))
    role = db.Column(db.String(120))
    govid = db.Column(db.String(40))
    handover_date = db.Column(db.String(20))
    # Every field the form collected for this document (mobile, email,
    # code, and whatever device-specific fields that template has) -
    # kept as JSON since different templates collect very different
    # fields. name/department/role/govid above are duplicated out as
    # real columns just so the history list can show and search them
    # without needing to parse JSON for every row.
    fields_json = db.Column(db.Text)
    filename = db.Column(db.String(300), nullable=False)
    created_by = db.Column(db.String(120))
    # Who this record belongs to, for access control - separate from
    # created_by above, which is just the display name printed in
    # History and can't be trusted to identify an account (free-typed,
    # from before real accounts existed). NULL means "no verified
    # owner" - true for every record made before this column existed.
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Set only once a record has actually been corrected, so "never
    # edited" stays distinguishable from "edited by the same person who
    # created it, straight away".
    updated_by = db.Column(db.String(120))
    updated_at = db.Column(db.DateTime)

    @property
    def fields(self):
        try:
            return json.loads(self.fields_json) if self.fields_json else {}
        except (TypeError, ValueError):
            return {}

    @property
    def template_label(self):
        spec = TEMPLATES.get(self.template_id)
        return spec["label"] if spec else self.template_id


class Departure(db.Model):
    """Someone who has left. Kept per person rather than per document:
    they hand back everything at once, and the register works out which
    rows that touches."""
    id = db.Column(db.Integer, primary_key=True)
    # employee_identity(): the employee code where there is one, the
    # national ID behind it, the name as a last resort.
    identity = db.Column(db.String(160), unique=True, index=True)
    name = db.Column(db.String(200))
    # Typed on the leaver page. Kept here because someone can leave
    # without ever having had a document generated for them, and then
    # this is the only place their department and email exist - the
    # resignation sheet would otherwise show their name and four blanks.
    code = db.Column(db.String(60))
    # The English spelling, for the emails and for the sheet's own
    # column - the Arabic name above is what the register matches on.
    name_en = db.Column(db.String(200))
    department = db.Column(db.String(120))
    email = db.Column(db.String(200))
    left_on = db.Column(db.String(20))
    recorded_by = db.Column(db.String(120))
    # Same split as Handover.created_by_user_id: recorded_by above is
    # just a display name, this is the account it can actually be
    # checked against. NULL for anything recorded before accounts
    # existed.
    recorded_by_user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class User(db.Model):
    """A real login. Replaces the single shared team password: each
    person gets their own username, and a role decides what they can do
    beyond the everyday work every signed-in person can already do
    (making documents, recording resignations, looking people up)."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    # What documents, the nav, and every "who did this" field call them -
    # chosen once at account creation rather than retyped every login.
    display_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="staff")
    # Deactivated rather than deleted, so their historical created_by /
    # created_by_user_id rows stay meaningful instead of pointing at
    # nothing.
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    # True for every account an Admin creates or resets - an Admin never
    # chooses a real password for someone else, only ever the same fixed
    # default, so this is what forces the person to replace it with
    # something only they know before they can do anything else. The
    # bootstrap admin (settings.ADMIN_PASSWORD, a real password someone
    # chose during setup) is the one account created with this False.
    must_change_password = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def is_admin(self):
        return self.role == "admin"


def create_all_and_migrate():
    """Create the tables, then add any column an older database is
    missing. Called once from app.py inside an application context.

    SQLite's ALTER TABLE only supports adding columns, which is all this
    has ever needed - no row is rewritten and nothing is dropped, so
    running it against an up-to-date database does nothing at all.
    """
    db.create_all()

    # Lightweight migration: add any columns older databases don't have
    # yet, without touching (or losing) existing rows. SQLite's ALTER
    # TABLE only supports adding columns, which is all we need here.
    inspector = inspect(db.engine)
    if "handover" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("handover")}
        with db.engine.begin() as conn:
            if "template_id" not in existing_cols:
                conn.execute(text(
                    "ALTER TABLE handover ADD COLUMN template_id VARCHAR(60) "
                    "DEFAULT 'laptop_handover'"
                ))
            if "fields_json" not in existing_cols:
                conn.execute(text("ALTER TABLE handover ADD COLUMN fields_json TEXT"))
            if "govid" not in existing_cols:
                conn.execute(text("ALTER TABLE handover ADD COLUMN govid VARCHAR(40)"))
            if "updated_by" not in existing_cols:
                conn.execute(text("ALTER TABLE handover ADD COLUMN updated_by VARCHAR(120)"))
            if "updated_at" not in existing_cols:
                conn.execute(text("ALTER TABLE handover ADD COLUMN updated_at DATETIME"))
            if "created_by_user_id" not in existing_cols:
                conn.execute(text(
                    "ALTER TABLE handover ADD COLUMN created_by_user_id INTEGER"))

    if "departure" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("departure")}
        with db.engine.begin() as conn:
            for column, kind in (("code", "VARCHAR(60)"),
                                 ("name_en", "VARCHAR(200)"),
                                 ("department", "VARCHAR(120)"),
                                 ("email", "VARCHAR(200)"),
                                 ("recorded_by_user_id", "INTEGER")):
                if column not in existing_cols:
                    conn.execute(text(
                        f"ALTER TABLE departure ADD COLUMN {column} {kind}"))

    ensure_bootstrap_admin()


def ensure_bootstrap_admin():
    """Create the very first Admin account from ADMIN_USERNAME/
    ADMIN_PASSWORD, but only if no account exists yet.

    This is the one and only account this app ever creates without an
    Admin doing it through /admin/users - every other account is always
    created by an Admin, always with the same fixed starting password
    (see settings.DEFAULT_USER_PASSWORD), never one this app makes up on
    its own. Once a single account exists, this is inert forever, so the
    env vars are harmless to leave set.
    """
    if User.query.count() > 0:
        return
    if not (settings.ADMIN_USERNAME and settings.ADMIN_PASSWORD):
        log.warning(
            "No accounts exist yet and ADMIN_USERNAME/ADMIN_PASSWORD are "
            "not set - nobody can log in until an admin account exists. "
            "Set both in your .env file (or as environment variables) "
            "and restart."
        )
        return
    db.session.add(User(
        username=settings.ADMIN_USERNAME.strip().lower(),
        password_hash=generate_password_hash(settings.ADMIN_PASSWORD),
        display_name=settings.ADMIN_DISPLAY_NAME,
        role="admin",
        must_change_password=False,
    ))
    db.session.commit()
