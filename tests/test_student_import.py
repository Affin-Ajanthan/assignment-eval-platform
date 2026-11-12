"""The admin's "Import students": the template, POST /admin/students/import/preview and POST /admin/students/import.
Generated passwords are read from the answer and used, but never printed: a failing assert shows only counts."""

import base64
import io
import logging
import sys
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

sys.path.insert(0, str(Path(__file__).parent.parent))

import app.main as main_module
from app import student_import as si
from app.auth import password_problems, verify_password
from app.db import SessionLocal
from app.main import app as fastapi_app
from app.models import Enrollment, User
from tests.auth_helpers import _unique, admin_token, auth_headers, create_instructor, create_student, create_subject

client = TestClient(fastapi_app)
H = auth_headers
HEADINGS = ["Full name", "Email", "Batch", "Register number"]
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _mail(prefix="imp"):
    return f"{_unique(prefix)}@example.com"


def _number():
    return _unique("IMP")


def _xlsx(rows, headings=HEADINGS):
    book = Workbook()
    sheet = book.active
    sheet.append(headings)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _upload(content, name="class.xlsx"):
    return {"file": (name, io.BytesIO(content), "application/octet-stream")}


def _preview(admin, content, name="class.xlsx"):
    return client.post("/admin/students/import/preview", headers=H(admin), files=_upload(content, name))


def _run(admin, content, name="class.xlsx", subject_ids=""):
    return client.post("/admin/students/import", headers=H(admin), files=_upload(content, name),
                       data={"subject_ids": subject_ids})


def _password_lines(body):
    """The lines of the passwords file: {email: (full name, batch, register number, password)}."""
    book = load_workbook(io.BytesIO(base64.b64decode(body["passwords_file"])))
    rows = list(book["First passwords"].iter_rows(values_only=True))
    assert rows[0] == ("Full name", "Email", "Batch", "Register number", "First password")
    return {r[1]: (r[0], r[2], r[3], r[4]) for r in rows[1:]}


def _problems(body, row):
    return next(r["problems"] for r in body["rows"] if r["row"] == row)


def _user(email):
    with SessionLocal() as db:
        return db.query(User).filter(User.email == email).first()


# ---- the template ---------------------------------------------------------------------------------------------------

def test_template_has_the_headings_text_cells_and_no_students():
    admin = admin_token(client)
    r = client.get("/admin/students/import-template", headers=H(admin))
    assert r.status_code == 200 and r.headers["content-type"] == XLSX_TYPE
    book = load_workbook(io.BytesIO(r.content))
    sheet = book.worksheets[0]
    assert [c.value for c in sheet[1]] == HEADINGS
    assert sheet["C2"].number_format == "@" and sheet["D2"].number_format == "@"  # or Excel makes 001 into 1
    assert all(sheet.cell(row=2, column=c).value is None for c in range(1, 5))


def test_the_filled_in_template_imports():
    admin = admin_token(client)
    book = load_workbook(io.BytesIO(client.get("/admin/students/import-template", headers=H(admin)).content))
    email, number = _mail(), _number()
    sheet = book.worksheets[0]
    sheet["A2"], sheet["B2"], sheet["C2"], sheet["D2"] = "From Template", email, "01", number
    buffer = io.BytesIO()
    book.save(buffer)
    body = _preview(admin, buffer.getvalue()).json()
    assert body["ready"] == 1 and body["with_problems"] == 0  # the example on the other sheet is not read
    assert body["rows"][0]["register_number"] == f"TST/01/{number}"


# ---- who may ---------------------------------------------------------------------------------------------------------

def test_only_an_admin_can_use_any_of_it():
    admin = admin_token(client)
    subject = create_subject(client, admin)
    _inst, inst_tok = create_instructor(client, admin, [subject["id"]])
    _stu, stu_tok = create_student(client, admin, [subject["id"]])
    email = _mail()
    content = _xlsx([["Not Created", email, "", ""]])
    for token in (inst_tok, stu_tok):
        assert client.get("/admin/students/import-template", headers=H(token)).status_code == 403
        assert _preview(token, content).status_code == 403
        assert _run(token, content).status_code == 403
    assert client.post("/admin/students/import", files=_upload(content)).status_code == 401
    assert _user(email) is None


# ---- the preview -----------------------------------------------------------------------------------------------------

def test_preview_creates_nothing_and_holds_no_passwords():
    admin = admin_token(client)
    email = _mail()
    r = _preview(admin, _xlsx([["Preview Only", email, "01", _number()]]))
    assert r.status_code == 200, r.text
    assert r.json()["ready"] == 1
    assert "password" not in r.text.lower()
    assert _user(email) is None


def test_every_kind_of_problem_is_reported_on_its_row():
    admin = admin_token(client)
    taken = _number()
    existing = client.post("/admin/students", headers=H(admin), json={
        "email": _mail(), "full_name": "Already Here", "password": "abcd", "subject_ids": [],
        "batch": "01", "register_number": f"TST/01/{taken}"}).json()
    good = _mail()
    dup_email, dup_number = _mail(), _number()
    body = _preview(admin, _xlsx([
        ["Good Row", good, "01", _number()],                # row 2
        ["", _mail(), "", ""],                              # row 3: no name
        ["No Email", "", "", ""],                           # row 4
        ["Bad Email", "not-an-email", "", ""],              # row 5
        ["Has Account", existing["email"].upper(), "", ""],  # row 6: case doesn't matter
        ["First Twin", dup_email, "01", dup_number],        # row 7
        ["Second Twin", dup_email.upper(), "02", dup_number.lower()],  # row 8: same email, same number in another batch
        ["No Batch", _mail(), "", "123"],                   # row 9
        ["Slash Batch", _mail(), "a/b", ""],                # row 10
        ["Taken Number", _mail(), "02", taken.lower()],     # row 11: taken in another batch, and in another case
        ["Wrong Batch", _mail(), "02", "TST/03/777"],       # row 12
        ["Spaced Number", _mail(), "01", "1 2"],            # row 13
        ["N" * 201, _mail(), "", ""],                       # row 14
    ])).json()
    assert body["ready"] == 2 and body["with_problems"] == 11  # rows 2 and 7 are fine
    assert _problems(body, 2) == [] and _problems(body, 7) == []
    assert _problems(body, 3) == ["Full name is missing"]
    assert _problems(body, 4) == ["Email is missing"]
    assert "not a valid email" in _problems(body, 5)[0]
    assert "already has an account" in _problems(body, 6)[0]
    assert _problems(body, 8) == ["Same email as row 7", "Same student number as row 7"]
    assert _problems(body, 9) == ["A register number needs a batch"]
    assert _problems(body, 10) == ["A batch can't contain '/'"]
    assert "already belongs to another student" in _problems(body, 11)[0]
    assert "is not in batch 02" in _problems(body, 12)[0]
    assert "must look like" in _problems(body, 13)[0]
    assert "longer than 200" in _problems(body, 14)[0]


def test_cleaning_blank_rows_and_row_numbers():
    admin = admin_token(client)
    mixed = f"  {_unique('MiXeD')}@Example.COM "
    body = _preview(admin, _xlsx([
        [None, None, None, None],
        ["  Nimal   Silva ", mixed, " 01 ", None],
        ["", "", "", ""],
        ["Number Cell", _mail(), 2026, 1.0],  # what Excel makes of 001 in a cell that is not text
    ])).json()
    assert [r["row"] for r in body["rows"]] == [3, 5]  # the rows the admin sees in the spreadsheet
    first, second = body["rows"]
    assert first["full_name"] == "Nimal Silva" and first["batch"] == "01"
    assert first["email"] == mixed.strip().lower()  # login compares exactly, so one form is stored
    assert second["batch"] == "2026" and second["register_number"] == "TST/2026/1"


def test_a_whole_register_number_for_the_batch_is_accepted():
    admin = admin_token(client)
    number = _number()
    body = _preview(admin, _xlsx([["Whole Number", _mail(), "01", f"TST/01/{number}"]])).json()
    assert body["ready"] == 1 and body["rows"][0]["register_number"] == f"TST/01/{number}"


def test_other_headings_and_extra_columns_are_understood():
    admin = admin_token(client)
    number = _number()
    body = _preview(admin, _xlsx([["x", "Other Names", "y", _mail(), "01", number]],
                                 headings=["No.", "Student Name", "Notes", "E-mail Address", "BATCH", "Reg No"])).json()
    assert body["ready"] == 1
    assert body["rows"][0]["full_name"] == "Other Names" and body["rows"][0]["register_number"] == f"TST/01/{number}"


def test_csv_with_a_byte_order_mark_and_with_semicolons():
    admin = admin_token(client)
    first, second = _mail(), _mail()
    utf8 = f"﻿Full name,Email,Batch,Register number\r\nKavyā Rāj,{first},01,{_number()}\r\n".encode("utf-8")
    body = _preview(admin, utf8, "class.csv").json()
    assert body["ready"] == 1 and body["rows"][0]["full_name"] == "Kavyā Rāj"
    plain = f"Full name;Email\r\nRené Dupont;{second}\r\n".encode("cp1252")  # Excel's plain CSV in some regions
    body = _preview(admin, plain, "class.csv").json()
    assert body["ready"] == 1 and body["rows"][0]["full_name"] == "René Dupont"


# ---- files that can't be used ----------------------------------------------------------------------------------------

def test_files_that_cannot_be_used_are_refused_with_a_reason():
    admin = admin_token(client)
    for content, name, expected in (
        (b"junk", "class.pdf", "Upload an Excel"),
        (b"junk", "class", "Upload an Excel"),
        (b"junk", "class.xls", "Old .xls"),
        (b"not a zip at all", "class.xlsx", "could not be read"),
        (b"", "class.csv", "empty"),
        (_xlsx([]), "class.xlsx", "no students"),
        (_xlsx([["A", "a@example.com"]], headings=["Surname", "Email"]), "class.xlsx", "Missing: Full name"),
        (b"Full name,Batch\nA,01\n", "class.csv", "Missing: Email"),
    ):
        r = _preview(admin, content, name)
        assert r.status_code == 400 and expected in r.json()["detail"], (name, r.text)


def test_too_many_rows_are_refused_before_any_work():
    admin = admin_token(client)
    rows = [[f"Student {i}", f"over{i}@example.com"] for i in range(si.MAX_ROWS + 1)]
    r = _run(admin, _xlsx(rows, headings=["Full name", "Email"]))
    assert r.status_code == 400 and "split it" in r.json()["detail"]
    assert _user("over0@example.com") is None


def test_too_large_files_are_refused():
    admin = admin_token(client)
    r = _preview(admin, b"x" * (si.MAX_FILE_BYTES + 1), "class.csv")
    assert r.status_code == 400 and "too large" in r.json()["detail"]


def test_a_workbook_that_unpacks_to_something_huge_is_refused():
    admin = admin_token(client)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"0" * (si._MAX_UNZIPPED_BYTES + 1))
    assert len(buffer.getvalue()) < si.MAX_FILE_BYTES  # small on the way in
    r = _preview(admin, buffer.getvalue())
    assert r.status_code == 400 and "too large" in r.json()["detail"]


def test_a_workbook_with_an_xml_entity_bomb_is_refused():
    admin = admin_token(client)
    source = io.BytesIO(_xlsx([["A", "a@example.com", "", ""]]))
    bomb = (b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa">'
            + b"".join(b'<!ENTITY %c "%s">' % (98 + i, (b"&%c;" % (97 + i)) * 10) for i in range(8))
            + b']><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              b'<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>&i;</t></is></c></row></sheetData></worksheet>')
    out = io.BytesIO()
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as new:
        for item in old.infolist():
            new.writestr(item, bomb if item.filename == "xl/worksheets/sheet1.xml" else old.read(item.filename))
    r = _preview(admin, out.getvalue())
    assert r.status_code == 400 and "could not be read" in r.json()["detail"]


# ---- the import ------------------------------------------------------------------------------------------------------

def test_import_creates_only_the_good_rows_and_gives_their_passwords_once():
    admin = admin_token(client)
    good, bad = _mail(), "not-an-email"
    number = _number()
    r = _run(admin, _xlsx([["Good Student", good, "01", number], ["Bad Student", bad, "", ""]]))
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert [c["email"] for c in body["created"]] == [good]
    assert [s["row"] for s in body["skipped"]] == [3] and body["skipped"][0]["problems"]
    # The rows themselves hold no password: only the file does.
    assert "password" not in str(body["created"]).lower()

    lines = _password_lines(body)
    assert set(lines) == {good}
    name, batch, register_number, password = lines[good]
    assert name == "Good Student" and batch == "01" and register_number == f"TST/01/{number}"

    student = _user(good)
    assert student.role == "student" and student.must_change_password
    assert student.batch == "01" and student.register_number == f"TST/01/{number}"
    # Only the hash is stored.
    assert password not in (student.password_hash, student.password_salt)
    assert verify_password(password, student.password_hash, student.password_salt)


def test_a_generated_password_logs_in_and_must_then_be_changed():
    admin = admin_token(client)
    email = _mail()
    password = _password_lines(_run(admin, _xlsx([["First Login", email, "", ""]])).json())[email][3]
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200 and login.json()["user"]["must_change_password"] is True
    token = login.json()["token"]
    assert client.get("/student/subjects", headers=H(token)).status_code == 403  # nothing works until it is changed
    new = "Str0ng!pass"
    assert client.post("/auth/change-password", headers=H(token),
                       json={"current_password": password, "new_password": new}).status_code == 200
    assert client.get("/student/subjects", headers=H(token)).status_code == 200
    assert client.post("/auth/login", json={"email": email, "password": password}).status_code == 401


def test_generated_passwords_are_strong_different_and_safe_in_a_spreadsheet():
    passwords = [si.make_password() for _ in range(300)]
    assert len(set(passwords)) == 300
    for password in passwords:
        assert password_problems(password) == []
        assert password[0] not in "=+-@"
        assert not set(password) & set("0O1lI")


def test_every_student_gets_their_own_password_and_the_chosen_subjects():
    admin = admin_token(client)
    s1, s2 = create_subject(client, admin), create_subject(client, admin)
    a, b = _mail(), _mail()
    body = _run(admin, _xlsx([["A Student", a, "", ""], ["B Student", b, "", ""]]),
                subject_ids=f"{s1['id']}, {s2['id']}").json()
    lines = _password_lines(body)
    assert lines[a][3] != lines[b][3]
    with SessionLocal() as db:
        for email in (a, b):
            student = db.query(User).filter(User.email == email).one()
            enrolled = {e.subject_id for e in db.query(Enrollment).filter(Enrollment.student_id == student.id)}
            assert enrolled == {s1["id"], s2["id"]}


def test_unknown_or_malformed_subjects_create_nothing():
    admin = admin_token(client)
    email = _mail()
    content = _xlsx([["Not Created", email, "", ""]])
    assert _run(admin, content, subject_ids="99999999").status_code == 400
    assert _run(admin, content, subject_ids="1,abc").status_code == 400
    assert _user(email) is None


def test_every_row_is_checked_again_at_the_import():
    """An account made after the preview: the import notices, and that row is left out."""
    admin = admin_token(client)
    late, other = _mail(), _mail()
    content = _xlsx([["Late Twin", late, "", ""], ["Other", other, "", ""]])
    assert _preview(admin, content).json()["ready"] == 2
    r = client.post("/admin/students", headers=H(admin), json={"email": late, "full_name": "Got There First",
                                                               "password": "abcd", "subject_ids": []})
    assert r.status_code == 200, r.text
    body = _run(admin, content).json()
    assert [c["email"] for c in body["created"]] == [other]
    assert "already has an account" in body["skipped"][0]["problems"][0]
    assert _user(late).full_name == "Got There First"  # not changed


def test_importing_the_same_file_twice_changes_nothing_the_second_time():
    admin = admin_token(client)
    email = _mail()
    content = _xlsx([["Only Once", email, "", ""]])
    first = _run(admin, content).json()
    before = _user(email).password_hash
    second = _run(admin, content).json()
    assert len(first["created"]) == 1 and second["created"] == [] and second["passwords_file"] == ""
    assert _user(email).password_hash == before  # the password handed out still works


def test_if_the_database_refuses_one_none_are_created(monkeypatch):
    admin = admin_token(client)
    taken, _ = create_student(client, admin, [])
    fresh = _mail()

    def stale(_file, _db):  # as if the taken account appeared after the rows were checked
        return [si.ImportRow(row=2, full_name="Fresh", email=fresh),
                si.ImportRow(row=3, full_name="Clash", email=taken["email"])]

    monkeypatch.setattr(main_module, "_checked_import_rows", stale)
    no_exceptions = TestClient(fastapi_app, raise_server_exceptions=False)
    r = no_exceptions.post("/admin/students/import", headers=H(admin), files=_upload(_xlsx([])), data={"subject_ids": ""})
    assert r.status_code == 409, r.text
    assert "nothing was created" in r.json()["detail"]
    assert _user(fresh) is None


def test_the_log_says_who_and_how_many_but_never_a_password(caplog):
    admin = admin_token(client)
    email = _mail()
    with caplog.at_level(logging.INFO):
        password = _password_lines(_run(admin, _xlsx([["Logged", email, "", ""]])).json())[email][3]
    lines = [r.getMessage() for r in caplog.records if r.name == "app.student_import"]
    assert len(lines) == 1 and "admin@school.local" in lines[0] and "1 created" in lines[0]
    assert password not in caplog.text


def test_a_name_that_looks_like_a_formula_stays_text_in_the_passwords_file():
    admin = admin_token(client)
    email = _mail()
    formula = '=HYPERLINK("http://evil.example","click")'
    csv_file = f'Full name,Email\n"{formula.replace(chr(34), chr(34) * 2)}",{email}\n'.encode()
    body = _run(admin, csv_file, "class.csv").json()
    assert len(body["created"]) == 1, body["skipped"]
    book = load_workbook(io.BytesIO(base64.b64decode(body["passwords_file"])))
    cell = book["First passwords"]["A2"]
    assert cell.value == formula and cell.data_type == "s"  # text, not something Excel runs


def test_a_real_formula_cell_in_a_workbook_is_not_run_and_counts_as_blank():
    admin = admin_token(client)
    email = _mail()
    body = _preview(admin, _xlsx([['=HYPERLINK("http://evil.example","click")', email, "", ""]])).json()
    assert _problems(body, 2) == ["Full name is missing"]
