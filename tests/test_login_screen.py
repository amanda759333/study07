# -*- coding: utf-8 -*-
# 작성일시: 2026-10-20 20:27 (KST)
"""#6 로그인 화면을 AppTest로 실제로 눌러 본다.

앱은 뜰 때 관리자 계정을 실제 DB에 만들거나 갱신한다(공고 2.1의 동작 그대로).
시험용 학생은 테스트 안에서 만들고 끝나면 지운다.
"""
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row
from streamlit.testing.v1 import AppTest

from teamform import service
from teamform.config import get_secret
from tests.scenarios import EASY, csv_bytes

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
    assert "명단 올리기" in [s.value for s in at.subheader]
    assert at.button(key="admin_start") is not None


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
    assert "팀 목록" in subheaders and "명단 올리기" not in subheaders
    assert not [b for b in at.button if b.key and b.key.startswith("admin_")]


def test_logout_returns_to_login_screen(temp_student):
    at = run_login(temp_student, "1234")
    at.button(key="logout").click().run()
    assert "user_id" not in at.session_state
    assert at.text_input(key="login_student_no") is not None


def test_admin_start_without_file_is_blocked():
    at = run_login("admin", ADMIN_PASSWORD)
    at.number_input(key="admin_team_count").set_value(4)
    at.button(key="admin_start").click().run()
    assert result_text(at) == "막힘: 명단 CSV 파일을 올리지 않음"


def test_admin_close_and_unassigned():
    """[공고 2.7] admin_close의 result와 unassigned(팀이 없는 학생 이름). 끝나면 명단을 다시 올려 마감을 푼다."""
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
        service.reset_roster(c, service.login(c, "admin", ADMIN_PASSWORD), csv_bytes(EASY), 3)
    try:
        at = run_login("admin", ADMIN_PASSWORD)
        assert any("학생1 (2026101)" in m.value for m in at.markdown)  # 마감 전에도 팀이 없는 학생이 보임
        at.button(key="admin_close").click().run()
        assert result_text(at) == "승인: 모집을 마감함(대기 지원 0건 거절, 1명뿐인 팀의 학생 0명 빠짐)"
        assert at.button(key="admin_close").disabled
    finally:
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
            service.reset_roster(c, service.login(c, "admin", ADMIN_PASSWORD), csv_bytes(EASY), 3)


def test_admin_assign_shows_status(monkeypatch):
    """[공고 2.7] admin_assign의 result와 assign_status(몇 차 모델의 결과). AI는 가짜로 바꾼다."""
    from teamform import ai

    tries = []

    def fake(model, prompt, timeout):
        tries.append(model)
        if len(tries) == 1:
            raise ai.AIError("HTTP 429", "사용량 제한")
        plan = {1: ["2026101", "2026104", "2026107"], 2: ["2026102", "2026105", "2026108"], 3: ["2026103", "2026106"]}
        items = [f'{{"student_no": "{no}", "team_no": {t}}}' for t, nos in plan.items() for no in nos]
        return '{"assignments": [' + ", ".join(items) + "]}"

    monkeypatch.setattr(ai, "call_model", fake)
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
        service.reset_roster(c, service.login(c, "admin", ADMIN_PASSWORD), csv_bytes(EASY), 3)
    try:
        at = run_login("admin", ADMIN_PASSWORD)
        at.button(key="admin_assign").click().run()
        assert result_text(at) == "막힘: 모집이 마감되지 않음"

        at.button(key="admin_close").click().run()
        at.button(key="admin_assign").click().run()
        assert result_text(at) == "승인: 2차 모델의 배정안이 검사를 통과함"
        status = " ".join(m.value for m in at.markdown)
        assert "1차 google/gemma-4-31b-it:free: HTTP 429" in status
        assert "2차 minimax/minimax-m3.1-flash:free: 성공" in status
        assert len(at.dataframe[0].value) == 8  # 배정안 표: 8명
        at.button(key="admin_confirm").click().run()
        assert result_text(at) == "승인: 배정안을 확정함(8명)"
        assert any("팀이 없는 학생이 없음" in m.value for m in at.markdown)
        assert at.button(key="admin_confirm").disabled
    finally:
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
            service.reset_roster(c, service.login(c, "admin", ADMIN_PASSWORD), csv_bytes(EASY), 3)



def test_refresh_button_on_both_screens(temp_student):
    """[공고 2.7] 새로 고침 단추(refresh)를 학생 화면과 관리자 화면 양쪽에 둔다."""
    student = run_login(temp_student, "1234")
    assert student.button(key="refresh") is not None
    student.button(key="refresh").click().run()
    assert not student.exception and "user_id" in student.session_state
    admin = run_login("admin", ADMIN_PASSWORD)
    assert admin.button(key="refresh") is not None


def test_all_models_fail_app_assigns(monkeypatch):
    """[공고 2.5-6] 3차 모델까지 실패하면 앱이 배정안을 만들고, 확정까지 된다."""
    from teamform import ai

    def fail(model, prompt, timeout):
        raise ai.AIError("HTTP 429", "사용량 제한")

    monkeypatch.setattr(ai, "call_model", fail)
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
        service.reset_roster(c, service.login(c, "admin", ADMIN_PASSWORD), csv_bytes(EASY), 3)
    try:
        at = run_login("admin", ADMIN_PASSWORD)
        at.button(key="admin_close").click().run()
        at.button(key="admin_assign").click().run()
        assert result_text(at) == "승인: 3차 모델까지 실패해 앱이 모든 경우를 따져 배정함(검사 다섯 가지 통과)"
        status = " ".join(m.value for m in at.markdown)
        assert "3차 dots-studio/dots-3-note-preview:free: HTTP 429" in status
        assert "앱이 모든 경우를 따져 만든 배정안" in status
        at.button(key="admin_confirm").click().run()
        assert result_text(at) == "승인: 배정안을 확정함(8명)"
    finally:
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
            service.reset_roster(c, service.login(c, "admin", ADMIN_PASSWORD), csv_bytes(EASY), 3)
