"""Running `python app.py` directly (what the README tells everyone to
do, and what a real deployment's dev/debug runs looks like) is a
different code path from every other test in this suite - those all
`from app import app`, which imports this file as a module named "app".
Run directly, Python instead loads it as "__main__".

That distinction bit for real: routes/*.py each do `from app import
app` to register their routes on the one shared Flask instance.
Imported normally, that finds the already-loaded "app" module and
reuses its Flask instance. Run as a script, there IS no "app" module
loaded yet - only "__main__" - so that import silently re-ran app.py
from scratch under the name "app", creating a second, separate Flask
instance. Every route ended up registered on that second, never-served
instance, while the one the dev server actually ran had none at all:
it started up with no errors and 404'd on every single URL, including
"/". app.py now registers itself into sys.modules under "app" before
importing the route modules specifically to close this gap - see its
own comment. This test would have caught the bug before it reached
anyone running the app the ordinary way.
"""

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def running_app_process(tmp_path):
    """A real `python app.py` subprocess, pointed at a throwaway
    database - not the one the rest of this suite uses, since that one
    is only ever touched through the app's own Flask test client."""
    port = _free_port()
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{tmp_path / 'script_run.db'}",
        "SECRET_KEY": "script-run-test-secret",
        "HANDOVER_OUTLOOK": "never",
        "HANDOVER_REGISTER_PATH": str(tmp_path / "register.xlsx"),
        "PORT": str(port),
    }
    process = subprocess.Popen(
        [sys.executable, "app.py"], cwd=PROJECT_ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 15
        last_error = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output = process.stdout.read()
                pytest.fail(f"`python app.py` exited early:\n{output}")
            try:
                urllib.request.urlopen(f"{base_url}/login", timeout=1)
                break
            except (urllib.error.URLError, ConnectionError) as error:
                last_error = error
                time.sleep(0.3)
        else:
            process.kill()
            pytest.fail(f"`python app.py` never came up on {base_url}: {last_error}")
        yield base_url
    finally:
        process.kill()
        process.wait(timeout=5)


def test_routes_are_reachable_when_run_as_a_script(running_app_process):
    base_url = running_app_process
    # Not logged in, so "/" and "/history" redirect to /login - urlopen
    # follows that transparently, landing on a 200. The point isn't the
    # exact status; it's that these are real ROUTES, not bare 404s from
    # an empty second Flask instance nobody registered anything on -
    # which is what urlopen would raise HTTPError(404) for instead.
    for path in ("/", "/login", "/history"):
        try:
            with urllib.request.urlopen(f"{base_url}{path}") as resp:
                assert resp.status == 200
        except urllib.error.HTTPError as error:
            pytest.fail(f"{path} returned {error.code} - route not registered?")
