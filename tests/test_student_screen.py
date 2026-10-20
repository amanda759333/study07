# -*- coding: utf-8 -*-
# 작성일시: 2026-10-21 01:03 (KST)
"""#8 학생 화면을 AppTest로 확인한다(공고 2.7, 2.8).

앱은 실제 DB를 쓰므로, 테스트 전후에 쉬움 명단으로 처음 상태를 다시 만든다.
"""
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row
from streamlit.testing.v1 import AppTest

from teamform import service
from teamform.config import get_secret
from tests.scenarios import EASY, csv_bytes, numbers

DATABASE_URL = get_secret("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL 없음")
APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")
NO = numbers(EASY)


def reset_easy():
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
        admin = service.login(c, "admin", get_secret("ADMIN_PASSWORD"))
        service.reset_roster(c, admin, csv_bytes(EASY), 3)


@pytest.fixture
def board_state():
    """팀1에 학생1·학생4, 학생7이 팀1에 지원해 대기 중인 상태."""
    reset_easy()
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
        sid = {n: c.execute("select id from tf_students where student_no = %s", (no,)).fetchone()["id"] for n, no in NO.items()}
        t1 = c.execute("select id from tf_teams order by id limit 1").fetchone()["id"]
        c.execute("insert into tf_members values (%s, 1, %s), (%s, 2, %s)", (t1, sid["학생1"], t1, sid["학생4"]))
        c.execute("insert into tf_applications (team_id, student_id) values (%s, %s)", (t1, sid["학생7"]))
    yield
    reset_easy()


def login_as(name):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_input(key="login_student_no").input(NO[name])
    at.text_input(key="login_password").input("1234")
    at.button(key="login_submit").click().run()
    assert not at.exception
    return at


def texts(at):
    return " ".join(m.value for m in at.markdown)


def apply_disabled(at):
    return [at.button(key=f"apply_{n}").disabled for n in (1, 2, 3)]


def test_team_list_shows_members_and_roles(board_state):
    at = login_as("학생5")
    page = texts(at)
    assert "**팀1** (2/4)" in page and "**팀2** (0/4)" in page
    assert "학생1 (2026101) — 주 역할 기획자 · 보조 역할 보고서 작성자" in page
    assert "학생4 (2026104) — 주 역할 웹 프로그래머 · 보조 역할 프론트엔드 디자이너" in page


def test_no_team_shows_message_and_buttons_enabled(board_state):
    at = login_as("학생5")
    assert "아직 팀이 없음" in texts(at)
    assert apply_disabled(at) == [False, False, False]


def test_my_team_is_marked_and_buttons_disabled(board_state):
    """[공고 2.8] 이미 팀에 속했으면 지원 단추 비활성화."""
    at = login_as("학생1")
    page = texts(at)
    assert "내 팀: **팀1**" in page and "**팀1** (2/4) · **내 팀**" in page
    assert apply_disabled(at) == [True, True, True]


def test_waiting_application_disables_buttons(board_state):
    """[공고 2.8] 결과를 기다리는 지원이 있으면 지원 단추 비활성화."""
    at = login_as("학생7")
    assert any("결과를 기다리는 지원: 팀1 (팀원 2명 가운데 0명 찬성)" in c.value for c in at.caption)
    assert apply_disabled(at) == [True, True, True]


def test_closed_disables_buttons(board_state):
    """[공고 2.8] 모집이 마감되었으면 지원 단추 비활성화."""
    with psycopg.connect(DATABASE_URL) as c:
        c.execute("update tf_settings set value = 'true' where key = 'closed'")
    at = login_as("학생5")
    assert apply_disabled(at) == [True, True, True]
