"""Admin-only user management: creating accounts, changing roles,
deactivating/reactivating, resetting passwords - and the guardrails that
stop an Admin locking everyone (including themselves) out."""

from conftest import assert_forbidden, login_as

from models import User, db


def test_staff_cannot_reach_admin_users_page(client, staff_user):
    login_as(client, staff_user)
    resp = client.get("/admin/users")
    assert_forbidden(resp)


def test_admin_can_create_a_user(client, app, admin_user):
    login_as(client, admin_user)
    resp = client.post("/admin/users", data={
        "username": "new-hire", "display_name": "New Hire", "role": "staff",
    }, follow_redirects=False)
    assert resp.status_code == 302

    with app.app_context():
        user = User.query.filter_by(username="new-hire").first()
        assert user is not None
        assert user.role == "staff"
        assert user.must_change_password is True


def test_admin_cannot_create_duplicate_username(client, app, admin_user):
    login_as(client, admin_user)
    client.post("/admin/users", data={
        "username": "dupe", "display_name": "First", "role": "staff",
    })
    resp = client.post("/admin/users", data={
        "username": "dupe", "display_name": "Second", "role": "staff",
    }, follow_redirects=True)
    assert b"already taken" in resp.data

    with app.app_context():
        assert User.query.filter_by(username="dupe").count() == 1


def test_admin_can_change_a_staff_role(client, app, admin_user, staff_user):
    login_as(client, admin_user)
    resp = client.post(f"/admin/users/{staff_user.id}/role", data={"role": "admin"},
                       follow_redirects=False)
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(User, staff_user.id).role == "admin"


def test_cannot_demote_the_only_active_admin(client, app, admin_user):
    login_as(client, admin_user)
    resp = client.post(f"/admin/users/{admin_user.id}/role", data={"role": "staff"},
                       follow_redirects=True)
    assert b"only active Admin" in resp.data
    with app.app_context():
        assert db.session.get(User, admin_user.id).role == "admin"


def test_admin_cannot_deactivate_own_account(client, app, admin_user):
    login_as(client, admin_user)
    resp = client.post(f"/admin/users/{admin_user.id}/deactivate", follow_redirects=True)
    assert b"deactivate your own account" in resp.data
    with app.app_context():
        assert db.session.get(User, admin_user.id).is_active is True


def test_admin_can_deactivate_a_second_admin_when_not_the_last_one(client, app,
                                                                    admin_user, staff_user):
    # The "last active Admin" guard only blocks emptying the Admin role
    # entirely - with two active Admins, deactivating one of them is fine.
    login_as(client, admin_user)
    client.post(f"/admin/users/{staff_user.id}/role", data={"role": "admin"})
    resp = client.post(f"/admin/users/{staff_user.id}/deactivate", follow_redirects=False)
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(User, staff_user.id).is_active is False


def test_admin_can_deactivate_and_reactivate_a_staff_account(client, app, admin_user,
                                                              staff_user):
    login_as(client, admin_user)
    client.post(f"/admin/users/{staff_user.id}/deactivate")
    with app.app_context():
        assert db.session.get(User, staff_user.id).is_active is False

    client.post(f"/admin/users/{staff_user.id}/reactivate")
    with app.app_context():
        assert db.session.get(User, staff_user.id).is_active is True


def test_admin_reset_password_forces_change_again(client, app, admin_user, staff_user):
    login_as(client, admin_user)
    resp = client.post(f"/admin/users/{staff_user.id}/reset-password",
                       follow_redirects=False)
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(User, staff_user.id).must_change_password is True


def test_admin_can_rename_any_user(client, app, admin_user, staff_user):
    login_as(client, admin_user)
    resp = client.post(f"/admin/users/{staff_user.id}/rename", data={
        "username": "renamed", "display_name": "Renamed Person",
    }, follow_redirects=False)
    assert resp.status_code == 302
    with app.app_context():
        user = db.session.get(User, staff_user.id)
        assert user.username == "renamed"
        assert user.display_name == "Renamed Person"
