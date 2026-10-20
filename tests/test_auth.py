# -*- coding: utf-8 -*-
# 작성일시: 2026-10-20 20:27 (KST)
"""#6 로그인: 해시, 관리자 계정, 로그인 판정, 관리자 기능 막기."""
import pytest

from teamform import service


def add_student(conn, student_no="T9001", password="1234", main_role="테스터", subs=("기획자",)):
    sid = conn.execute(
        """insert into tf_students (student_no, name, main_role, password_hash)
           values (%s, '시험학생', %s, %s) returning id""",
        (student_no, main_role, service.hash_password(password)),
    ).fetchone()["id"]
    for role in subs:
        conn.execute("insert into tf_student_sub_roles values (%s, %s)", (sid, role))
    return sid


# 해시 ----------------------------------------------------------------------

def test_hash_is_not_plaintext_and_verifies():
    h = service.hash_password("1234")
    assert h != "1234" and h.startswith("$2")
    assert service.verify_password("1234", h)
    assert not service.verify_password("12345", h)


def test_same_password_gets_different_hash():
    assert service.hash_password("1234") != service.hash_password("1234")


def test_broken_hash_does_not_verify():
    assert not service.verify_password("1234", "not-a-bcrypt-hash")


# 관리자 계정 ---------------------------------------------------------------

def test_ensure_admin_creates_then_keeps_then_updates(conn):
    conn.execute("delete from tf_students where student_no = 'admin'")
    assert service.ensure_admin(conn, "first-pass") == "만듦"
    assert service.ensure_admin(conn, "first-pass") == "그대로"
    assert service.ensure_admin(conn, "second-pass") == "갱신함"
    assert service.login(conn, "admin", "first-pass") is None
    admin = service.login(conn, "admin", "second-pass")
    assert admin is not None and admin.is_admin


def test_ensure_admin_without_password_fails(conn):
    with pytest.raises(ValueError):
        service.ensure_admin(conn, "")


def test_admin_password_is_stored_as_hash(conn):
    service.ensure_admin(conn, "plain-check")
    stored = conn.execute(
        "select password_hash from tf_students where student_no = 'admin'"
    ).fetchone()["password_hash"]
    assert stored != "plain-check" and stored.startswith("$2")


# 로그인 --------------------------------------------------------------------

def test_student_login_with_right_password(conn):
    add_student(conn)
    user = service.login(conn, "T9001", "1234")
    assert user is not None
    assert (user.name, user.main_role, user.sub_roles, user.is_admin) == ("시험학생", "테스터", ("기획자",), False)


def test_student_number_with_spaces_still_logs_in(conn):
    add_student(conn)
    assert service.login(conn, "  T9001 ", "1234") is not None


def test_wrong_password_does_not_log_in(conn):
    add_student(conn)
    assert service.login(conn, "T9001", "4321") is None


def test_student_number_only_does_not_log_in(conn):
    add_student(conn)
    assert service.login(conn, "T9001", "") is None


def test_unknown_student_number_does_not_log_in(conn):
    assert service.login(conn, "T9999", "1234") is None


def test_load_user_reads_current_state(conn):
    sid = add_student(conn)
    assert service.load_user(conn, sid).student_no == "T9001"
    conn.execute("delete from tf_students where id = %s", (sid,))
    assert service.load_user(conn, sid) is None


# 관리자 기능 막기 ----------------------------------------------------------

def test_require_admin_blocks_student(conn):
    add_student(conn)
    student = service.login(conn, "T9001", "1234")
    with pytest.raises(PermissionError):
        service.require_admin(student)
    with pytest.raises(PermissionError):
        service.require_admin(None)


def test_require_admin_allows_admin(conn):
    service.ensure_admin(conn, "admin-pass")
    service.require_admin(service.login(conn, "admin", "admin-pass"))
