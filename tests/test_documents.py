"""Creating, correcting, and deleting handover documents, and the
Staff/Admin permission boundary around them: every signed-in person can
see and download the full History, but only an Admin can edit or delete
a record - Staff never can, not even their own (see DECISIONS.md)."""

from conftest import assert_forbidden, login_as

from models import Handover, db

VALID_LAPTOP_HANDOVER = {
    "name": "محمد شعبان",
    "name_en": "Mohamed Shaban",
    "department": "IT",
    "role": "Software Engineer",
    "mobile": "01012345678",
    "email": "mshaban",
    "code": "10142",
    "govid": "12345678901234",
    "model": "E14",
    "serial": "SN-TEST-0001",
    "cpu": "I5",
    "computer_name": "STM-LT-9999",
}


def create_document(client, staff_user, overrides=None):
    login_as(client, staff_user)
    data = {**VALID_LAPTOP_HANDOVER, **(overrides or {})}
    return client.post("/new/laptop_handover", data=data, follow_redirects=False)


def test_create_document_success(client, app, staff_user):
    resp = create_document(client, staff_user)
    assert resp.status_code == 302
    assert "/done/" in resp.headers["Location"]

    with app.app_context():
        record = Handover.query.filter_by(name="محمد شعبان").first()
        assert record is not None
        assert record.created_by_user_id == staff_user.id
        assert record.fields["email"] == "mshaban@stm.com.eg"


def test_create_document_missing_required_field_shows_error(client, staff_user):
    resp = create_document(client, staff_user, overrides={"govid": ""})
    assert resp.status_code == 200
    assert b"Please fill in all required fields" in resp.data


def test_create_document_bad_mobile_format_is_rejected(client, staff_user):
    resp = create_document(client, staff_user, overrides={"mobile": "123"})
    assert resp.status_code == 200
    assert b"not the right format" in resp.data or b"11-digit" in resp.data


def test_unknown_template_id_is_404(client, staff_user):
    login_as(client, staff_user)
    resp = client.get("/new/not-a-real-template")
    assert resp.status_code == 404


def test_history_shows_every_record_to_every_signed_in_user(client, app, staff_user,
                                                             other_staff_user):
    create_document(client, staff_user)
    login_as(client, other_staff_user)
    resp = client.get("/history")
    assert resp.status_code == 200
    assert "محمد شعبان".encode() in resp.data


def test_staff_cannot_open_edit_form(client, app, staff_user):
    create_document(client, staff_user)
    with app.app_context():
        record_id = Handover.query.first().id
    resp = client.get(f"/edit/{record_id}")
    assert_forbidden(resp)


def test_admin_can_open_edit_form(client, app, staff_user, admin_user):
    create_document(client, staff_user)
    with app.app_context():
        record_id = Handover.query.first().id
    login_as(client, admin_user)
    resp = client.get(f"/edit/{record_id}")
    assert resp.status_code == 200


def test_staff_cannot_delete_document(client, app, staff_user):
    create_document(client, staff_user)
    with app.app_context():
        record_id = Handover.query.first().id
    resp = client.post(f"/delete/{record_id}")
    assert_forbidden(resp)
    with app.app_context():
        assert db.session.get(Handover, record_id) is not None


def test_admin_can_delete_document(client, app, staff_user, admin_user):
    create_document(client, staff_user)
    with app.app_context():
        record_id = Handover.query.first().id
    login_as(client, admin_user)
    resp = client.post(f"/delete/{record_id}", follow_redirects=False)
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(Handover, record_id) is None


def test_admin_edit_regenerates_document(client, app, staff_user, admin_user):
    create_document(client, staff_user)
    with app.app_context():
        record_id = Handover.query.first().id
    login_as(client, admin_user)
    resp = client.post(f"/edit/{record_id}",
                       data={**VALID_LAPTOP_HANDOVER, "role": "Senior Engineer"},
                       follow_redirects=False)
    assert resp.status_code == 302
    with app.app_context():
        record = db.session.get(Handover, record_id)
        assert record.role == "Senior Engineer"
        assert record.updated_by == "Test Admin"
