# How the Handover app works

A plain-English tour of what this app is, where everything lives, and the
handful of things that are surprising until someone tells you. Written
for the person who maintains it — which is you.

`README.md` is older than this file and still describes a `fill_logic.py`
that no longer exists. Trust this one.

---

## What it does, in one paragraph

You fill in a form; it writes the official Arabic Word document, saves a
copy, records who has which laptop, and opens the emails that go with it.
Ten document types, one register spreadsheet, three emails. Nothing is
sent automatically — every email opens as a draft for you to read and
press Send.

---

## The three places data lives

This is the thing to understand first, because almost every confusing
moment traces back to it.

| Where | What it is | Who writes it |
|---|---|---|
| `instance/handovers.db` | **The truth.** Every document and every resignation. | The app |
| `generated/*.docx` | The Word files, one per document | The app |
| `laptop_register.xlsx` | **A report.** Rebuilt from the database on every change | The app |

The spreadsheet is *output*, not storage. Anything you type into it is
overwritten the next time a document is made. To change what it says,
change the data:

- a row on the **Laptops** sheet → History → the pencil on that document
- a row on the **Resignation** sheet → Resignation page → "Already recorded" → the pencil

If a person has handover documents on file, those documents describe them
on the register, so their name is corrected on the document rather than
on the resignation record. The list says which of the two applies.

---

## The pages

| Page | What it is for |
|---|---|
| **New handover** | Pick a document type, or tick several to fill one form once |
| **History** | Everything ever made: search, correct, download, print, get the Excel |
| **Resignation** | Record a leaver, release their laptop, open both leaver emails, and correct past records |

Every button and icon explains itself on hover **and on keyboard focus** —
that is what `static/tooltips.js` does, driven by a `data-tip` attribute.
Adding an explanation anywhere is writing `data-tip="…"` on the element.

---

## The emails

Three of them, all opened as drafts, never sent by the app:

1. **Handover notification** — to Eng. Hegazy, after a document is made
2. **EMS deactivation** — asks for the FortiClient code when someone leaves
3. **Resignation** — tells the team someone has gone

Each is written **twice, from one description of its contents**:

- **HTML**, where the details are ruled tables. Used when the app can talk
  to Outlook directly.
- **plain text**, where they are a bulleted list. Used by the `mailto:`
  link, which cannot carry anything else.

`email_html.py` decides how every table looks, so all three messages
match. Tests assert the two renderings never disagree.

### Why a draft sometimes arrives as plain text

The app opens drafts by talking to **the Outlook running next to itself** —
the one on the machine the app runs on. Three things can stop that, and
the button says which on screen rather than failing silently:

- `pywin32` is not installed (`pip install pywin32`, then restart)
- the page was opened from another computer — the draft would appear on
  *this* machine's Outlook, not theirs, so it refuses and falls back
- it is the new Outlook, which does not allow this at all

A colleague browsing in from their own desk will always get the plain-text
fallback. That is correct: nothing a server can do reaches another PC's
Outlook.

If you reach the app by its IP or machine name rather than `localhost`,
the app cannot tell you apart from a colleague — set
`HANDOVER_OUTLOOK=always` in `.env` for that case only.

---

## The two names

Every employee is recorded twice: **Full name (Arabic)** and **Name in
English**.

They cannot be derived from each other. Arabic script does not write short
vowels, so محمد is Mohamed, Mohammed, Muhammad and Mohammad all at once,
and no library can tell which spelling a person actually uses. So both are
asked for once and carried forward by the lookup.

- The **documents** print the Arabic name — they are Arabic documents.
- The **emails** use the English one — they are English emails.
- The **register** has a column for each.

Each box refuses the other's script, checked in the browser *and* on the
server.

---

## The modules

Flask appears in exactly two files (`app.py` and `models.py`). Everything
else is plain Python that can be read, tested and understood on its own.

| File | Lines | What it knows about |
|---|---|---|
| `settings.py` | 83 | Every configurable value, read from `.env` |
| `templates.py` | 412 | The registry: the ten document types and their fields |
| `ooxml.py` | 1228 | The Word engine. Names no document type |
| `builders.py` | 238 | Three shapes that serve all ten types |
| `models.py` | 128 | The two tables, and the migration that adds columns |
| `documents.py` | 245 | Form → values → `.docx` → history row |
| `employees.py` | 216 | Identity, duplicates, lookups, register rows |
| `asset_register.py` | 291 | The Excel file: both sheets |
| `email_html.py` | 68 | How every email's tables look |
| `notify_email.py` | 291 | The handover notification |
| `leaver_email.py` | 223 | The two leaver messages |
| `outlook_com.py` | 133 | Talking to Outlook. Knows nothing else |
| `app.py` | 1334 | Routes and the web layer only |

`doc_templates/` holds the ten Arabic `.docx` templates. The app fills
`FILL_*` placeholders in them; it never writes a document from scratch.

---

## Things that will surprise you

**The register is rebuilt, not edited.** Covered above, but it is the
single most common confusion.

**"Rebuild" on the History page** exists for when that rebuild could not
happen — almost always because the file was open in Excel, which locks it
on Windows. Downloading also rebuilds first, so the copy you download is
always current.

**Resigning is a fact about a person, not a laptop.** Someone with no
handover document on file is still recorded, and still appears on the
Resignation sheet. (This was a bug once: the departure was only written if
a laptop matched, so people vanished entirely.)

**Removing a resignation record un-resigns them** — anything they held
goes back to `Held`, because that record was the only reason it said
`Left`.

**The employee code is the identity.** It is how the app knows two
documents are the same person, so a resignation filed under the right code
finds everything they were ever issued.

**Laptop model is a closed list; department is not.** New departments get
created, so that box takes anything. Laptop models are E14 and E16 — edit
`LAPTOP_MODELS` in `templates.py` to add one. Departments live beside it
in `DEPARTMENTS`.

**A document made before a list existed keeps its value.** Editing an old
record with an off-list model is allowed to save unchanged, so tightening
a list never makes old documents read-only.

---

## Running it

```
pip install -r requirements.txt
python app.py
```

Then `http://localhost:5000`. Settings live in `.env` — see
`.env.example`, which documents every one.

---

## Known risks

**The whole app lives inside OneDrive.** Two consequences:

1. `instance/handovers.db` contains **full national ID numbers** and is
   synced to the cloud.
2. Edits have been silently reverted here — a file written to disk was
   put back to its old contents by sync, twice, while this app was being
   worked on. If a change ever seems not to take effect, suspect this
   before suspecting the code.

Moving the folder out of OneDrive resolves both.

**`app.py` still runs with `debug=True` and `host="0.0.0.0"` by default.**
That is a debugger exposed to the whole network. Fine on a trusted LAN,
not fine beyond it.
