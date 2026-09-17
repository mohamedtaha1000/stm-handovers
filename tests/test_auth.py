"""Login, logout, and the forced first-password-change flow."""

from conftest import login, login_as, make_user


def test_login_wrong_password_shows_generic_error(client, admin_user):
    resp = login(client, "test-admin", "not-the-password")
    assert resp.status_code == 200
    assert b"Wrong username or password" in resp.data


def test_login_unknown_username_shows_same_generic_error(client):
    resp = login(client, "nobody-by-this-name", "whatever")
    assert b"Wrong username or password" in resp.data


def test_login_deactivated_account_is_refused(client, app):
    from models import User, db
    make_user(app, username="gone")
    with app.app_context():
        User.query.filter_by(username="gone").update({"is_active": False})
        db.session.commit()
    resp = login(client, "gone")
    assert b"Wrong username or password" in resp.data


def test_login_success_redirects_home(client, admin_user):
    resp = login(client, "test-admin", "test-admin-password")
    assert resp.status_code == 302
    assert resp.headers["Location"] in ("/", "http://localhost/")


def test_forced_password_change_blocks_everything_else(client, app):
    staff = make_user(app, username="newbie", must_change_password=True)
    login_as(client, staff)
    resp = client.get("/history", follow_redirects=False)
    assert resp.status_code == 302
    assert "/account/change-password" in resp.headers["Location"]


def test_forced_password_change_cannot_be_bypassed_by_direct_url(client, app):
    staff = make_user(app, username="newbie", must_change_password=True)
    login_as(client, staff)
    resp = client.get("/resignation", follow_redirects=False)
    assert "/account/change-password" in resp.headers["Location"]


def test_change_password_success_clears_forced_flag(client, app):
    staff = make_user(app, username="newbie", password="Abc@123456789",
                      must_change_password=True)
    login_as(client, staff)
    resp = client.post("/account/change-password", data={
        "current_password": "Abc@123456789",
        "new_password": "a-new-password-123",
        "confirm_password": "a-new-password-123",
    })
    assert resp.status_code == 302

    # The forced screen must be gone now, in the same session.
    resp = client.get("/history", follow_redirects=False)
    assert resp.status_code == 200


def test_change_password_wrong_current_password_is_rejected(client, app):
    staff = make_user(app, username="newbie", password="Abc@123456789",
                      must_change_password=True)
    login_as(client, staff)
    resp = client.post("/account/change-password", data={
        "current_password": "totally-wrong",
        "new_password": "a-new-password-123",
        "confirm_password": "a-new-password-123",
    })
    assert b"Current password is wrong." in resp.data


def test_change_password_too_short_is_rejected(client, app):
    staff = make_user(app, username="newbie", password="Abc@123456789",
                      must_change_password=True)
    login_as(client, staff)
    resp = client.post("/account/change-password", data={
        "current_password": "Abc@123456789",
        "new_password": "short",
        "confirm_password": "short",
    })
    assert b"at least 8 characters" in resp.data


def test_logout_clears_session(client, app):
    staff = make_user(app, username="someone")
    login_as(client, staff)
    client.get("/logout")
    resp = client.get("/history", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
