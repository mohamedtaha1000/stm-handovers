#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
models.py
=========
What the app stores, and nothing else: the tables, and the migrations
that keep an older database readable.

Split out of app.py so "what is a Handover" is answerable without
reading past thirty routes, and so the domain modules can be handed rows
to work on without importing the web application. The SQLAlchemy object
is created unbound here and attached to the app in app.py, which is what
lets this module be imported on its own.
"""

import json
import logging
import uuid
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from werkzeug.security import generate_password_hash

import settings
from templates import TEMPLATES

log = logging.getLogger(__name__)

db = SQLAlchemy()


def new_uuid():
    """A record's id, opaque and non-sequential - so seeing one (in a
    URL, in a shared link) never tells you anything about how many
    others exist or lets you step through them one by one."""
    return str(uuid.uuid4())


class Handover(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
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
    created_by_user_id = db.Column(db.String(36), db.ForeignKey("user.id"))
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
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
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
    recorded_by_user_id = db.Column(db.String(36), db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class User(db.Model):
    """A real login. Replaces the single shared team password: each
    person gets their own username, and a role decides what they can do
    beyond the everyday work every signed-in person can already do
    (making documents, recording resignations, looking people up)."""
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
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


def _needs_uuid_migration():
    """Whether user/handover/departure still have their original
    auto-incrementing integer id column, from before ids were switched
    to UUIDs."""
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    for table in ("user", "handover", "departure"):
        if table not in tables:
            continue
        id_col = next((c for c in inspector.get_columns(table) if c["name"] == "id"), None)
        if id_col is not None and "INT" in str(id_col["type"]).upper():
            return True
    return False


def _migrate_integer_ids_to_uuid():
    """One-time rebuild of user/handover/departure onto UUID primary
    keys, in place of the auto-incrementing integers they started with.

    A sequential integer id is easy to guess and step through in a URL
    (try /file/1, /file/2, ... and you have found every document, real
    national IDs included) - a UUID carries no such information.

    SQLite cannot ALTER a column's type or its PRIMARY KEY / FOREIGN KEY
    constraints in place, so each table is renamed aside, recreated from
    the current (UUID) model definitions, and every row is copied back
    in with a freshly generated id. user is done first so handover's and
    departure's foreign keys can be rewritten to match the new user ids
    as they go - anything pointing at a user gets remapped, anything
    NULL (no verified owner) stays NULL.

    Runs at most once: after this, the id columns are text, so
    _needs_uuid_migration() never fires again for this database.
    """
    if not _needs_uuid_migration():
        return

    log.warning(
        "Migrating user/handover/departure to UUID primary keys - this "
        "runs once and rewrites every row's id. Existing data (including "
        "foreign keys to user) is preserved."
    )

    tables = inspect(db.engine).get_table_names()
    present = [t for t in ("user", "handover", "departure") if t in tables]

    rows_by_table = {}
    with db.engine.begin() as conn:
        for table in present:
            rows_by_table[table] = [
                dict(row) for row in conn.execute(text(f"SELECT * FROM {table}")).mappings().all()
            ]
            # SQLite renames the table but leaves its indexes registered
            # under their original names, still attached to the renamed
            # table - left alone, db.create_all() below would collide
            # with them trying to create the same-named index fresh.
            for (index_name,) in conn.execute(text(
                    "SELECT name FROM sqlite_master WHERE type='index' "
                    "AND tbl_name=:t AND sql IS NOT NULL"), {"t": table}):
                conn.execute(text(f"DROP INDEX {index_name}"))
            conn.execute(text(f"ALTER TABLE {table} RENAME TO {table}_old"))

    # Recreates exactly the tables just renamed away, under their
    # current (UUID) schema - db.create_all() only ever fills in
    # tables that don't already exist, so nothing else is touched.
    db.create_all()

    # A column real ALTER-TABLE history added and the model later
    # stopped declaring is never dropped - SQLite migrations here only
    # ever add columns (see create_all_and_migrate()'s docstring), so it
    # just sits there unused. Harmless normally; fatal to a raw INSERT
    # that carries every old column forward, so anything the current
    # model doesn't recognise is dropped here rather than copied.
    new_inspector = inspect(db.engine)
    valid_cols = {t: {c["name"] for c in new_inspector.get_columns(t)} for t in present}

    def insert(conn, table, data):
        data = {k: v for k, v in data.items() if k in valid_cols[table]}
        cols = ", ".join(data.keys())
        placeholders = ", ".join(f":{k}" for k in data.keys())
        conn.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"), data)

    with db.engine.begin() as conn:
        user_id_map = {}
        for row in rows_by_table.get("user", []):
            new_id = new_uuid()
            user_id_map[row["id"]] = new_id
            insert(conn, "user", {**row, "id": new_id})

        for row in rows_by_table.get("handover", []):
            data = {**row, "id": new_uuid()}
            if data.get("created_by_user_id") is not None:
                data["created_by_user_id"] = user_id_map.get(data["created_by_user_id"])
            insert(conn, "handover", data)

        for row in rows_by_table.get("departure", []):
            data = {**row, "id": new_uuid()}
            if data.get("recorded_by_user_id") is not None:
                data["recorded_by_user_id"] = user_id_map.get(data["recorded_by_user_id"])
            insert(conn, "departure", data)

        for table in present:
            conn.execute(text(f"DROP TABLE {table}_old"))

    log.warning("UUID migration complete: %s",
                ", ".join(f"{t}={len(rows_by_table.get(t, []))} rows" for t in present))


def create_all_and_migrate():
    """Create the tables, rebuild ids onto UUIDs if this database still
    has the old integer ones, then add any column an older database is
    missing. Called once from app.py inside an application context.

    Everything past the UUID rebuild only ever adds a column - no row is
    rewritten and nothing is dropped, so running this against an
    up-to-date database does nothing at all.
    """
    _migrate_integer_ids_to_uuid()
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
                    "ALTER TABLE handover ADD COLUMN created_by_user_id VARCHAR(36)"))

    if "departure" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("departure")}
        with db.engine.begin() as conn:
            for column, kind in (("code", "VARCHAR(60)"),
                                 ("name_en", "VARCHAR(200)"),
                                 ("department", "VARCHAR(120)"),
                                 ("email", "VARCHAR(200)"),
                                 ("recorded_by_user_id", "VARCHAR(36)")):
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
