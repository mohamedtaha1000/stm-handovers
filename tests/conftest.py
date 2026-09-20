"""
tests/conftest.py
==================
Test setup for an app with no factory pattern: settings.py reads its
environment variables at import time, so every one of them has to be set
here, at module load, before anything below gets the chance to `import
app`, `import models`, or `import settings` for the first time. pytest
guarantees conftest.py runs before it collects any test module, which is
what makes this ordering safe.

One temporary folder backs the whole test session (a real sqlite file
and a real .xlsx, not mocks) - this app's own established style is to
test against real logic rather than guess, and a fresh temp folder per
session is enough: `_reset_db` below wipes and rebuilds every table
before each test, so nothing leaks between them.
"""

import os
import tempfile
from pathlib import Path

_TEST_DIR = Path(tempfile.mkdtemp(prefix="stm_handovers_tests_"))

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DIR / 'test.db'}"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["ADMIN_USERNAME"] = "test-admin"
os.environ["ADMIN_PASSWORD"] = "test-admin-password"
os.environ["ADMIN_DISPLAY_NAME"] = "Test Admin"
os.environ["DEFAULT_USER_PASSWORD"] = "Abc@123456789"
# "never" so a resignation test never reaches outlook_com's real win32com
# call - that module only imports win32com.client lazily, inside a
# function, specifically so this is possible on a machine (or a Linux CI
# runner) with no Outlook at all.
os.environ["HANDOVER_OUTLOOK"] = "never"

import pytest  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

import settings  # noqa: E402
from app import app as flask_app  # noqa: E402
from models import User, db  # noqa: E402

# settings.py's own docstring: import the MODULE and reassign its
# attributes, since GENERATED_DIR/REGISTER_PATH are read at call time
# through `settings.X`, not frozen at import. There is no env var for
# GENERATED_DIR (only HANDOVER_REGISTER_PATH covers the register), so
# this is the only way to keep generated .docx files out of the real
# generated/ folder.
settings.GENERATED_DIR = _TEST_DIR / "generated"
settings.GENERATED_DIR.mkdir(exist_ok=True)
settings.REGISTER_PATH = _TEST_DIR / "laptop_register.xlsx"

flask_app.config.update(TESTING=True)


@pytest.fixture
def app():
    """The single, real Flask app - not a factory, so every test shares
    the one instance, and `_reset_db` below is what keeps them from
    seeing each other's data."""
    return flask_app


@pytest.fixture(autouse=True)
def _reset_db(app):
    """Fresh tables before every test. Cheap enough on sqlite to do for
    real rather than trying to roll back a transaction, and it means a
    test can never see a row a previous one left behind."""
    with app.app_context():
        db.drop_all()
        db.create_all()
        from models import ensure_bootstrap_admin
        ensure_bootstrap_admin()
        yield
        db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


def _detached_copy(user):
    """A plain, un-bound snapshot of a User row's columns.
    db.session.commit() expires every attribute on the ORM object by
    default (expire_on_commit=True) so the next access re-reads it from
    the database - fine normally, but fatal once the object outlives the
    app_context/session it was loaded in, which every fixture here does.
    A snapshot sidesteps the whole ORM lifecycle instead of fighting it."""
    from types import SimpleNamespace
    return SimpleNamespace(
        id=user.id, username=user.username, display_name=user.display_name,
        role=user.role, is_active=user.is_active,
        must_change_password=user.must_change_password,
    )


@pytest.fixture
def admin_user(app):
    """The one account ensure_bootstrap_admin() creates from
    ADMIN_USERNAME/ADMIN_PASSWORD above."""
    with app.app_context():
        return _detached_copy(User.query.filter_by(username="test-admin").first())


def make_user(app, *, username, display_name="Someone", role="staff",
             password="Abc@123456789", must_change_password=False):
    """A ready-to-log-in account, for tests that don't care about the
    admin-creates-every-account flow itself (that flow has its own
    tests in test_admin.py)."""
    with app.app_context():
        user = User(
            username=username, display_name=display_name, role=role,
            password_hash=generate_password_hash(password),
            must_change_password=must_change_password,
        )
        db.session.add(user)
        db.session.commit()
        return _detached_copy(user)


@pytest.fixture
def staff_user(app):
    return make_user(app, username="staff-one", display_name="Staff One")


@pytest.fixture
def other_staff_user(app):
    return make_user(app, username="staff-two", display_name="Staff Two")


def login(client, username, password="Abc@123456789"):
    return client.post("/login", data={"username": username, "password": password})


def assert_forbidden(resp):
    """This app's actual "you can't do that" contract: app.py's own
    @app.errorhandler(403) turns every admin_required/abort(403) into a
    302 redirect (with a flash message) rather than a bare 403 response
    - deliberately, so a browser actually lands somewhere instead of
    being stuck on an error page. A raw assert on status_code == 403
    would never pass against this app; this is what "forbidden" looks
    like here."""
    assert resp.status_code == 302
    assert resp.headers["Location"] in ("/", "http://localhost/")


def login_as(client, user):
    """Skip the HTTP round-trip through /login for tests that only care
    about what happens after - sets exactly what routes/auth.py's own
    login() view sets on success."""
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["user_id"] = user.id
        sess["role"] = user.role
        sess["display_name"] = user.display_name
        sess["must_change_password"] = user.must_change_password
