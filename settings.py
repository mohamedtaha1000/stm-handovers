#!/usr/bin/env python3
"""
settings.py
===========
Every knob in one place: where files live, who the emails go to, what
the shared password is.

All of it comes from the environment (a .env file beside the app, or
real environment variables when deployed) so a change of owner, address
or folder needs no edit and no redeploy. Import the MODULE, not the
names - the tests point these at a temporary folder by reassigning
them, and that only works if they are read at call time:

    import settings
    settings.GENERATED_DIR / name        # picks up a reassignment
    from settings import GENERATED_DIR   # frozen at import - don't
"""

import os
import re
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

GENERATED_DIR = BASE_DIR / "generated"
INSTANCE_DIR = BASE_DIR / "instance"
DOC_TEMPLATES_DIR = BASE_DIR / "doc_templates"
GENERATED_DIR.mkdir(exist_ok=True)
INSTANCE_DIR.mkdir(exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{INSTANCE_DIR / 'handovers.db'}")

SECRET_KEY = os.environ.get("SECRET_KEY")

# The very first Admin account, created once - only when no account
# exists yet. Every account after that is made by an Admin from the
# "Manage users" page, not from these variables.
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()
ADMIN_DISPLAY_NAME = os.environ.get("ADMIN_DISPLAY_NAME", "Admin").strip()

# What every account an Admin creates (or resets) starts with. Never
# chosen by the Admin per-account on purpose - always this one value -
# because the person is required to replace it with something only they
# know before they can do anything else.
DEFAULT_USER_PASSWORD = os.environ.get("DEFAULT_USER_PASSWORD") or "Abc@123456789"

def addresses(raw: str | None) -> list[str]:
    """One recipient or several, however they were written.

    Outlook separates addresses with semicolons and a mailto: URL with
    commas, and nobody filling in an environment variable should have to
    know which - so both are accepted here, and each side is handed the
    one it wants. Blanks and stray separators are dropped, so a trailing
    ";" is not an empty recipient.
    """
    return [piece.strip() for piece in re.split(r"[;,]", raw or "") if piece.strip()]


# Who the "this has been handed over" email is addressed to.
NOTIFY_TO = os.environ.get("HANDOVER_NOTIFY_TO", "").strip()
NOTIFY_NAME = os.environ.get("HANDOVER_NOTIFY_NAME", "Eng. Hegazy").strip()

# Where the two leaver messages go. Separate from NOTIFY_TO because they
# are a different conversation with a different team; either left unset
# just means that message opens with an empty To line, which is still
# faster than writing it out by hand.
EMS_TO = os.environ.get("HANDOVER_EMS_TO", "").strip()
LEAVER_TO = os.environ.get("HANDOVER_LEAVER_TO", "").strip()

# Whether the app may open drafts in Outlook itself rather than handing
# the browser a mailto: link.
#
#   auto   (default) only for a browser on this same machine, worked out
#          from the address the request came in on
#   always trust it wherever the request came from - for the case where
#          the app is reached by its machine's own network name or IP
#          rather than by localhost, where "auto" cannot tell
#   never  always use the mailto: link
#
# "always" is only ever right when this app is used from the machine it
# runs on: the drafts open next to the APP, so a colleague at another
# desk would get nothing and someone would get two windows they did not
# ask for.
OUTLOOK_DRAFTS = os.environ.get("HANDOVER_OUTLOOK", "auto").strip().lower()

# The laptop register. Beside the app by default, so on a machine where
# the folder is synced it simply appears - no download step, no second
# copy to go stale.
REGISTER_PATH = Path(os.environ.get(
    "HANDOVER_REGISTER_PATH", str(BASE_DIR / "laptop_register.xlsx")))
