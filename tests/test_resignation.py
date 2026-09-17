"""Recording a resignation, and the Admin-only correction/removal of one
already on file."""

from conftest import assert_forbidden, login_as

from models import Departure, db

VALID_LEAVER = {
    "name": "سارة أحمد",
    "name_en": "Sara Ahmed",
    "code": "20099",
    "department": "Finance",
    "email": "sahmed@stm.com.eg",
    "computer_name": "STM-LT-0099",
    "serial": "SN-LEAVER-0001",
}


def test_mark_left_records_a_departure(client, app, staff_user):
    login_as(client, staff_user)
    resp = client.post("/resignation/record", data=VALID_LEAVER, follow_redirects=False)
    assert resp.status_code == 302

    with app.app_context():
        gone = Departure.query.filter_by(code="20099").first()
        assert gone is not None
        assert gone.name_en == "Sara Ahmed"
        assert gone.recorded_by_user_id == staff_user.id


def test_mark_left_missing_required_field_is_refused(client, app, staff_user):
    login_as(client, staff_user)
    data = {**VALID_LEAVER, "email": ""}
    resp = client.post("/resignation/record", data=data, follow_redirects=True)
    assert b"Nothing was changed" in resp.data
    with app.app_context():
        assert Departure.query.filter_by(code="20099").first() is None


def test_mark_left_json_response(client, app, staff_user):
    login_as(client, staff_user)
    resp = client.post("/resignation/record",
                       data={**VALID_LEAVER, "format": "json"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["recorded"] is True


def test_staff_cannot_open_edit_departure_form(client, app, staff_user):
    login_as(client, staff_user)
    client.post("/resignation/record", data=VALID_LEAVER)
    with app.app_context():
        departure_id = Departure.query.first().id
    resp = client.get(f"/resignation/{departure_id}/edit")
    assert_forbidden(resp)


def test_admin_can_edit_departure(client, app, staff_user, admin_user):
    login_as(client, staff_user)
    client.post("/resignation/record", data=VALID_LEAVER)
    with app.app_context():
        departure_id = Departure.query.first().id

    login_as(client, admin_user)
    resp = client.post(f"/resignation/{departure_id}/edit",
                       data={**VALID_LEAVER, "left_on": "1/1/2026"},
                       follow_redirects=False)
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(Departure, departure_id).left_on == "1/1/2026"


def test_staff_cannot_remove_departure(client, app, staff_user):
    login_as(client, staff_user)
    client.post("/resignation/record", data=VALID_LEAVER)
    with app.app_context():
        departure_id = Departure.query.first().id
    resp = client.post(f"/resignation/{departure_id}/remove")
    assert_forbidden(resp)
    with app.app_context():
        assert db.session.get(Departure, departure_id) is not None


def test_admin_can_remove_departure(client, app, staff_user, admin_user):
    login_as(client, staff_user)
    client.post("/resignation/record", data=VALID_LEAVER)
    with app.app_context():
        departure_id = Departure.query.first().id

    login_as(client, admin_user)
    resp = client.post(f"/resignation/{departure_id}/remove", follow_redirects=False)
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(Departure, departure_id) is None
