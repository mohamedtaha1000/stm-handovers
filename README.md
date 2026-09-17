# STM Handover Documents

An internal Flask web application for generating STM's handover and
receipt Word documents from a browser form, replacing manual editing of
`.docx` files. Every generated document is logged to a searchable,
filterable history with export and print support.

This README covers setup and deployment. Related documentation:

- [HOW-IT-WORKS.md](HOW-IT-WORKS.md) — a plain-English tour of how the
  app actually behaves: the register, the resignation flow, the emails,
  the two name fields.
- [TODO.md](TODO.md) — what's still outstanding, in order of priority.
- [DECISIONS.md](DECISIONS.md) — judgment calls already made, and why,
  so they aren't re-litigated later.

## Contents

- [Overview](#overview)
- [Requirements](#requirements)
- [Running locally](#running-locally)
- [Configuration](#configuration)
- [Project structure](#project-structure)
- [Features](#features)
- [Managing accounts](#managing-accounts)
- [Deployment](#deployment)
- [Security notes](#security-notes)
- [Adding a new document type](#adding-a-new-document-type)

## Overview

Users sign in with their own account, choose a document type, fill in a
form, and download the completed `.docx`. Two roles: **Staff** does the
everyday work — make documents, record resignations, look people up, see
and download the full History; **Admin** can additionally edit or delete
any record and manage accounts. See
[Managing accounts](#managing-accounts). Supported document types:

| Document type              | Description |
|-----------------------------|--------------|
| Laptop handover             | Issuing a laptop to an employee |
| Laptop replacement          | Swapping an employee's laptop for a new one (records both the returned and issued device) |
| Keyboard & mouse handover   | Issuing a keyboard-and-mouse combo kit to an employee |
| Mouse handover              | Issuing a mouse (on its own) to an employee |
| Screen handover             | Issuing a monitor to an employee |
| Router handover             | Issuing a SIM/data router to an employee |
| Headset handover            | Issuing a headset to an employee |
| Printer handover            | Issuing a printer to an employee |
| Flash drive handover        | Issuing a USB flash drive to an employee |
| Hard disk handover          | Issuing an external hard disk to an employee |

Each document type is defined in a single registry
(`templates.py::TEMPLATES`), which drives the home page, the form for
each document type, and the underlying `.docx` template — adding a new
type does not require changing the Flask routes or HTML pages (see
[Adding a new document type](#adding-a-new-document-type)).

## Requirements

- Python 3.10+
- The packages listed in `requirements.txt`

## Running locally

From the project root:

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` (if not already present) and set:

```
SECRET_KEY=<a random long string>
ADMIN_USERNAME=<a username for the first Admin account>
ADMIN_PASSWORD=<a password for it>
```

Generate a secure `SECRET_KEY` with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Start the app:

```bash
python app.py
```

Open **http://127.0.0.1:5000** and log in with `ADMIN_USERNAME`/
`ADMIN_PASSWORD` — this creates that one Admin account automatically, the
only time this app ever creates an account without a person doing it
from "Manage users". From there, add an account for everyone else (see
[Managing accounts](#managing-accounts)). `.env` is loaded automatically
on startup — no environment variables need to be set manually in the
shell.

On first run this creates:
- `instance/handovers.db` — a local SQLite database of generated documents
- `generated/` — the generated `.docx` files, named
  `<Name> - <Document type> - <Date>.docx` (e.g.
  `Yasmin Mohamed - Laptop handover - 2026-09-10.docx`); if the same
  person generates the same document type again on the same day, `(2)`,
  `(3)`, etc. is appended instead of overwriting the earlier file

Both directories are excluded from version control (see `.gitignore`).

## Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes | Signs Flask session cookies. Any long random string. |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Yes, once | Create the very first Admin account, only when no account exists yet. Inert forever after that — every other account comes from "Manage users". |
| `ADMIN_DISPLAY_NAME` | No | What that first account is called (default `Admin`). |
| `DEFAULT_USER_PASSWORD` | No | The fixed starting password every Admin-created or reset account gets (default `Abc@123456789`). The account holder is forced to replace it on first login. |
| `DATABASE_URL` | No | Overrides the default SQLite database (e.g. a Postgres connection string) with no code changes required. |
| `PORT` | No | Port to listen on when run directly with `python app.py` (default `5000`). |
| `FLASK_DEBUG` | No | Off (`0`) by default. Set to `1` to turn on Flask's interactive debugger and auto-reload for local troubleshooting — never in production. |
| `HANDOVER_NOTIFY_TO` | No | Who the "this has been handed over" email is addressed to. Unset means the draft opens with an empty To line. |
| `HANDOVER_NOTIFY_NAME` | No | How that email greets its recipient (default `Eng. Hegazy`). |
| `HANDOVER_EMS_TO` | No | Who the leaver's EMS deactivation email is addressed to. |
| `HANDOVER_LEAVER_TO` | No | Who the leaver's resignation email is addressed to. |
| `HANDOVER_REGISTER_PATH` | No | Where the laptop register `.xlsx` is written (default `laptop_register.xlsx` beside the app). Rebuilt automatically on every change. |
| `HANDOVER_OUTLOOK` | No | `auto` (default), `always`, or `never` — whether the app may open email drafts directly in the local Outlook (HTML tables) instead of a `mailto:` link (plain text). Requires `pywin32` and classic desktop Outlook; see [HOW-IT-WORKS.md](HOW-IT-WORKS.md). |

If `ADMIN_USERNAME`/`ADMIN_PASSWORD` aren't set and no account exists
yet, the app still starts, but logs a warning — nobody can log in until
an Admin account exists one way or another.

## Project structure

```
settings.py           Every configurable value, read from the environment
templates.py          What documents exist and what each one asks for.
                       Data only - no imports, nothing to execute
ooxml.py               The Word engine: how to edit a .docx without
                       disturbing it. Names no document type
builders.py            One function per SHAPE of document (three of
                       them serve all ten types)
models.py              The tables (Handover, Departure, User), and the migration
documents.py           Form -> validated values -> filled .docx -> row
employees.py           Who a person is across their documents, and
                       what they still hold
asset_register.py      The laptop register spreadsheet
                       (Laptops and Leavers sheets)
email_html.py          How every email's tables look (HTML)
notify_email.py        The "this has been handed over" message
leaver_email.py        The two messages sent when someone leaves
outlook_com.py         Opening drafts in the local Outlook
app.py                 Flask application: routes and the web layer only

doc_templates/         One placeholder Word template per document type:
                         Laptop Handover Template.docx
                         Laptop Replacement Template.docx
                         Keyboard and Mouse Handover Template.docx
                         Mouse Receipt Template.docx
                         Screen Handover Template.docx
                         Router Handover Template.docx
                         Headset Handover Template.docx
                         Printer Handover Template.docx
                         Flash Drive Handover Template.docx
                         Hard Disk Handover Template.docx

templates/             HTML pages (login, picker, form, done, history)
static/style.css       Stylesheet
static/stm-logo.png    Logo, used in the header and favicon
requirements.txt       Python dependencies
Procfile               Start command for hosting platforms (gunicorn)
.env                   Local secrets (not committed to version control)
.env.example           Blank reference copy of .env, safe to commit
```

## Features

### Document generation

Each document type has its own form, generated from its field list in
`templates.py`. Required fields are validated server-side; mobile
number and National ID fields are additionally checked against a
regular expression (11-digit Egyptian mobile number, 14-digit national
ID) before a document is generated, with the specific problem shown
inline if a value doesn't match.

### History

Every generated document is recorded with the submitting user's name,
department, position, national ID (masked to the last 4 digits in list
views), document type, and the date and time it was generated. The
History page supports:

- **Search** — matches name, department, or position
- **Filters** — by document type, and by a from/to date range (based on
  generation date)
- **Pagination** — 50 records per page
- **Print** — a print-friendly view of the current filtered results,
  with navigation and controls hidden
- **Delete** — Admin only. Permanently removes a record and its
  generated `.docx` file, after a confirmation prompt.
- **Regenerate** — if a record's `.docx` goes missing from disk on its
  own (not via Delete), its row shows a "Regenerate" action that rebuilds
  the file from the record's own saved data. Open to everyone, same as
  Download.

Search, filters, and pagination are reflected in the URL, so a filtered
view can be bookmarked or shared.

Every signed-in person sees the full History and can download anything
in it. **Editing** (Handover documents and resignation records alike) is
Admin only, with no exception for a Staff member's own work.

### Resignation

A separate page records an employee leaving: it releases any laptop on
file back to `Held`, and opens the two leaver emails (EMS deactivation
and a resignation notice to the team) as drafts. See
[HOW-IT-WORKS.md](HOW-IT-WORKS.md) for how this interacts with the
register.

## Managing accounts

Admin only, from "Manage users" in the nav:

- **Add a user** — username, display name, role. There's no password
  field: every new account starts with the same fixed password
  (`DEFAULT_USER_PASSWORD`), and the account holder is forced to set
  their own the moment they log in, before they can do anything else.
- **Change role**, **deactivate/reactivate**, **reset password** (back
  to the same fixed starting password, forcing another change on next
  login).
- An Admin can't deactivate or demote themselves, and can't leave the
  team with zero active Admins.

Accounts are only ever created this way — there's no self-registration.

## Deployment

The application is a standard Flask app and can be deployed to any
platform that runs Python (Render, Railway, PythonAnywhere, an internal
server, etc.). Example using **Render**:

1. Push this folder to its own **private** GitHub repository —
   `doc_templates/` contains STM's internal document layouts and should
   not be made public.
2. On [render.com](https://render.com), create a **New → Web Service**
   and connect the repository.
3. Set the build and start commands:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app`
4. Set the environment variables `SECRET_KEY`, `ADMIN_USERNAME`, and
   `ADMIN_PASSWORD` (see [Configuration](#configuration)).
5. Deploy. Render provides a URL (e.g.
   `https://stm-handover.onrender.com`) to share with the team. Log in
   with the Admin account, then create everyone else's from "Manage
   users" — don't share the Admin login itself around.

**Note on free hosting tiers:** platforms like Render's free tier use an
*ephemeral* filesystem — the SQLite database and generated files can be
lost on restart or redeploy. For reliable long-term history, either:

- attach a persistent disk (available on paid plans), or
- point `DATABASE_URL` at a managed database (e.g. Render's free
  Postgres tier) — no code changes required.

Railway and PythonAnywhere follow a similar process: connect the
repository, set the required environment variables, and point the start
command at `gunicorn app:app`.

## Security notes

This application collects national ID numbers and other personal
employee data. Before deploying it somewhere reachable outside STM's
internal network, review the following:

- **Authentication** is per-person accounts with two roles (Staff,
  Admin) — see [Managing accounts](#managing-accounts). Passwords are
  hashed, never stored in plain text.
- **National IDs are masked** in list views (last 4 digits only). The
  full number is still present in the generated `.docx` file and
  briefly on the confirmation page immediately after generation, since
  it is required in the document itself. Every Staff member can download
  every document in History — including the full, unmasked ID inside it —
  not just ones they made themselves.
- **Change `SECRET_KEY`** from any placeholder value before deploying,
  and don't leave `ADMIN_PASSWORD` as whatever you first typed — sign in
  once, change it, and use `ADMIN_USERNAME`/`ADMIN_PASSWORD` only for
  that first account, never as an everyday login.
- Consider checking with STM's IT/security function before hosting real
  employee national IDs anywhere reachable from outside the office
  network, even behind a password. At minimum, use a host that provides
  HTTPS by default, and don't share any account's password outside the
  person it belongs to.
- If access is only needed from the office, hosting on an internal
  server reachable only over the company network/VPN removes the public
  exposure entirely.

## Adding a new document type

1. Obtain a real, filled-in example of the new document.
2. Sanitize it into a placeholder template (`FILL_*` placeholders
   replacing real values) and add it to `doc_templates/`.
3. Write a corresponding fill function in `templates.py`.
4. Add an entry to the `TEMPLATES` dict describing the document's label,
   template file, fill function, and field list.

No other file needs to change — the home page and the document's form
are generated from the registry.

---

Open work and possible future enhancements are tracked in
[TODO.md](TODO.md), not here, so there's a single current list rather
than two that can drift apart.
