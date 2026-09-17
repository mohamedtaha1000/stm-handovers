# Decisions

A running log of judgement calls made on this project — things that
weren't a bug fix with one right answer, but a choice between real
tradeoffs. `TODO.md` says what's still open; this says what's already
been settled and why, so nobody re-litigates it from scratch later.

Newest first.

---

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
*else* created, and managing accounts. Staff can still edit their own
records.

**History is the only place ownership gates *visibility*, not just
action.** A Staff member's History page lists, downloads, and can
Regenerate only documents they created. Deliberately **not** extended to
the equipment/employee lookup, the laptop register, or Resignation's own
list — those exist specifically to see across everyone (e.g. checking
what a leaving employee still holds, even if a different Staff member
issued it originally), so scoping them the same way would break the app.

**Pre-existing records belong to nobody by default.** A free-typed name
from the old shared-password era can't be reliably matched to a real
account (two people could've typed the same name; spelling varies), so
every record made before this shipped is Admin-only until an Admin
explicitly assigns it to the right account via an "Owner account" field
added to the existing edit forms — accepted as the simplest safe default
over trying to auto-match names, or building a separate reassignment
page.

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
