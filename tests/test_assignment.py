# -*- coding: utf-8 -*-
# 작성일시: 2026-10-21 01:03 (KST)
"""#12 배정안 검사 다섯 가지와 #13 규칙을 지키는 배정 찾기(공고 2.5-4, 2.5-8). DB 없이 순수 함수만."""
import pytest

from teamform.board import Board, Member, Team
from teamform.rules import check_assignment, required_filled
from teamform.solver import find_assignment, why_impossible
from tests.scenarios import EASY, HARD, MEDIUM


def people(rows):
    """명단 줄 → 이름별 Member. id는 학번 숫자."""
    out = {}
    for row in rows:
        no, name, main, subs = row.split(",")
        out[name] = Member(int(no), no, name, main, tuple(s for s in subs.split(";") if s))
    return out


def board(rows, teams, unassigned):
    p = people(rows)
    return Board(
        teams=[Team(i, i, f"팀{i}", [p[n] for n in names]) for i, names in enumerate(teams, start=1)],
        closed=True,
        unassigned=[p[n] for n in unassigned],
    )


# 부록의 기대 결과대로 마감한 뒤의 상태
EASY_CLOSED = board(EASY, [["학생1", "학생4"], ["학생2", "학생5"], ["학생3", "학생6"]], ["학생7", "학생8"])
MEDIUM_CLOSED = board(MEDIUM, [["학생1", "학생5"], ["학생6", "학생9"], [], []],
                      ["학생2", "학생3", "학생4", "학생7", "학생8", "학생10", "학생11", "학생12"])
HARD_CLOSED = board(HARD, [["학생1", "학생4", "학생7"], ["학생2", "학생8", "학생5"], ["학생11", "학생15"], []],
                    ["학생3", "학생6", "학생9", "학생10", "학생12", "학생13", "학생14", "학생16"])

NO = {name: m.student_no for name, m in people(MEDIUM).items()}
# 2026-10-21 실제 2차 모델(minimax)이 낸 중간 시나리오 배정안
MEDIUM_AI_PLAN = [(NO[n], t) for n, t in [("학생2", 2), ("학생3", 3), ("학생7", 3), ("학생10", 3), ("학생11", 3),
                                         ("학생4", 4), ("학생8", 4), ("학생12", 4)]]


# 필수 포함 역할 채운 수(공고 3장 「필수 포함 역할 자리 계산」) -------------------------

def m(i, main, *subs):
    return Member(i, f"S{i}", f"학생{i}", main, subs)


@pytest.mark.parametrize("members, filled", [
    ([m(1, "기획자", "웹 프로그래머")], 1),               # 공고 예: 둘 다 할 수 있는 학생 혼자면 1개만
    ([m(1, "테스터"), m(2, "발표자")], 0),                 # 공고 예: 테스터와 발표자만 있는 팀
    ([m(1, "기획자"), m(2, "테스터", "기획자")], 1),        # 둘 다 기획자만 할 수 있음
    ([m(1, "기획자", "웹 프로그래머"), m(2, "웹 프로그래머")], 2),
    ([m(1, "테스터", "기획자"), m(2, "프론트엔드 디자이너", "웹 프로그래머")], 2),  # 보조 역할만으로 둘 다
])
def test_required_filled(members, filled):
    assert required_filled(members) == filled


# 검사 다섯 가지 ------------------------------------------------------------------

def test_real_ai_plan_passes():
    assert check_assignment(MEDIUM_CLOSED, MEDIUM_AI_PLAN) == []


def test_1_missing_student():
    plan = [p for p in MEDIUM_AI_PLAN if p[0] != NO["학생12"]]
    assert "① 학생12(2026212)이 배정되지 않음" in check_assignment(MEDIUM_CLOSED, plan)


def test_2_student_in_two_teams():
    plan = MEDIUM_AI_PLAN + [(NO["학생12"], 3)]
    assert "② 학생12(2026212)이 여러 번 배정됨(팀4, 팀3)" in check_assignment(MEDIUM_CLOSED, plan)


def test_3_team_size():
    plan = [(no, 3 if team == 4 else team) for no, team in MEDIUM_AI_PLAN]  # 팀4 학생을 팀3으로
    problems = check_assignment(MEDIUM_CLOSED, plan)
    assert "③ 팀3이 7명임(2~4명이어야 함)" in problems and "③ 팀4이 0명임(2~4명이어야 함)" in problems


def test_4_duplicate_main_role():
    plan = [(no, 3 if no == NO["학생8"] else team) for no, team in MEDIUM_AI_PLAN]  # 웹 프로그래머 학생8도 팀3으로
    assert "④ 팀3에 주 역할이 웹 프로그래머인 학생이 2명(학생7, 학생8)" in check_assignment(MEDIUM_CLOSED, plan)


def test_5_required_roles_with_different_people():
    plan = [(NO["학생4"], 2) if no == NO["학생2"] else (NO["학생2"], 4) if no == NO["학생4"] else (no, t)
            for no, t in MEDIUM_AI_PLAN]
    assert check_assignment(MEDIUM_CLOSED, plan) == []  # 기획자끼리 바꿔도 통과
    plan = [(no, 2 if no == NO["학생8"] else 4 if no == NO["학생2"] else t) for no, t in MEDIUM_AI_PLAN]
    problems = check_assignment(MEDIUM_CLOSED, plan)
    assert "⑤ 팀2에 기획자와 웹 프로그래머를 서로 다른 사람으로 둘 수 없음(기획자 가능: 없음, 웹 프로그래머 가능: 학생6, 학생9, 학생8)" in problems
    assert any(p.startswith("④ 팀2에 주 역할이 웹 프로그래머") for p in problems)


def test_moving_existing_member_is_rejected():
    plan = MEDIUM_AI_PLAN + [(NO["학생1"], 3)]
    assert "2026201은 팀이 없는 학생이 아님" in check_assignment(MEDIUM_CLOSED, plan)


# 규칙을 지키는 배정 찾기 ------------------------------------------------------------

@pytest.mark.parametrize("closed", [EASY_CLOSED, MEDIUM_CLOSED, HARD_CLOSED], ids=["쉬움", "중간", "어려움"])
def test_finds_plan_that_passes_five_checks(closed):
    plan = find_assignment(closed)
    assert plan is not None
    assert check_assignment(closed, plan) == []


def test_hard_needs_planner_and_web_in_team3():
    """어려움: 팀3(테스터·발표자)의 남은 두 자리는 기획자와 웹 프로그래머로 채워야 한다."""
    plan = dict(find_assignment(HARD_CLOSED))
    team3 = {name for name, mem in people(HARD).items() if plan.get(mem.student_no) == 3}
    assert "학생3" in team3 and team3 & {"학생6", "학생9"}


def test_nothing_to_assign_but_rules_kept():
    full = board(EASY, [["학생1", "학생4", "학생7"], ["학생2", "학생5", "학생8"], ["학생3", "학생6"]], [])
    assert find_assignment(full) == []


def test_impossible_full_team_without_web():
    """공고 2.3 예: 웹 프로그래머를 맡을 수 있는 학생 없이 4명이 다 찬 팀은 끝까지 채우지 못한다."""
    impossible = board(HARD, [["학생1", "학생7", "학생10", "학생13"], ["학생2", "학생5"]], ["학생9", "학생11"])
    assert find_assignment(impossible) is None
    reasons = why_impossible(impossible)
    assert "팀1에 웹 프로그래머를 맡을 학생이 없음" in reasons
    assert "팀1에 자리가 0개 남았는데 채우지 못한 필수 포함 역할이 1개임" in reasons


def test_impossible_too_few_students():
    impossible = board(EASY, [[], [], []], ["학생1", "학생4", "학생7", "학생8"])
    assert find_assignment(impossible) is None
    assert "모든 팀을 2명 이상으로 채우려면 6명이 필요한데 팀이 없는 학생은 4명임" in why_impossible(impossible)
