# -*- coding: utf-8 -*-
# 작성일시: 2026-10-20 20:27 (KST)
"""#6 로그인 화면을 AppTest로 실제로 눌러 본다.

앱은 뜰 때 관리자 계정을 실제 DB에 만들거나 갱신한다(공고 2.1의 동작 그대로).
시험용 학생은 테스트 안에서 만들고 끝나면 지운다.
"""
from pathlib import Path

import psycopg
import pytest
from streamlit.testing.v1 import AppTest

from teamform import service
from teamform.config import get_secret

ADMIN_PASSWORD = get_secret("ADMIN_PASSWORD")
DATABASE_URL = get_secret("DATABASE_URL")
pytestmark = pytest.mark.skipif(not (ADMIN_PASSWORD and DATABASE_URL), reason="비밀 값 없음")

TEMP_NO = "T9101"
APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


@pytest.fixture
def temp_student():
    with psycopg.connect(DATABASE_URL) as c:
        c.execute("delete from tf_students where student_no = %s", (TEMP_NO,))
        c.execute(
            """insert into tf_students (student_no, name, main_role, password_hash)
               values (%s, '시험학생', '발표자', %s)""",
            (TEMP_NO, service.hash_password("1234")),
        )
    yield TEMP_NO
    with psycopg.connect(DATABASE_URL) as c:
        c.execute("delete from tf_students where student_no = %s", (TEMP_NO,))


def run_login(student_no, password):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_input(key="login_student_no").input(student_no)
    at.text_input(key="login_password").input(password)
    at.button(key="login_submit").click().run()
    return at


def result_text(at):
    return " ".join(i.value for i in at.info)


def test_login_screen_has_keys():
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert at.text_input(key="login_student_no").label == "학번"
    assert at.text_input(key="login_password").label == "비밀번호"
    assert at.button(key="login_submit") is not None


def test_admin_logs_in_and_sees_admin_screen():
    at = run_login("admin", ADMIN_PASSWORD)
    assert not at.exception
    assert at.session_state["user_id"] is not None
    assert result_text(at).startswith("승인")
    assert any("관리자" in s.value for s in at.subheader)


def test_admin_number_only_is_blocked():
    at = run_login("admin", "")
    assert "user_id" not in at.session_state
    assert result_text(at).startswith("막힘")


def test_admin_wrong_password_is_blocked():
    at = run_login("admin", ADMIN_PASSWORD + "x")
    assert "user_id" not in at.session_state
    assert result_text(at) == "막힘: 학번 또는 비밀번호가 틀림"


def test_student_logs_in_without_admin_screen(temp_student):
    at = run_login(temp_student, "1234")
    assert not at.exception
    assert result_text(at).startswith("승인")
    subheaders = [s.value for s in at.subheader]
    assert "팀 목록" in subheaders and "관리자" not in subheaders


def test_logout_returns_to_login_screen(temp_student):
    at = run_login(temp_student, "1234")
    at.button(key="logout").click().run()
    assert "user_id" not in at.session_state
    assert at.text_input(key="login_student_no") is not None
