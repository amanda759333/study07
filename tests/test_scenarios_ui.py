# -*- coding: utf-8 -*-
# 작성일시: 2026-10-21 01:03 (KST)
"""#16 공고 부록의 연습 시나리오 3개를 화면으로 처음부터 끝까지 실행한다(AppTest).

채점 프로그램처럼 학생마다 화면을 따로 열고, 동작하기 전에 화면을 다시 그리고(refresh 단추가 있으면 누르지만
이 앱은 두지 않으므로 자동으로 다시 그려진 것과 같게 한 번 더 그림), 단추가 없거나 비활성이면 "막힘"으로 본다(공고 2.7). 동작마다 result의 첫 단어를 부록의 기대 결과와 비교한다.
AI는 무료 한도를 쓰지 않도록 세 모델 모두 실패하게 바꾼다(3차까지 실패하면 앱이 배정하는 길로 감).

시나리오 단계는 이 테스트에만 있다. 앱 코드는 시나리오 이름·순서·학생 이름을 모른다(공고 6.3-19).
"""
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row
from streamlit.testing.v1 import AppTest

from teamform import ai, service
from teamform.board import load_board
from teamform.config import get_secret
from teamform.roster import parse_roster
from teamform.rules import check_assignment
from tests.scenarios import EASY, HARD, MEDIUM, csv_bytes

DATABASE_URL = get_secret("DATABASE_URL")
ADMIN_PASSWORD = get_secret("ADMIN_PASSWORD")
pytestmark = pytest.mark.skipif(not (DATABASE_URL and ADMIN_PASSWORD), reason="비밀 값 없음")
APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")
DATA = Path(__file__).resolve().parent.parent / "data"  # e-class에서 받은 연습 시나리오 명단(가상 학생)


def roster(file_name, rows):
    """e-class에서 받은 실제 명단 파일이 있으면 그대로, 없으면 부록 표로 만든 명단."""
    path = DATA / file_name
    return path.read_bytes() if path.exists() else csv_bytes(rows)

# 부록의 단계. ("지원", 이름, 팀, 기대) / ("찬성"·"거부", 투표자, 지원자, 기대) / ("마감", 기대) / ("배정확정",)
EASY_STEPS = [
    ("지원", "학생1", 1, "승인"), ("지원", "학생2", 2, "승인"), ("지원", "학생3", 3, "승인"),              # 1
    ("지원", "학생4", 1, "대기"), ("찬성", "학생1", "학생4", "승인"),                                    # 2
    ("지원", "학생5", 2, "대기"), ("찬성", "학생2", "학생5", "승인"),                                    # 3
    ("지원", "학생7", 1, "대기"), ("찬성", "학생1", "학생7", "대기"), ("거부", "학생4", "학생7", "거절"),  # 4
    ("지원", "학생6", 3, "대기"), ("찬성", "학생3", "학생6", "승인"),                                    # 5
    ("마감", "승인"), ("배정확정",),                                                                    # 6
]
MEDIUM_STEPS = [
    ("지원", "학생1", 1, "승인"),                                                                       # 1
    ("지원", "학생5", 1, "대기"), ("찬성", "학생1", "학생5", "승인"),                                    # 2
    ("지원", "학생2", 1, "막힘"),                                                     # 3 (막혔으므로 뒤의 투표는 건너뜀)
    ("지원", "학생6", 2, "승인"),                                                                       # 4
    ("지원", "학생9", 2, "대기"), ("찬성", "학생6", "학생9", "승인"),                                    # 5
    ("지원", "학생10", 2, "대기"), ("찬성", "학생6", "학생10", "대기"), ("거부", "학생9", "학생10", "거절"),  # 6
    ("지원", "학생3", 3, "승인"), ("지원", "학생11", 4, "승인"),                                         # 7
    ("지원", "학생12", 4, "대기"), ("지원", "학생12", 3, "막힘"),                                        # 8
    ("마감", "승인"),                                                                                  # 9
    ("지원", "학생2", 3, "막힘"),                                                                       # 10
    ("배정확정",),                                                                                     # 11
]
HARD_STEPS = [
    ("지원", "학생1", 1, "승인"),                                                                       # 1
    ("지원", "학생4", 1, "대기"), ("찬성", "학생1", "학생4", "승인"),                                    # 2
    ("지원", "학생7", 1, "대기"), ("찬성", "학생1", "학생7", "대기"), ("찬성", "학생4", "학생7", "승인"),  # 3
    ("지원", "학생2", 2, "승인"),                                                                       # 4
    ("지원", "학생8", 2, "대기"), ("찬성", "학생2", "학생8", "승인"),                                    # 5
    ("지원", "학생5", 2, "대기"), ("지원", "학생6", 2, "대기"),                                          # 6
    ("찬성", "학생2", "학생5", "대기"), ("찬성", "학생8", "학생5", "승인"),                              # 7
    ("찬성", "학생2", "학생6", "대기"), ("찬성", "학생8", "학생6", "대기"), ("찬성", "학생5", "학생6", "거절"),  # 8
    ("지원", "학생11", 3, "승인"),                                                                      # 9
    ("지원", "학생15", 3, "대기"), ("찬성", "학생11", "학생15", "승인"),                                 # 10
    ("지원", "학생14", 3, "막힘"),                                                                      # 11
    ("지원", "학생10", 4, "승인"),                                                                      # 12
    ("지원", "학생13", 1, "대기"), ("찬성", "학생1", "학생13", "대기"),                                  # 13
    ("마감", "승인"),                                                                                  # 14
    ("배정확정",),                                                                                     # 15
]


class Grader:
    """채점 프로그램 흉내: 사람마다 화면 하나, 동작 전에 다시 그림, 단추가 없거나 꺼져 있으면 막힘."""

    def __init__(self, data):
        # 실제 명단의 이름은 "학생1(PL;PT;TT)"처럼 역할 약자가 붙어 있으므로 "학생1"로 찾는다
        self.no = {r.name.split("(")[0]: r.student_no for r in parse_roster(data)}
        self.screens = {}

    def screen(self, who, student_no, password):
        if who not in self.screens:
            at = AppTest.from_file(APP, default_timeout=60).run()
            at.text_input(key="login_student_no").input(student_no)
            at.text_input(key="login_password").input(password)
            at.button(key="login_submit").click().run()
            assert not at.exception, at.exception
            self.screens[who] = at
        at = self.screens[who]
        refresh = [b for b in at.button if b.key == "refresh"]
        if refresh:  # 공고 2.7: 채점 프로그램은 이 단추가 있으면 먼저 누른다
            refresh[0].click().run()
        else:  # 없으면 자동으로 다시 그려지기를 기다린다(이 앱은 3초마다 다시 그림)
            at.run()
        return at

    def press(self, who, key, student_no=None, password="1234"):
        at = self.screen(who, student_no or self.no[who], password)
        found = [b for b in at.button if b.key == key]
        if not found or found[0].disabled:
            return "막힘(단추 없음·비활성)"
        found[0].click().run()
        assert not at.exception, at.exception
        return " ".join(i.value for i in at.info)

    def admin(self, key):
        return self.press("admin", key, "admin", ADMIN_PASSWORD)


def play(data, team_count, steps, monkeypatch):
    def all_fail(model, prompt, timeout):
        raise ai.AIError("HTTP 429", "사용량 제한")

    monkeypatch.setattr(ai, "call_model", all_fail)
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
        service.reset_roster(c, service.login(c, "admin", ADMIN_PASSWORD), data, team_count)
    g = Grader(data)
    log = []
    try:
        for step in steps:
            kind = step[0]
            if kind == "지원":
                _, who, team, want = step
                got = g.press(who, f"apply_{team}")
            elif kind in ("찬성", "거부"):
                _, who, applicant, want = step
                got = g.press(who, f"vote_{'yes' if kind == '찬성' else 'no'}_{g.no[applicant]}")
            elif kind == "마감":
                want, got = step[1], g.admin("admin_close")
            else:  # 배정확정
                got_assign, got_confirm = g.admin("admin_assign"), g.admin("admin_confirm")
                log.append((step, "승인", got_assign))
                want, got = "승인", got_confirm
            log.append((step, want, got))
        mismatches = [(s, w, g_) for s, w, g_ in log if not g_.startswith(w)]
        assert not mismatches, mismatches
        # 마지막에 새로 열어(DB에서 다시 읽어) 확정한 팀 구성이 남아 있고 규칙을 지키는지(공고 6.2-5)
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
            board = load_board(c)
        assert board.unassigned == []
        assert check_assignment(board, []) == []
    finally:
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
            service.reset_roster(c, service.login(c, "admin", ADMIN_PASSWORD), csv_bytes(EASY), 3)
    return log


def test_easy(monkeypatch):
    play(roster("쉬움.csv", EASY), 3, EASY_STEPS, monkeypatch)


def test_medium(monkeypatch):
    log = play(roster("중간.csv", MEDIUM), 4, MEDIUM_STEPS, monkeypatch)
    blocked = [got for step, want, got in log if want == "막힘"]
    assert blocked[0] == "막힘: 같은 주 역할의 팀원이 있음"   # 3단계는 단추를 누른 뒤 이유와 함께
    assert blocked[1].startswith("막힘(단추 없음·비활성)")   # 8단계 팀3은 대기 지원이 있어 단추가 꺼짐
    assert blocked[2].startswith("막힘(단추 없음·비활성)")   # 10단계는 마감되어 단추가 꺼짐


def test_hard(monkeypatch):
    play(roster("어려움.csv", HARD), 4, HARD_STEPS, monkeypatch)
