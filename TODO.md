# TODO

Everything still outstanding, roughly in the order it matters. Each item
says what it is, why it matters, and what "done" looks like.

---

### 2. ~~Decide what to do about the public GitHub repository~~ — decided: fresh repo

Rather than rewrite history on `github.com/mohamedtaha1000/Handovers`, the
plan is to delete it and create a new one — a clean history has nothing
old to leak, which is simpler than scrubbing commits. You're handling the
GitHub delete/create yourself.

Along the way, `.gitignore` had an old unresolved merge conflict actually
committed into it (literal `<<<<<<<`/`=======`/`>>>>>>>` markers) — fixed,
merged cleanly, `.env`/`instance/`/`generated/*.docx` still ignored.

Also handled: `generated/*.docx` (the real per-employee documents with
PII) was already gitignored and never pushed — that part needed no repo
change. What it did need was a way back if one of those files is ever
lost some other way — deleted from the folder by hand, or an interrupted
OneDrive sync — while its record is still there: History now shows a
"Regenerate" action (amber refresh icon) in place of Download for exactly
that row, which rebuilds the `.docx` from the record's own stored
`fields_json` on request. Deliberately not automatic on download — History
→ Delete still permanently removes the row and file together, unchanged.
Tested by generating a document, deleting its file from `generated/`, and
regenerating it from History — it came back byte-identical in size,
without touching `updated_by`/`updated_at` (this recovers a record, it
does not edit one). This only covers `generated/` — the ten blank
templates in `doc_templates/` are hand-authored and have no database
representation, so losing those is still unrecoverable; back them up
separately if that ever matters.

### 3. ~~Turn off the debugger~~ — done

The default in `app.py` is now `FLASK_DEBUG=0`; the interactive debugger
no longer opens by default on `0.0.0.0`.

---

## Housekeeping

### 4. Delete `fill_logic.py`

77 KB, still in the folder, imported by nothing. It is the old
single-file version from before the code was split up, and it will
mislead whoever reads the folder next — including you in six months.

**Done when:** the file is gone and the app still starts.

### 5. ~~Replace `README.md`~~ — done

Now points at `HOW-IT-WORKS.md` for behavior, and its project structure
and features list include the resignation/leaver flow and the files that
support it.

---


## Decisions still open

### 8. ~~Colleagues get plain-text emails~~ — decided: accepted as is

Anyone opening the app from their own desk gets the `mailto:` fallback —
correct addresses and details, but a bulleted list instead of tables.
Decided against sending over SMTP instead: that would mean every email
goes out immediately with no human reviewing it in Outlook first, which
matters more than the formatting. No code change.

### 9. ~~The employee code is not in the leaver emails~~ — done

Added to both messages, right after the name. Left optional on the form —
not everyone has one to hand — so it prints blank rather than blocking
either "Mark as left" or the two single-email links.

### 10. Two forms are nearly page-full

`laptop_handover` and `printer_handover` have very little room left. If
Arabic text is ever added to either, expect a second page — the fix is to
find the space rather than let it spill.

### 11. ~~Individual per-user logins and Role-Based Access Control~~ — done

Replaced the single shared team password with real accounts (two roles:
Admin, Staff). Every signed-in person sees and downloads the full
History; Admin-only: editing any document or resignation record,
deleting anything, managing accounts. See `DECISIONS.md` for the shape
of it and why, and `HOW-IT-WORKS.md`'s "Accounts and roles" section for
day-to-day behavior.

### 12. ~~Sequential integer ids in URLs~~ — done

`Handover`, `Departure`, and `User` now use UUID primary keys instead of
guessable, enumerable integers. Migrated automatically on first startup
against an old database — see `DECISIONS.md` for the migration itself
and what it had to work around.

---

## Ideas, not commitments

- **A backup of the database.** There is one copy of
  `instance/handovers.db`. A scheduled copy elsewhere would be cheap.
- **Search the Resignation list.** Fine at a dozen records; a search box
  would help at a hundred.
- **Bold headings in the handover notification.** Now possible for the
  Outlook path, since it takes HTML.
- **Production-hardening measures** — rate limiting, CSRF tokens — worth
  adding if this is ever exposed beyond the office network.
