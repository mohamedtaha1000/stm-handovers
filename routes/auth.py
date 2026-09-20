#!/usr/bin/env python3
"""
routes/auth.py
===============
Signing in and out, and the two things every account can do to itself:
change its password, change its own username/display name.

login_required and admin_required live here too, since this is where
"who is signed in, and are they an Admin" is decided, and every other
routes module needs both.

Deliberately not a Blueprint: Flask always namespaces a Blueprint's
routes as "blueprintname.viewname" - there is no way to opt out of the
dot, even with an explicit endpoint= - and every existing url_for() and
request.endpoint check across every template would need to change to
match. Importing the same `app` object instead and registering routes
on it directly with the ordinary @app.route(...) keeps every endpoint
name exactly what it already was; this file move is purely
organisational. `app` already exists by the time this module is
imported - see app.py's own comments on import order.
"""

from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app import app
from models import User, db


def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
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


def admin_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        if (session.get("must_change_password")
                and request.endpoint not in ("change_password", "logout")):
            return redirect(url_for("change_password"))
        if session.get("role") != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


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
            # Carried over just so the forced change-password screen can
            # fill in "current password" from what they already typed
            # here, rather than making them type the same thing twice in
            # a row. Read once and discarded - see change_password().
            if user.must_change_password:
                session["_typed_password"] = password
            nxt = request.args.get("next") or url_for("index")
            return redirect(nxt)
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/account/change-password", methods=["GET", "POST"])
def change_password():
    error = None
    # Set at login, only when this screen is about to be forced on them -
    # read once and discarded either way, so it never lingers in the
    # session past this one visit.
    typed_at_login = session.pop("_typed_password", "")
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
        # Failed - keep whatever they'd typed in this box rather than
        # making them retype it along with fixing the actual problem.
        typed_at_login = current
    return render_template(
        "change_password.html", error=error,
        forced=session.get("must_change_password", False),
        current_password=typed_at_login,
    )


@app.route("/account/profile", methods=["GET", "POST"])
@login_required
def account_profile():
    """Change your own username or display name. Not reachable while a
    password change is still forced - that screen is the one thing that
    has to happen first, so it stays the only door open until it does."""
    user = User.query.get(session["user_id"])
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        display_name = request.form.get("display_name", "").strip()
        if not username or not display_name:
            error = "A username and a display name are both needed."
        elif User.query.filter(User.username == username, User.id != user.id).first() is not None:
            error = f'The username "{username}" is already taken.'
        else:
            user.username = username
            user.display_name = display_name
            db.session.commit()
            session["display_name"] = display_name
            flash("Profile updated.", "success")
            return redirect(url_for("index"))
    return render_template("account_profile.html", error=error, user=user)
