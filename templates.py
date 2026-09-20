#!/usr/bin/env python3
"""
templates.py
============
What documents exist, and what each one asks for. The single source of
truth behind the "pick a document" screen, every form, the column
headings in the emails, and the chips in history.

Data only. This module imports nothing and calls nothing - reading it
tells you the whole domain, and adding a document type is an entry here
plus, if it is a new SHAPE, a function in builders.py.
"""

from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DOC_TEMPLATES_DIR = BASE_DIR / "doc_templates"

# The employee half of every form - the same seven questions whatever
# the document is. Named here because it is a fact about the registry:
# it is exactly the union of every spec's employee_fields.
EMPLOYEE_KEYS = ("name", "name_en", "department", "role", "mobile", "email",
                 "code", "govid")

# Printed in the Company field unless someone changes it on the form.
DEFAULT_COMPANY = "اس تي ام للاستثمار"

# Lists offered on the form. A field with "options" becomes a box you can
# pick from OR type into - never a closed dropdown, because the day a new
# department is created or a new laptop model is bought is exactly the day
# someone needs to record one, and being unable to would stop the document
# rather than tidy it.
#
# Edit these two lists and every form that uses them follows.
DEPARTMENTS = (
    "Sales", "Administration", "IT", "Operations", "Sports", "Leads Club",
    "Retail", "People and Culture", "Legal", "Finance",
)

# Laptops only. A headset or a router has its own model, and offering
# E14 there would be noise.
#
# Unlike the departments, this list is CLOSED: the model boxes are real
# dropdowns and nothing else is accepted, in the browser or on the
# server. Adding a model is a one-line edit here.
LAPTOP_MODELS = ("E14", "E16")

# ----------------------------------------------------------------------
# Template registry - the single source of truth for the "pick a
# document" screen and each one's own form fields.
# ----------------------------------------------------------------------

# Field specs shared by (almost) every template.
#
# "pattern" is a regex (matched with re.fullmatch) used for both the
# server-side check in app.py and the HTML5 pattern= attribute in
# form.html (so most people see the browser's inline error before ever
# submitting); "pattern_msg" is the human-readable explanation shown by
# both when a value doesn't match.
# The two names, and why there are two.
#
# The documents are Arabic, so the name printed in them has to be the
# Arabic one - that is the whole point of the templates. The emails are
# English, and an Arabic name dropped into an English sentence reads
# badly and cannot be searched for in a mailbox.
#
# They cannot be derived from each other. Arabic script does not write
# short vowels, so محمد is Mohamed, Mohammed, Muhammad and Mohammad all
# at once, and no library can tell which spelling a person actually
# uses. So both are asked for, once, and the lookup copies them forward
# to every later document for that person.
#
# Each box refuses the other's script. Typing the English name into the
# Arabic box is the easy mistake, and it would quietly produce an Arabic
# document with a Latin name in it.
_ARABIC_LETTERS = r"[\u0621-\u063A\u0640-\u064A\u066E-\u06D3 ]+"
_LATIN_LETTERS = r"[A-Za-z][A-Za-z .'\-]*"

_NAME = {
    "key": "name", "label": "Full name (Arabic)",
    "placeholder": "محمد شعبان ابراهيم", "required": True,
    "pattern": _ARABIC_LETTERS,
    "hint": "Arabic",
    "pattern_msg": "The full name goes in the document itself, which is Arabic — "
                   "so this box takes Arabic letters only. The English spelling "
                   "goes in the next box.",
}
_NAME_EN = {
    "key": "name_en", "label": "Name in English",
    "placeholder": "Mohamed Shaban Ibrahim", "required": True,
    "pattern": _LATIN_LETTERS,
    "hint": "English",
    "pattern_msg": "This is the name the emails use, so it takes English letters "
                   "only (spaces, hyphens and apostrophes are fine). The Arabic "
                   "spelling goes in the box before it.",
}
_DEPARTMENT = {"key": "department", "label": "Department",
               "placeholder": "Pick one, or type a new one", "required": True,
               "options": DEPARTMENTS}
_ROLE = {"key": "role", "label": "Position", "placeholder": "Software Engineer", "required": True}
_MOBILE = {
    "key": "mobile", "label": "Mobile", "placeholder": "01xxxxxxxxx", "required": True,
    "inputmode": "numeric", "maxlength": 11,
    "pattern": r"01[0125][0-9]{8}",
    "hint": "11 digits",
    "pattern_msg": "Enter an 11-digit Egyptian mobile number starting with 010, 011, 012, or 015 (e.g. 01012345678).",
}
_EMAIL = {"key": "email", "label": "Email", "required": True, "suffix": "@stm.com.eg"}

# The name of the machine on the corporate network. No template prints
# it - none of them has a row for it - but every form collects it, so
# the app can quote it in the emails that do need it without anyone
# looking it up twice. Required, like everything else on these forms:
# the whole value of recording it is that it is there when someone
# leaves, and a blank one would only be noticed months later.
_COMPUTER_NAME = {"key": "computer_name", "label": "Computer name",
                  "placeholder": "STM-LT-0142", "required": True}
_CODE = {"key": "code", "label": "Employee code", "required": True}
_GOVID = {
    "key": "govid", "label": "National ID", "required": True, "maxlength": 14,
    "inputmode": "numeric", "placeholder": "", "wide": True, "hint": "14 digits",
    "pattern": r"[0-9]{14}",
    "pattern_msg": "National ID must be exactly 14 digits.",
}

EMPLOYEE_FIELDS_WITH_EMAIL = [_NAME, _NAME_EN, _DEPARTMENT, _ROLE, _MOBILE,
                              _EMAIL, _CODE, _GOVID]
EMPLOYEE_FIELDS_NO_EMAIL = [_NAME, _NAME_EN, _DEPARTMENT, _ROLE, _MOBILE, _CODE, _GOVID]

TEMPLATES = {
    "laptop_handover": {
        "label": "Laptop handover",
        "label_ar": "محضر تسليم لاب توب",
        "group": "Computers",
        "category": "computer",
        "short": "Laptop",
        "doc_file": "laptop_handover.docx",
        "filename_prefix": "استلام لابتوب",
        "employee_fields": EMPLOYEE_FIELDS_WITH_EMAIL,
        "device_title": "Laptop details",
        "device_fields": [
            {"key": "model", "label": "Laptop model", "placeholder": "E14",
             "required": True, "options": LAPTOP_MODELS, "strict": True},
            {"key": "serial", "label": "Serial number", "placeholder": "PF5K...", "required": True},
            {"key": "cpu", "label": "CPU", "placeholder": "I5 / I7", "required": True},
        ],
        "extra_fields": [
            {"key": "color", "label": "Color", "placeholder": "BLACK", "default": "BLACK"},
            {"key": "storage", "label": "Storage", "placeholder": "512SSD", "default": "512SSD"},
            {"key": "ram", "label": "RAM", "placeholder": "24GB", "default": "24GB"},
            {"key": "company", "label": "Company", "placeholder": DEFAULT_COMPANY, "default": DEFAULT_COMPANY},
        ],
    },
    "laptop_replacement": {
        "label": "Laptop replacement",
        "label_ar": "محضر استبدال جهاز كمبيوتر",
        "group": "Computers",
        "category": "computer",
        "short": "Replacement",
        "doc_file": "laptop_replacement.docx",
        "filename_prefix": "استبدال لابتوب",
        "employee_fields": EMPLOYEE_FIELDS_WITH_EMAIL,
        "device_title": "Old device (being returned)",
        "device_fields": [
            {"key": "old_model", "label": "Old model", "placeholder": "E14",
             "required": True, "options": LAPTOP_MODELS, "strict": True},
            {"key": "old_serial", "label": "Old serial number", "placeholder": "PF5K...", "required": True},
            {"key": "old_color", "label": "Old color", "placeholder": "BLACK", "required": True},
            {"key": "old_storage", "label": "Old storage", "placeholder": "512SSD", "required": True},
            {"key": "old_ram", "label": "Old RAM", "placeholder": "24GB", "required": True},
            {"key": "old_cpu", "label": "Old CPU", "placeholder": "I5 / I7", "required": True},
        ],
        "device_title_2": "New device (being issued)",
        "device_fields_2": [
            {"key": "new_model", "label": "New model", "placeholder": "E14",
             "required": True, "options": LAPTOP_MODELS, "strict": True},
            {"key": "new_serial", "label": "New serial number", "placeholder": "PF5K...", "required": True},
            {"key": "new_color", "label": "New color", "placeholder": "BLACK", "required": True},
            {"key": "new_storage", "label": "New storage", "placeholder": "512SSD", "required": True},
            {"key": "new_ram", "label": "New RAM", "placeholder": "24GB", "required": True},
            {"key": "new_cpu", "label": "New CPU", "placeholder": "I5 / I7", "required": True},
        ],
        "extra_fields": [
            {"key": "company", "label": "Company", "placeholder": DEFAULT_COMPANY, "default": DEFAULT_COMPANY},
        ],
    },
    "keyboard_mouse_handover": {
        "label": "Keyboard & mouse handover",
        "label_ar": "محضر تسليم كيبورد وماوس",
        "group": "Peripherals",
        "category": "peripheral",
        "short": "Keyboard & mouse",
        "doc_file": "keyboard_mouse_handover.docx",
        "filename_prefix": "استلام كيبورد وماوس",
        "employee_fields": EMPLOYEE_FIELDS_WITH_EMAIL,
        "device_title": "Keyboard & mouse details",
        "device_fields": [
            {"key": "brand", "label": "Brand", "placeholder": "Logitech", "required": True},
            {"key": "serial", "label": "Serial number", "placeholder": "KM123456", "required": True},
            {"key": "model", "label": "Model", "placeholder": "MK270", "required": True},
            {"key": "color", "label": "Color", "placeholder": "Black", "required": True},
        ],
        "extra_fields": [
            {"key": "company", "label": "Company", "placeholder": DEFAULT_COMPANY, "default": DEFAULT_COMPANY},
        ],
    },
    "mouse_receipt": {
        "label": "Mouse handover",
        "label_ar": "محضر استلام ماوس",
        "group": "Peripherals",
        "category": "peripheral",
        "short": "Mouse",
        "doc_file": "mouse_receipt.docx",
        "filename_prefix": "استلام ماوس",
        "employee_fields": EMPLOYEE_FIELDS_WITH_EMAIL,
        "device_title": "Mouse details",
        "device_fields": [
            {"key": "model", "label": "Model", "placeholder": "M171", "required": True},
            {"key": "brand", "label": "Brand", "placeholder": "Logitech", "required": True},
        ],
        "extra_fields": [
            {"key": "company", "label": "Company", "placeholder": DEFAULT_COMPANY, "default": DEFAULT_COMPANY},
        ],
    },
    "screen_handover": {
        "label": "Screen handover",
        "label_ar": "محضر تسليم شاشة",
        "group": "Peripherals",
        "category": "peripheral",
        "short": "Screen",
        "doc_file": "screen_handover.docx",
        "filename_prefix": "تسليم شاشة",
        "employee_fields": EMPLOYEE_FIELDS_WITH_EMAIL,
        "device_title": "Screen details",
        "device_fields": [
            {"key": "model", "label": "Screen model", "placeholder": "SE2725HMc (Dell 27 Monitor)", "required": True},
            {"key": "serial", "label": "Serial number", "placeholder": "CN-...", "required": True},
            {"key": "color", "label": "Color", "placeholder": "Black", "required": True},
        ],
        "extra_fields": [
            {"key": "company", "label": "Company", "placeholder": DEFAULT_COMPANY, "default": DEFAULT_COMPANY},
        ],
    },
    "router_handover": {
        "label": "Router handover",
        "label_ar": "محضر تسليم راوتر بشريحة",
        "group": "Storage & network",
        "category": "network",
        "short": "Router",
        "doc_file": "router_handover.docx",
        "filename_prefix": "استلام راوتر",
        "employee_fields": EMPLOYEE_FIELDS_WITH_EMAIL,
        "device_title": "Router details",
        "device_fields": [
            {"key": "brand", "label": "Brand", "placeholder": "Huawei", "required": True},
            {"key": "model", "label": "Model", "placeholder": "B535", "required": True},
            {"key": "serial", "label": "Serial number", "placeholder": "RT123456", "required": True},
            {"key": "sim_number", "label": "Data SIM number", "placeholder": "01234567890123", "required": True},
            {"key": "color", "label": "Color", "placeholder": "White", "required": True},
        ],
        "extra_fields": [
            {"key": "company", "label": "Company", "placeholder": DEFAULT_COMPANY, "default": DEFAULT_COMPANY},
        ],
    },
    "headset_handover": {
        "label": "Headset handover",
        "label_ar": "محضر تسليم سماعة",
        "group": "Peripherals",
        "category": "peripheral",
        "short": "Headset",
        "doc_file": "headset_handover.docx",
        "filename_prefix": "استلام سماعة",
        "employee_fields": EMPLOYEE_FIELDS_WITH_EMAIL,
        "device_title": "Headset details",
        "device_fields": [
            {"key": "model", "label": "Headset model", "placeholder": "HS-200", "required": True},
            {"key": "serial", "label": "Serial number", "placeholder": "HSN123456", "required": True},
            {"key": "color", "label": "Color", "placeholder": "Black", "required": True},
        ],
        "extra_fields": [
            {"key": "company", "label": "Company", "placeholder": DEFAULT_COMPANY, "default": DEFAULT_COMPANY},
        ],
    },
    "printer_handover": {
        "label": "Printer handover",
        "label_ar": "محضر تسليم طابعة",
        "group": "Peripherals",
        "category": "peripheral",
        "short": "Printer",
        "doc_file": "printer_handover.docx",
        "filename_prefix": "استلام طابعة",
        "employee_fields": EMPLOYEE_FIELDS_WITH_EMAIL,
        "device_title": "Printer details",
        "device_fields": [
            {"key": "brand", "label": "Brand", "placeholder": "HP", "required": True},
            {"key": "model", "label": "Model", "placeholder": "LaserJet-M111", "required": True},
            {"key": "serial", "label": "Serial number", "placeholder": "SN-PRT123456", "required": True},
            {"key": "color", "label": "Color", "placeholder": "White", "required": True},
        ],
        "extra_fields": [
            {"key": "company", "label": "Company", "placeholder": DEFAULT_COMPANY, "default": DEFAULT_COMPANY},
        ],
    },
    "flash_handover": {
        "label": "Flash drive handover",
        "label_ar": "محضر تسليم فلاشة",
        "group": "Storage & network",
        "category": "storage",
        "short": "Flash drive",
        "doc_file": "flash_handover.docx",
        "filename_prefix": "استلام فلاشة",
        "employee_fields": EMPLOYEE_FIELDS_WITH_EMAIL,
        "device_title": "Flash drive details",
        "device_fields": [
            {"key": "brand", "label": "Brand", "placeholder": "Kingston", "required": True},
            {"key": "capacity", "label": "Capacity", "placeholder": "32 GB", "required": True},
            {"key": "model", "label": "Model", "placeholder": "DTSE9/32GB", "required": True},
            {"key": "color", "label": "Color", "placeholder": "Black", "required": True},
        ],
        "extra_fields": [
            {"key": "company", "label": "Company", "placeholder": DEFAULT_COMPANY, "default": DEFAULT_COMPANY},
        ],
    },
    "hard_handover": {
        "label": "Hard disk handover",
        "label_ar": "محضر تسليم هارد",
        "group": "Storage & network",
        "category": "storage",
        "short": "Hard disk",
        "doc_file": "hard_handover.docx",
        "filename_prefix": "استلام هارد",
        "employee_fields": EMPLOYEE_FIELDS_WITH_EMAIL,
        "device_title": "Hard disk details",
        "device_fields": [
            {"key": "brand", "label": "Brand", "placeholder": "Seagate", "required": True},
            {"key": "model", "label": "Model", "placeholder": "Expansion", "required": True},
            {"key": "serial", "label": "Serial number", "placeholder": "HD-SN123456", "required": True},
            {"key": "color", "label": "Color", "placeholder": "Black", "required": True},
        ],
        "extra_fields": [
            {"key": "company", "label": "Company", "placeholder": DEFAULT_COMPANY, "default": DEFAULT_COMPANY},
        ],
    },
}


# What each document type looks like in the picker. Drawn per type
# rather than one generic page glyph: ten identical file icons is a list
# you have to read, and ten different shapes is a list you can scan.
# Inner SVG only - the <svg> wrapper, size and stroke live in the CSS.
TEMPLATE_ICONS = {
    "laptop_handover":
        '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M2 20h20"/>',
    "laptop_replacement":
        '<path d="M17 2l4 4-4 4"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><path d="M7 22l-4-4 4-4"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>',
    "keyboard_mouse_handover":
        '<rect x="2" y="7" width="20" height="10" rx="2"/><path d="M6 11h.01M10 11h.01M14 11h.01M8 14h8"/>',
    "mouse_receipt":
        '<rect x="7" y="3" width="10" height="18" rx="5"/><path d="M12 7v4"/>',
    "screen_handover":
        '<rect x="2" y="4" width="20" height="13" rx="2"/><path d="M9 21h6M12 17v4"/>',
    "headset_handover":
        '<path d="M4 14v-3a8 8 0 0 1 16 0v3"/><rect x="2" y="14" width="5" height="7" rx="2"/><rect x="17" y="14" width="5" height="7" rx="2"/>',
    "printer_handover":
        '<path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="7" rx="2"/><path d="M7 16h10v5H7z"/>',
    "router_handover":
        '<path d="M5 13a10 10 0 0 1 14 0"/><path d="M8.5 16.5a5 5 0 0 1 7 0"/><path d="M12 20h.01"/>',
    "flash_handover":
        '<path d="M12 2v13"/><rect x="9" y="15" width="6" height="7" rx="1.5"/><path d="M9 7h6"/>',
    "hard_handover":
        '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 12h.01M10 12h8"/>',
}

for _tid, _icon in TEMPLATE_ICONS.items():
    if _tid in TEMPLATES:
        TEMPLATES[_tid]["icon"] = _icon


# Every document collects the computer name. It is appended here rather
# than written into each of the ten specs above so it cannot drift: one
# line, one place, every type. On a replacement it belongs to the NEW
# machine - that is the one the person walks away with - so it joins the
# second device group where there is one.
for _spec in TEMPLATES.values():
    _group = "device_fields_2" if _spec.get("device_fields_2") else "device_fields"
    _spec[_group] = list(_spec[_group]) + [_COMPUTER_NAME]


# The picker shows the ten documents in these groups, in this order, and
# the history table tints each document's chip by its category. Purely
# presentational - the fill functions never read them - but they live
# beside the labels so there is one place to describe a document type.
TEMPLATE_GROUPS = ("Computers", "Peripherals", "Storage & network")


def all_fields(template_id: str) -> list[dict[str, Any]]:
    """Every field key this template's form should collect (employee +
    device + device_2 if any), in order."""
    spec = TEMPLATES[template_id]
    fields = list(spec["employee_fields"]) + list(spec["device_fields"])
    if "device_fields_2" in spec:
        fields += list(spec["device_fields_2"])
    return fields


def required_field_keys(template_id: str) -> list[str]:
    return [f["key"] for f in all_fields(template_id) if f.get("required")]


def template_path(template_id: str) -> Path:
    return DOC_TEMPLATES_DIR / TEMPLATES[template_id]["doc_file"]
