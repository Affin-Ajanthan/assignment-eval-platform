"""Creating many student accounts at once from a spreadsheet (.xlsx or .csv): the admin's "Import students".

This module has no database or web code: it reads the file, says what is wrong with each row, makes the passwords and
writes the two workbooks. The routes are beside the other student routes in app/main.py.

A file is only ever read to check it, and read again (and every row checked again) when the admin confirms, so nothing
is kept between the two steps and an account made in between is still noticed. The passwords exist as plain text only
in the answer to that confirmation: they are never stored, and never logged.
"""

from __future__ import annotations

import base64
import csv
import io
import re
import secrets
import zipfile
from dataclasses import dataclass, field

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter

from . import exports as _exports
from .auth import password_problems

# One file: about 25 seconds of password hashing at this many rows. Kept well under the usual 60-second proxy limit: an
# answer cut off after the accounts were created would lose their passwords. A bigger class is imported in two files.
MAX_ROWS = 300
MAX_FILE_BYTES = 2 * 1024 * 1024
# An .xlsx is a zip: a small one can unpack to something huge. No real class list comes near these.
_MAX_UNZIPPED_BYTES = 50 * 1024 * 1024
_MAX_ZIP_ENTRIES = 200
# Blank rows are skipped, but only this many rows are looked at, so a file with a million empty rows can't take long.
_MAX_ROWS_SCANNED = 20_000
_MAX_COLUMNS = 40

_NAME_MAX, _EMAIL_MAX, _BATCH_MAX, _REGISTER_MAX = 200, 254, 100, 50
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")  # the same check as editing a student

# The headings of the template, and the other names a registrar's export may use (case and spaces don't matter).
_COLUMNS = {
    "full_name": ("fullname", "name", "studentname"),
    "email": ("email", "emailaddress", "mail"),
    "batch": ("batch",),
    "number": ("registernumber", "registerno", "regno", "regnumber", "studentnumber", "number"),
}
_TEMPLATE_HEADINGS = ["Full name", "Email", "Batch", "Register number"]

# Characters that are easy to read out and type: no 0/O, 1/l/I. Starts with a letter or digit, never with something
# a spreadsheet takes for a formula (= + - @).
_LOWER = "abcdefghjkmnpqrstuvwxyz"
_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_DIGITS = "23456789"


class ImportFileError(Exception):
    """The file as a whole can't be used; the message says why, for the admin."""


@dataclass
class ImportRow:
    row: int  # the row number the admin sees in the spreadsheet
    full_name: str = ""
    email: str = ""
    batch: str = ""
    number: str = ""  # as written in the file
    register_number: str = ""  # as it will be stored, TST/<batch>/<number>
    problems: list[str] = field(default_factory=list)


def _text(value) -> str:
    """A cell as text. A number is written without ".0": Excel keeps a register number typed as 1 as the number 1.0."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _read_xlsx(content: bytes) -> list[tuple]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
    except zipfile.BadZipFile:
        raise ImportFileError("This file could not be read as an Excel workbook. Save it again as .xlsx and retry.")
    if len(infos) > _MAX_ZIP_ENTRIES or sum(i.file_size for i in infos) > _MAX_UNZIPPED_BYTES:
        raise ImportFileError("This workbook is too large to be a class list.")
    try:
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        try:
            rows = []
            for values in book.worksheets[0].iter_rows(values_only=True, max_col=_MAX_COLUMNS):
                rows.append(values)
                if len(rows) > _MAX_ROWS_SCANNED:
                    raise ImportFileError(f"This file has too many rows. The most in one file is {MAX_ROWS} students.")
            return rows
        finally:
            book.close()
    except ImportFileError:
        raise
    except Exception:  # openpyxl raises many kinds on a damaged or hostile file; the admin only needs to know this
        raise ImportFileError("This file could not be read as an Excel workbook. Save it again as .xlsx and retry.")


def _read_csv(content: bytes) -> list[tuple]:
    try:
        text = content.decode("utf-8-sig")  # Excel's "CSV UTF-8" starts with a byte-order mark
    except UnicodeDecodeError:
        text = content.decode("cp1252", errors="replace")  # Excel's plain "CSV" on Windows
    first_line = text.split("\n", 1)[0]
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","  # some regions' Excel writes ;
    try:
        rows = []
        for values in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter):
            rows.append(tuple(values[:_MAX_COLUMNS]))
            if len(rows) > _MAX_ROWS_SCANNED:
                raise ImportFileError(f"This file has too many rows. The most in one file is {MAX_ROWS} students.")
        return rows
    except csv.Error:
        raise ImportFileError("This file could not be read as a CSV file. Save it again and retry.")


def read_rows(filename: str, content: bytes) -> list[ImportRow]:
    """The students in a file, with the numbers of the rows they are on. Blank rows are skipped. Nothing is checked
    yet except that the file can be used at all (ImportFileError otherwise)."""
    if len(content) > MAX_FILE_BYTES:
        raise ImportFileError(f"This file is too large. The most is {MAX_FILE_BYTES // (1024 * 1024)} MB.")
    extension = "." + (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    if extension == ".xlsx":
        cells = _read_xlsx(content)
    elif extension == ".csv":
        cells = _read_csv(content)
    elif extension == ".xls":
        raise ImportFileError("Old .xls files can't be read. In Excel, use Save As and choose .xlsx.")
    else:
        raise ImportFileError("Upload an Excel (.xlsx) or CSV (.csv) file. The template is an .xlsx file.")

    numbered = [(i, [_text(v) for v in values]) for i, values in enumerate(cells, start=1)]
    numbered = [(i, values) for i, values in numbered if any(values)]
    if not numbered:
        raise ImportFileError("This file is empty. Fill in the template and upload it again.")

    headings = [re.sub(r"[^a-z0-9]", "", h.lower()) for h in numbered[0][1]]
    where = {key: next((headings.index(n) for n in names if n in headings), None) for key, names in _COLUMNS.items()}
    missing = [label for key, label in (("full_name", "Full name"), ("email", "Email")) if where[key] is None]
    if missing:
        raise ImportFileError(f"The first row must hold the column headings. Missing: {', '.join(missing)}. "
                              "The template has the right ones.")

    def cell(values: list[str], key: str) -> str:
        column = where[key]
        return values[column] if column is not None and column < len(values) else ""

    rows = [ImportRow(row=i, full_name=cell(v, "full_name"), email=cell(v, "email"), batch=cell(v, "batch"),
                      number=cell(v, "number")) for i, v in numbered[1:]]
    if not rows:
        raise ImportFileError("This file has headings but no students. Add them from the second row on.")
    if len(rows) > MAX_ROWS:
        raise ImportFileError(f"This file has {len(rows)} students. The most in one file is {MAX_ROWS}: "
                              "split it into smaller files.")
    return rows


def check_rows(rows: list[ImportRow], taken_emails: set[str], taken_numbers: set[str], prefix: str) -> list[ImportRow]:
    """Fills in each row's cleaned values and its problems. A row with no problems can be created.

    ``taken_emails`` are every account's email and ``taken_numbers`` every student's own number, both in lower case.
    The rules are the ones for adding a student by hand, plus: nor may two rows of the file clash with each other.
    """
    email_rows: dict[str, int] = {}
    number_rows: dict[str, int] = {}
    for r in rows:
        r.problems = []
        r.full_name = " ".join(r.full_name.split())
        r.email = r.email.strip().lower()  # login compares emails exactly: one form, whatever the file used
        r.batch = " ".join(r.batch.split())
        r.number = r.number.strip()
        r.register_number = ""

        if not r.full_name:
            r.problems.append("Full name is missing")
        elif len(r.full_name) > _NAME_MAX:
            r.problems.append(f"Full name is longer than {_NAME_MAX} characters")

        if not r.email:
            r.problems.append("Email is missing")
        elif len(r.email) > _EMAIL_MAX or not _EMAIL.fullmatch(r.email):
            r.problems.append("This is not a valid email address")
        else:
            if r.email in taken_emails:
                r.problems.append("This email already has an account")
            elif r.email in email_rows:
                r.problems.append(f"Same email as row {email_rows[r.email]}")
            email_rows.setdefault(r.email, r.row)

        batch_ok = True
        if len(r.batch) > _BATCH_MAX:
            r.problems.append(f"Batch is longer than {_BATCH_MAX} characters")
            batch_ok = False
        elif "/" in r.batch:
            r.problems.append("A batch can't contain '/'")
            batch_ok = False

        if r.number:
            own = r.number
            given_whole = own.startswith(f"{prefix}/")
            if given_whole:  # the whole number (TST/01/001) is fine too, if it is for this batch
                whole = f"{prefix}/{r.batch}/"
                if r.batch and own.startswith(whole):
                    own = own[len(whole):]
                elif r.batch:
                    r.problems.append(f"Register number {r.number} is not in batch {r.batch}")
                    batch_ok = False
            if not r.batch:
                r.problems.append("A register number needs a batch")
            elif batch_ok:
                if not own or "/" in own or any(c.isspace() for c in own):
                    r.problems.append(f"Register number '{r.number[:60]}' must look like 001 or {prefix}/{r.batch}/001")
                else:
                    register_number = f"{prefix}/{r.batch}/{own}"
                    if len(register_number) > _REGISTER_MAX:
                        r.problems.append(f"Register number is longer than {_REGISTER_MAX} characters")
                    else:
                        r.register_number = register_number
                        key = own.lower()
                        if key in taken_numbers:
                            r.problems.append(f"Student number {own} already belongs to another student")
                        elif key in number_rows:
                            r.problems.append(f"Same student number as row {number_rows[key]}")
                        number_rows.setdefault(key, r.row)
    return rows


def make_password() -> str:
    """A random first password, like Kx7m-Qp4t-Wz9r: strong enough for the password rules, and easy to read out."""
    alphabet = _LOWER + _UPPER + _DIGITS
    while True:
        password = "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))
        if not password_problems(password):
            return password


def _workbook_bytes(book: Workbook) -> bytes:
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def template_xlsx() -> bytes:
    """The empty class list to fill in. The first sheet is the one that is read, so the example is on another one,
    where it can't be imported by mistake. Batch and Register number are text cells, or Excel turns 001 into 1."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Students"
    _exports._table(sheet, _TEMPLATE_HEADINGS, [], widths=[30, 36, 12, 18])
    for row in range(2, MAX_ROWS + 2):
        for column in (3, 4):
            sheet.cell(row=row, column=column).number_format = "@"

    help_sheet = book.create_sheet("How to fill it in")
    for line in (
        ["Put one student on each row of the Students sheet, from the second row on."],
        ["Full name and Email are required. Batch and Register number are optional."],
        ["Register number: only the student's own number, such as 001. A register number needs a batch."],
        [f"At most {MAX_ROWS} students in one file. Nothing is created until you have checked the preview."],
        [],
        ["Example:"],
        _TEMPLATE_HEADINGS,
        ["Nimal Silva", "nimal@example.com", "01", "001"],
        ["Kavya Raj", "kavya@example.com", "01", "002"],
    ):
        help_sheet.append(line)
    for column, width in zip("ABCD", (30, 36, 12, 18)):
        help_sheet.column_dimensions[column].width = width
    return _workbook_bytes(book)


def passwords_xlsx_base64(students: list[tuple[str, str, str, str, str]]) -> str:
    """The list of the created students and their first passwords: (full name, email, batch, register number,
    password). Base64, because it goes to the browser inside the JSON answer and is kept nowhere else. A name that
    looks like a formula stays text (exports._write_row)."""
    book = Workbook()
    sheet = book.active
    sheet.title = "First passwords"
    _exports._table(sheet, ["Full name", "Email", "Batch", "Register number", "First password"], students,
                    widths=[30, 36, 12, 18, 20])
    note = book.create_sheet("Read me")
    for line in (
        "Give each student only their own line, in private.",
        "Each student must choose a new password the first time they log in.",
        "These passwords are not saved anywhere else. Delete this file once they have been handed out.",
    ):
        note.append([line])
    note.column_dimensions[get_column_letter(1)].width = 90
    return base64.b64encode(_workbook_bytes(book)).decode("ascii")
