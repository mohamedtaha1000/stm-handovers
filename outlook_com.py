# -*- coding: utf-8 -*-
"""
outlook_com.py
==============
Opening drafts in Outlook itself, so one press can open two.

A mailto: link is the portable way to open a message and stays the
fallback everywhere this does not work. But a browser hands the mail
client at most ONE mailto per click and drops the rest without a word:
the limit is one per gesture, not one per moment, so no delay between
them helps. Two drafts from one press is simply not something a mailto
link can do.

Outlook has no such limit. This tool runs on the same machine as the
Outlook it is opening - that is how it is used - so it can ask Outlook
directly for as many drafts as it likes, from one press, and without
the roughly 2,000 characters a mailto URL is held to.

It also takes an HTML body, so the employee details arrive as a table
rather than as a bulleted list, and the sender's own signature is kept
underneath instead of being written over.

Nothing is ever sent. Display() opens the compose window exactly as the
mailto link does, and a person still reads it and presses Send.

This module knows about Outlook and nothing else: no Flask, no request,
no idea what a leaver is. It is handed a list of {to, subject, body} and
either opens them all or says, in one sentence, why it could not - so
the caller can fall back rather than guess.
"""
import logging
import sys

log = logging.getLogger(__name__)

OL_MAIL_ITEM = 0    # Outlook's constant for "a new mail message"
OL_DISCARD = 1      # ...and for closing one without saving it


def under_signature(existing, html):
    """Put our message at the top of the body Outlook has already made,
    so whatever is down there - the sender's signature - stays.

    Outlook drops the signature in when the window opens, and assigning
    HTMLBody replaces the lot. So the body is read back and ours is
    spliced in just after <body>, rather than written over it. A body
    with no <body> tag at all is the odd case, and ours simply goes
    first.
    """
    opening = existing.lower().find("<body")
    if opening == -1:
        return html + existing
    closes = existing.find(">", opening)
    if closes == -1:
        return html + existing
    return existing[:closes + 1] + html + existing[closes + 1:]


def unavailable():
    """Why this machine cannot open drafts directly, or None when it can.

    A sentence rather than a flag, because the caller shows it to the
    person: "it only opened one" is a puzzle, "install pywin32" is a
    thing to do.
    """
    if sys.platform != "win32":
        return ("Outlook can only be opened directly on Windows, and this "
                f"app is running on {sys.platform}.")
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        return ("Opening both at once needs the pywin32 package: run "
                "'pip install pywin32' in the Python this app runs in, "
                "then restart it.")
    return None


def open_drafts(drafts):
    """Open every draft in Outlook. Returns None, or a sentence saying
    why none of them opened.

    All of them or none of them, deliberately: a half-opened pair is
    worse than none at all, because the caller's fallback can open both
    and nobody can tell by looking which half is already there.
    """
    problem = unavailable()
    if problem:
        return problem

    import pythoncom
    import win32com.client

    # Every request is served on its own thread, and COM has to be
    # started on the thread that uses it.
    pythoncom.CoInitialize()
    try:
        try:
            outlook = win32com.client.Dispatch("Outlook.Application")
        except Exception:
            log.exception("Outlook did not answer")
            return ("Outlook did not answer. It may still be starting up, "
                    "or this may be the new Outlook, which cannot be "
                    "opened this way.")

        opened = []
        try:
            for draft in drafts:
                item = outlook.CreateItem(OL_MAIL_ITEM)
                item.To = draft.get("to", "")
                item.Subject = draft.get("subject", "")
                # Shown BEFORE the body is written, and not modal (which
                # would hold this request open until the window closed).
                # Outlook only adds the sender's signature when the
                # window opens, and writing a body first would leave no
                # signature to add it to.
                item.Display(False)
                html = draft.get("html")
                if html:
                    item.HTMLBody = under_signature(item.HTMLBody or "", html)
                else:
                    item.Body = draft.get("body", "")
                opened.append(item)
        except Exception:
            log.exception("A draft could not be opened")
            for item in opened:
                try:
                    item.Close(OL_DISCARD)
                except Exception:
                    pass
            return "Outlook was reached but would not open the drafts."
    finally:
        pythoncom.CoUninitialize()
    return None
