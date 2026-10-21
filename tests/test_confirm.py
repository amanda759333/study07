# -*- coding: utf-8 -*-
# 작성일시: 2026-10-21 01:03 (KST)
"""#12 배정안 확정(공고 2.5-7). 부록 중간 시나리오를 마감까지 진행하고 확정한다(DB, 트랜잭션은 되돌림)."""
import pytest

from teamform import service
from teamform.board import load_board
from teamform.rules import check_assignment
from tests.test_assignment import MEDIUM_AI_PLAN
from tests.test_close import admin, medium_until_step_8


@pytest.fixture
def closed_medium(conn):
    p = medium_until_step_8(conn)
    service.close(conn, admin(conn))
    return p


def test_confirm_saves_plan(conn, closed_medium):
    before = load_board(conn)
    assert check_assignment(before, MEDIUM_AI_PLAN) == []
    assert service.confirm(conn, admin(conn), MEDIUM_AI_PLAN) == "승인: 배정안을 확정함(8명)"
    after = load_board(conn)
    assert after.unassigned == []
    assert [[m.name for m in t.members] for t in after.teams] == [
        ["학생1", "학생5"],
        ["학생6", "학생9", "학생2"],
        ["학생3", "학생7", "학생10", "학생11"],
        ["학생4", "학생8", "학생12"],
    ]


def test_confirm_twice_is_blocked(conn, closed_medium):
    service.confirm(conn, admin(conn), MEDIUM_AI_PLAN)
    message = service.confirm(conn, admin(conn), MEDIUM_AI_PLAN)
    assert message.startswith("막힘: 배정안이 지금 상태와 맞지 않음(")


def test_confirm_rejects_plan_that_breaks_rules(conn, closed_medium):
    bad = [(no, 3) for no, _ in MEDIUM_AI_PLAN]  # 모두 팀3으로
    assert service.confirm(conn, admin(conn), bad).startswith("막힘: 배정안이 지금 상태와 맞지 않음(⑤ 팀2에 기획자와")
    assert len(load_board(conn).unassigned) == 8  # 아무것도 저장하지 않음


def test_confirm_without_plan_or_close(conn):
    medium_until_step_8(conn)
    assert service.confirm(conn, admin(conn), None) == "막힘: 확정할 배정안이 없음"
    assert service.confirm(conn, admin(conn), MEDIUM_AI_PLAN) == "막힘: 모집이 마감되지 않음"


def test_student_cannot_confirm(conn, closed_medium):
    with pytest.raises(PermissionError):
        service.confirm(conn, closed_medium.user("학생1"), MEDIUM_AI_PLAN)
