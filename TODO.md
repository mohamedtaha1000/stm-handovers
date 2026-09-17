# TODO

Everything still outstanding, roughly in the order it matters. Each item
says what it is, why it matters, and what "done" looks like.

---

### 2. Decide what to do about the public GitHub repository

`github.com/mohamedtaha1000/Handovers` is **public** and holds this app's
source, the ten Arabic `.docx` templates and the README. `.env` and
`instance/` are gitignored, so the password and the database are not in
it — but an employee's real name, mobile number and national ID were in a
template early on and may still be in the git history.

Making the repository private does not retract anything already cloned or
indexed, so this is a judgement call about what is acceptable, not a
technical fix.

**Done when:** you have decided, and either made it private, rewritten
the history, or consciously accepted it.

### 3. Turn off the debugger

`app.py` ends with:

```python
debug = os.environ.get("FLASK_DEBUG", "1") == "1"
app.run(debug=debug, host="0.0.0.0", port=...)
```

The default is **on**, and `0.0.0.0` means every machine on the network
can reach it. Flask's debugger offers an interactive Python console on
any error — to whoever hits the error.

**Done when:** `FLASK_DEBUG=0` is in `.env`, or the default in `app.py` is
flipped to `"0"`.

---

## Housekeeping

### 4. Delete `fill_logic.py`

77 KB, still in the folder, imported by nothing. It is the old
single-file version from before the code was split up, and it will
mislead whoever reads the folder next — including you in six months.

**Done when:** the file is gone and the app still starts.

### 5. Replace `README.md`

It describes a `fill_logic.py::TEMPLATES` registry that no longer exists,
and predates the register, the resignation flow, the emails and the two
name fields. `HOW-IT-WORKS.md` is the current explanation.

**Done when:** the README either points at `HOW-IT-WORKS.md` or is
rewritten to match reality.

---


## Decisions still open

### 8. Colleagues get plain-text emails

Anyone opening the app from their own desk gets the `mailto:` fallback —
correct addresses and details, but a bulleted list instead of tables. The
app opens drafts in the Outlook next to *itself*, and nothing a server can
do reaches another PC's Outlook.

Options: accept it; send from the server over SMTP instead (everyone gets
identical HTML, but nobody reviews it before it goes, and it needs a
mailbox the app can send from); or run a copy per machine (not advised —
it splits the database).

### 9. The employee code is not in the leaver emails

The two leaver messages carry the team's own five lines. The form now also
asks for the employee code, which is not among them. Say the word if it
should be.

### 10. Two forms are nearly page-full

`laptop_handover` and `printer_handover` have very little room left. If
Arabic text is ever added to either, expect a second page — the fix is to
find the space rather than let it spill.

---

## Ideas, not commitments

- **A backup of the database.** There is one copy of
  `instance/handovers.db`. A scheduled copy elsewhere would be cheap.
- **Search the Resignation list.** Fine at a dozen records; a search box
  would help at a hundred.
- **Bold headings in the handover notification.** Now possible for the
  Outlook path, since it takes HTML.
