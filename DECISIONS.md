# Decisions

A running log of judgement calls made on this project — things that
weren't a bug fix with one right answer, but a choice between real
tradeoffs. `TODO.md` says what's still open; this says what's already
been settled and why, so nobody re-litigates it from scratch later.

Newest first.

---

### 2026-09-17 — Added type hints; left Flask view functions loosely typed

Added PEP 484 type hints across the domain modules (`employees.py`,
`documents.py`, `asset_register.py`, `builders.py`, `templates.py`,
`leaver_email.py`, `email_html.py`, `notify_email.py`, `outlook_com.py`,
`settings.py`) and the `routes/*.py` modules, using built-in generics
(`list[str]`, `dict[str, Any]`, `str | None` - this project targets
Python 3.10+, so no `typing.List`/`Optional` needed).

**Deliberately left unannotated:**
- Flask view functions' own return types (e.g. `def login():`, `def
  history():`) - a view can return a rendered template (`str`), a
  redirect, a dict (JSON), or a `(dict, status_code)` tuple depending on
  the branch, and forcing a `flask.Response | str | ...` union onto
  every one of them would be noise, not information. Their URL path
  parameters ARE typed (`record_id: str`, `user_id: str`, ...) since
  those are always the same one thing: the UUID string from the route.
- `models.py`'s `db.Column(...)` class attributes - typing those
  properly needs SQLAlchemy 2.0's `Mapped[]`/`mapped_column()` style,
  which is a separate, bigger migration this pass wasn't trying to do.
- `ooxml.py` and `fill_logic.py` entirely - low-level OOXML/python-docx
  manipulation where a type would mostly be `Element`/`Any` noise, and
  `fill_logic.py` is already excluded from linting for the same reason.

**Verified**: `python -m py_compile` on every changed file, `ruff check
.` clean across the whole repo, and the full `pytest` suite (see below)
still green - type hints are additive by construction, but this
confirms nothing besides annotations actually changed.

### 2026-09-17 — CI runs on Ubuntu, not Windows, and never touches Outlook

`.github/workflows/ci.yml` runs `ruff check .` and `pytest` on every
push/PR against `master`, on `ubuntu-latest` rather than `windows-latest`
- even though this app is deployed on Windows and its one Windows-only
feature (`outlook_com.py`, opening drafts directly in a local Outlook via
`pywin32`/COM) can only really run there. Two reasons this is still the
right call for CI specifically:

- `outlook_com.py` already guards its own `import win32com.client`
  behind a `sys.platform != "win32"` check and does it lazily, inside
  the one function that needs it - so the module imports cleanly
  anywhere, and nothing in the test suite (which sets
  `HANDOVER_OUTLOOK=never`, see the test-suite entry below) ever reaches
  that code path regardless of OS.
- Everything CI actually exercises - Flask, SQLAlchemy/sqlite,
  python-docx document generation - is genuinely cross-platform, so
  `ubuntu-latest` runs it correctly and considerably faster/cheaper than
  a Windows runner would.

The trade-off, accepted deliberately: CI gives no coverage at all for
the Outlook-COM code path itself. That was already untested by anything
automatable (it drives a real desktop Outlook installation), so this
isn't a regression - just naming the gap rather than pretending
`windows-latest` would have closed it.

While wiring this up, `pip install -r requirements-dev.txt` was found to
fail outright on this dev machine: `requirements.txt` pinned
`pywin32==306`, which has no wheel for Python 3.13 (this machine's
version) - only 307 and up do. Fixed by bumping the pin to `312`,
matching the version already installed and working in this environment.
Not a judgement call, just recorded here since it was a real, silent
blocker to a fresh `pip install` that this session's CI dry-run is what
actually surfaced it.

### 2026-09-17 — First automated test suite (pytest)

Added `tests/` covering the things this app cannot afford to get wrong
silently: login/logout, the forced first-password-change flow, document
create/edit/delete, the resignation flow, admin user management, and the
Staff/Admin permission boundary from the RBAC work above. 37 tests, all
against real logic (real python-docx generation against the real
`doc_templates/*.docx` files, a real temporary sqlite database) rather
than mocks - consistent with how this project was already being verified
by hand throughout this session.

**Fixture strategy, and why it looks the way it does:** this app has no
factory pattern - `settings.py` reads every environment variable at
IMPORT time, so `tests/conftest.py` sets `DATABASE_URL`,
`HANDOVER_REGISTER_PATH`, `SECRET_KEY`, `ADMIN_USERNAME`/`ADMIN_PASSWORD`
etc. as the very first thing it does, at module level, before `app` or
`models` gets imported by anything. `HANDOVER_OUTLOOK=never` is set for
the same reason: without it, a resignation test would reach
`outlook_com.open_drafts()`, which talks to a real Outlook via COM - the
whole test suite would either hang or fail on a machine (or a Linux CI
runner) without Outlook installed. `settings.GENERATED_DIR` is
reassigned after import (there's no env var for it, only for the
register) per settings.py's own documented pattern, so generated .docx
files land in a temp folder instead of the real `generated/`.

**One behavioural surprise the tests caught immediately:** `abort(403)`
in this app never reaches the browser as an actual 403 - `app.py`'s own
`@app.errorhandler(403)` turns it into a 302 redirect to `/` with a
flash message (deliberately, so a browser lands somewhere instead of
stalling on an error page). Every permission-boundary test asserts
against that real redirect+flash contract (via a shared
`assert_forbidden()` helper) rather than a bare status code, which is
what an untested assumption would have gotten wrong.

**Database reset strategy:** `db.drop_all()` / `db.create_all()` before
every single test, rather than wrapping each test in a rolled-back
transaction - simpler to reason about, and fast enough on a temporary
sqlite file that the extra cost never mattered in practice (the whole
suite runs in well under a minute).

### 2026-09-17 — Adopted ruff for linting; skipped blanket auto-formatting

Added `ruff` (via `requirements-dev.txt` + `pyproject.toml`) as the
project's linter, on the standard rule set plus import-sorting,
modernisation, and bugbear (`select = ["E", "F", "I", "UP", "B"]`), with
`E501` (line-too-long) ignored so the codebase's prose-style comments and
docstrings can keep running past a strict wrap column on purpose.

`ruff check .` found 37 issues. The 29 safe ones (stale
`# -*- coding: utf-8 -*-` declarations, unsorted imports, a couple of
genuinely unused imports) were auto-fixed. The remaining 8 needed real
judgement, not a blind fix:

- **`B905` (`zip()` without `strict=`), 6 occurrences** (`ooxml.py` x5,
  `asset_register.py` x1): each was read individually rather than
  patched mechanically. Where both sides of a `zip()` are built from the
  same source and are always the same length (e.g. `zip(runs, texts)`
  where `texts` is derived from `runs` on the line above), `strict=True`
  was added - it now fails loudly if that invariant is ever broken.
  Where the lengths are *expected* to differ - `zip(row.cells, widths)`
  when a Word table has merged cells, and the classic
  `zip(mine, mine[1:])` pairwise-consecutive idiom in
  `asset_register.py` - `strict=False` was set explicitly instead, with
  a comment explaining why, so the choice reads as deliberate rather
  than an oversight the linter will keep flagging.
- **`B007`** (unused loop variable in `routes/documents.py`): the loop
  only used the dict's values, so it was rewritten as
  `for problems in errors.values()` rather than renaming the unused key
  to `_template_id`.
- **`UP028`** (`ooxml.py`): a `for pp in walk_table(table): yield pp`
  loop collapsed to `yield from walk_table(table)` - behaviourally
  identical, one line instead of two.

**`ruff format` (the auto-formatter half of the same tool) was
deliberately NOT run project-wide.** `ruff format --diff .` produces
~2,700 lines of changes, and sampling them (`templates.py`) showed it
collapsing hand-aligned multi-line dicts and wrapped string
concatenations - arranged that way on purpose, for readability - into a
denser, harder-to-read shape, plus wholesale quote-style churn. That
tradeoff (a large diff, disconnected from any actual bug, that makes
some deliberately-formatted code worse to read) isn't worth it just to
have "a formatter was run." Linting for real mistakes stays enforced;
whole-file reformatting was left off.

### 2026-09-17 — Routes split into `routes/` by feature, not Blueprints

`app.py` had grown to 1,580 lines holding all ~40 routes - auth,
documents, resignation, and admin all interleaved. Options considered:
leave it; split by technical layer; split by feature into Flask
Blueprints (the framework's own native answer to this).

**Decided:** split into `routes/auth.py`, `routes/documents.py`,
`routes/resignation.py`, `routes/admin.py` (plus `routes/common.py` for
the couple of things more than one of them needs: rebuilding the
register, opening Outlook drafts) - but **not** as Blueprints.

**Why not Blueprints, despite being the "idiomatic" choice:** Flask
unconditionally namespaces every Blueprint route as
`blueprintname.viewname` - there is no way to opt out, even by passing
an explicit `endpoint=`. Adopting them would have meant updating every
`url_for()` call across every template (~15 files) and every
`request.endpoint` comparison, for a change that was supposed to be
purely organisational. This was discovered by inspecting the actual
registered URL map after a first attempt with Blueprints, not assumed -
worth remembering if the instinct to reach for Blueprints comes up
again later.

**What was used instead:** each `routes/*.py` module does `from app
import app` and registers routes directly with the ordinary
`@app.route(...)`, exactly as `app.py` did before. This works because
`app.py` creates `app` *before* importing the route modules - by the
time each one runs `from app import app`, the object already exists in
the partially-initialised `app` module, so the "circular" import
resolves cleanly. Net effect, confirmed by diffing the before/after URL
maps line for line: identical routes, identical endpoint names, zero
template changes.

**Verified** against a full copy of production data: every route across
all four modules, and the complete write-paths for creating a document,
recording a resignation, and creating an admin account.

### 2026-09-17 — Every record id is a UUID, not a sequential integer

`Handover`, `Departure`, and `User` used auto-incrementing integer
primary keys (1, 2, 3, ...), used directly in URLs like `/file/8`. A
sequential id is guessable and enumerable - stepping through
`/file/1`, `/file/2`, ... would eventually surface every document, real
national IDs included.

**Decided:** all three switch to UUID primary keys, chosen for
consistency across the whole app rather than only the two PII-bearing
ones (`User` gains little security benefit here since `/admin/users/*`
is already Admin-only, but a mixed scheme - some resources UUID, some
still integer - would be a needless inconsistency).

**Migration:** SQLite can't change a column's type or its
PRIMARY KEY/FOREIGN KEY constraints in place, so this isn't an
`ALTER TABLE ADD COLUMN` like every migration before it - each table is
renamed aside, recreated from the current (UUID) model, and every row
copied back in with a fresh id; `Handover.created_by_user_id` and
`Departure.recorded_by_user_id` are rewritten to point at the new user
ids as they go. Runs automatically, once, the first time the app starts
against a database that still has the old integer ids - verified
end-to-end against a full copy of the real database (all rows, all
foreign keys, all indexes intact; idempotent on a second run) before
ever running it for real. See `HOW-IT-WORKS.md`'s "Things that will
surprise you" for the one real consequence: an old bookmarked URL like
`/edit/8` stops resolving to anything afterward.

Found and fixed two problems only a real-data test run surfaced:
renaming a table in SQLite leaves its indexes registered under their
original names, colliding with recreating them fresh; and the live
`handover` table still carried columns (`mobile`, `serial`, `model`,
`cpu`, ...) from before `fields_json` existed, long abandoned by the
model but never dropped (this codebase's migrations only ever add
columns) - a plain `SELECT *` copy would have tried inserting into
columns the rebuilt table no longer has. Both are handled generically
rather than patched around this one instance.

### 2026-09-17 — New features get their own branch, not straight onto `master`

Work so far (including RBAC) was committed directly to `master`. Going
forward, that changes.

**Decided:** every new feature is built on its own branch, merged into
`master` when it's done and tested, rather than developed in place on
`master`. Keeps `master` always in a working, deployable state, and
gives each feature a clean, revertable unit instead of a tangle of
commits mixed in with everything else that happened to land the same
day. Small fixes and doc updates can still go straight to `master`; this
is about actual features.

### 2026-09-17 — History opened up to everyone; editing narrowed to Admin-only

Revises part of the RBAC decision below, from the same day. Staff's
History was scoped to only the documents they created — which also meant
a Staff member could edit their own records, and a whole "Owner account"
mechanism existed to attribute records to accounts for that purpose.

**Decided:** every Staff member now sees and can download the **entire**
History, not just their own. In exchange, editing a document or
departure record is now Admin-only, full stop — the "edit your own"
exception is gone. Regenerating a missing file also no longer checks
ownership, since it's a download-adjacent recovery action, not an edit.

**Consequence:** `created_by_user_id`/`recorded_by_user_id` no longer
gate anything. Left in place as plain audit data (still stamped on
creation, still more reliable than the free-typed `created_by` text
column for knowing who actually made a record) but the "Owner account"
dropdown on the edit forms was removed — it no longer changed what
anyone could do, so keeping it would have been misleading. Nothing
reads these columns for permission decisions anymore.

### 2026-09-17 — Role-Based Access Control: real accounts, two roles, History scoped to owner

Replacing the single shared `TEAM_PASSWORD` (anyone could type any
display name and act as anyone) with actual access control. Several
things were decided together here, through a back-and-forth rather than
upfront:

**Real individual accounts, not a shared password with a role picker.**
Roles only mean something if login identifies a real person — otherwise
"Admin" is just a second password everyone learns.

**Two roles only: Admin, Staff.** Not three-tier (Admin/Editor/Viewer) —
this team's day-to-day work doesn't split that way.

**Admin-only, unconditionally, regardless of who created a record:**
deleting a `Handover` or `Departure` record (Staff can never delete
anything, full stop — not even their own), editing a record someone
*else* created, and managing accounts. ~~Staff can still edit their own
records.~~ **Superseded the same day** — see the entry above: editing is
now Admin-only with no exception.

**History is the only place ownership gates *visibility*, not just
action.** ~~A Staff member's History page lists, downloads, and can
Regenerate only documents they created.~~ **Superseded the same day** —
see the entry above: History is fully open to Staff now, only editing
stayed Admin-gated. Still true as originally written: deliberately
**not** extended to the equipment/employee lookup, the laptop register,
or Resignation's own list — those exist specifically to see across
everyone (e.g. checking what a leaving employee still holds, even if a
different Staff member issued it originally), so scoping them the same
way would break the app.

**Pre-existing records belong to nobody by default.** A free-typed name
from the old shared-password era can't be reliably matched to a real
account (two people could've typed the same name; spelling varies), so
every record made before this shipped had no verified owner. ~~An Admin
explicitly assigns it to the right account via an "Owner account" field
added to the existing edit forms.~~ **Superseded the same day** — that
field is gone; ownership stopped gating anything, so there was nothing
left to assign it *for*.

**Accounts are Admin-created only, and always start with the same fixed
password** (`Abc@123456789` by default), never one an Admin picks per
person — with a forced "set your own password" screen before the account
can do anything else, checked on every request so it can't be skipped by
bookmarking a different URL. Resetting a password reapplies the same
rule rather than an Admin choosing a new one for someone. The one
exception is the bootstrap Admin account, created once from
`ADMIN_USERNAME`/`ADMIN_PASSWORD` in `.env` when no account exists yet —
a real password someone chose during setup, so it isn't forced through
the change screen.

### 2026-09-17 — New repo keeps full git history

Migrating off the public `github.com/mohamedtaha1000/Handovers` to a new
private repo, `stm-handovers`. Considered starting with a single fresh
commit (no old history at all, so nothing old to leak) versus repointing
`origin` and pushing the existing history as-is.

**Decided:** keep full history, just repoint `origin` at the new URL.
Chosen knowingly — this carries every old commit, including whichever one
originally had an employee's real name, mobile number and national ID in
a template, into the new repo too. The new repo is private, which was
judged sufficient.

### 2026-09-17 — No SMTP for colleague emails; keep the mailto fallback

Colleagues opening the app from their own desk get a `mailto:` draft
(correct details, but a bulleted list rather than the HTML tables Outlook
gets when the app talks to it directly), because nothing running on the
server can reach another PC's Outlook.

**Decided:** accept it as-is. Sending over SMTP instead would make every
outgoing email identical and nicely formatted, but it would also send the
instant the button is pressed, with nobody reviewing it in Outlook first.
Review-before-send matters more than formatting consistency. No code
change.

### 2026-09-17 — Employee code added to leaver emails, but optional

The two leaver messages (EMS deactivation, resignation) didn't include
the employee code, even though the form collects it.

**Decided:** add it to both messages, right after the name. Left
optional on the form rather than required — not everyone resigning has a
code to hand, or the person filling the form may not know it — so it
prints blank rather than blocking either the "Mark as left" button or the
two single-email links.

### 2026-09-17 — Lost `generated/*.docx` files are recovered by search, not silently

A generated Word document can occasionally go missing from disk on its
own (deleted from the folder by hand, or an interrupted OneDrive sync)
while its database record is still there. First built as a silent
auto-rebuild on download; rejected.

**Decided:** recovery is a deliberate, visible action instead. History
flags the affected row (an amber "Regenerate" icon in place of Download)
so it turns up when you search for that person, and rebuilding only
happens when that button is clicked. `History → Delete` is unchanged and
still removes the row and file together, for good — this only covers a
file going missing some other way. Regenerating does not touch
`updated_by`/`updated_at`, since nothing about the record changed.
