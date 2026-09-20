#!/usr/bin/env python3
"""
routes/common.py
=================
Web-layer helpers more than one blueprint needs, so they don't belong
to any single one of them: rebuilding the laptop register (documents
change it by generating; resignations change it by releasing a laptop),
and opening Outlook drafts (the handover notification and the two
leaver emails both go through the same machine-detection rules).

Everything route-specific enough to belong to just one blueprint lives
with the routes that use it instead.
"""

from typing import Any

from flask import current_app, flash, request

import asset_register
import outlook_com
import settings
from employees import departures_by_identity, register_rows


def refresh_register() -> str | None:
    """Rebuild the sheet. Returns None on success, or a sentence saying
    why not.

    This is called from the middle of generating a document, so it must
    never raise: a register that could not be written is a nuisance, and
    losing the document that was just signed is not. The usual cause on
    Windows is the file being open in Excel, which locks it - worth
    saying plainly rather than reporting as an error.
    """
    try:
        asset_register.write_workbook(register_rows(), settings.REGISTER_PATH,
                                      departures=departures_by_identity())
        return None
    except PermissionError:
        return (f"The laptop register ({settings.REGISTER_PATH.name}) is open in Excel, "
                f"so it could not be updated. Close it and the next document "
                f"will bring it up to date.")
    except Exception as problem:            # noqa: BLE001 - never block the document
        current_app.logger.exception("register rebuild failed")
        return f"The laptop register could not be updated: {problem}"


def register_updated() -> None:
    """Rebuild, and flash only if something went wrong. Success is
    silent: it happens on every single document and a message saying so
    every time would be noise the person learns to ignore."""
    problem = refresh_register()
    if problem:
        flash(problem, "info")


def open_drafts_here(drafts: list[dict[str, Any]]) -> tuple[bool, str]:
    """Put these drafts in front of the person. Returns (opened, reason)
    - reason being why not, for the page to show.

    Only for a browser on this machine: the drafts open in the Outlook
    the APP is running next to, so a colleague opening this page from
    their own desk would otherwise pop windows up on somebody else's
    screen. They get the mailto: fallback instead, which opens on theirs.
    """
    setting = settings.OUTLOOK_DRAFTS
    if setting == "never":
        return False, ("Opening drafts in Outlook is switched off "
                       "(HANDOVER_OUTLOOK=never in your .env file).")
    if setting != "always" and request.remote_addr not in ("127.0.0.1", "::1"):
        # Reached over the network. That is usually a colleague at
        # another desk, but it is also what it looks like when this app
        # is opened on its OWN machine by its network name or IP rather
        # than localhost - which "auto" has no way to tell apart. Hence
        # the address in the message, and the setting to override it.
        return False, (f"This page was opened from {request.remote_addr} rather "
                       f"than from this machine, so the draft would appear on "
                       f"this app's Outlook rather than yours. If this IS the "
                       f"same machine, set HANDOVER_OUTLOOK=always in your .env "
                       f"file and restart.")
    problem = outlook_com.open_drafts(drafts)
    return problem is None, problem or ""
