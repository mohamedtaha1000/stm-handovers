#!/usr/bin/env python3
"""
routes/admin.py
================
Manage users (Admin only).

The only way an account is ever created. Every new or reset account
gets the same fixed starting password (settings.DEFAULT_USER_PASSWORD)
rather than one an Admin makes up per person - see routes/auth.py for
why.

Not a Blueprint, and routes are registered directly on the shared `app`
object - see routes/auth.py's module docstring for why.
"""

from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash

import settings
from app import app
from models import User, db
from routes.auth import admin_required


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


@app.route("/admin/users/<string:user_id>/rename", methods=["POST"])
@admin_required
def admin_users_rename(user_id: str):
    user = User.query.get_or_404(user_id)
    username = request.form.get("username", "").strip().lower()
    display_name = request.form.get("display_name", "").strip()
    if not username or not display_name:
        flash("A username and a display name are both needed.", "error")
    elif User.query.filter(User.username == username, User.id != user.id).first() is not None:
        flash(f'The username "{username}" is already taken.', "error")
    else:
        user.username = username
        user.display_name = display_name
        db.session.commit()
        if user.id == session.get("user_id"):
            session["display_name"] = display_name
        flash(f"Updated to {display_name} ({username}).", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<string:user_id>/role", methods=["POST"])
@admin_required
def admin_users_role(user_id: str):
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


def _last_active_admin(user: User) -> bool:
    """Whether `user` is the only active Admin left - used to block the
    one action (demoting or deactivating them) that would leave nobody
    able to manage accounts at all."""
    return (User.query.filter_by(role="admin", is_active=True).count() <= 1
            and user.is_active and user.role == "admin")


@app.route("/admin/users/<string:user_id>/deactivate", methods=["POST"])
@admin_required
def admin_users_deactivate(user_id: str):
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


@app.route("/admin/users/<string:user_id>/reactivate", methods=["POST"])
@admin_required
def admin_users_reactivate(user_id: str):
    user = User.query.get_or_404(user_id)
    user.is_active = True
    db.session.commit()
    flash(f"{user.display_name} can sign in again.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/users/<string:user_id>/reset-password", methods=["POST"])
@admin_required
def admin_users_reset_password(user_id: str):
    user = User.query.get_or_404(user_id)
    user.password_hash = generate_password_hash(settings.DEFAULT_USER_PASSWORD)
    user.must_change_password = True
    db.session.commit()
    flash(f"{user.display_name}'s password has been reset to "
          f"{settings.DEFAULT_USER_PASSWORD} - they'll be asked to change it "
          f"on their next login.", "success")
    return redirect(url_for("admin_users"))
