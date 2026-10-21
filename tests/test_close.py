# -*- coding: utf-8 -*-
# 작성일시: 2026-10-21 01:03 (KST)
"""#10 모집 마감(공고 2.5-1, 2.5-2). 부록 시나리오의 마감 단계를 실행한다(DB, 트랜잭션은 되돌림)."""
import pytest

from teamform import service
from teamform.board import load_board
from tests.scenarios import EASY, HARD, MEDIUM
from tests.test_apply_vote import Play, first


def admin(conn):
    return service.login(conn, "admin", "test-admin-pass")


def medium_until_step_8(conn):
    p = Play(conn, MEDIUM, 4)
    p.apply("학생1", 1); p.apply("학생5", 1); p.vote("학생1", "학생5")
    p.apply("학생2", 1)
    p.apply("학생6", 2); p.apply("학생9", 2); p.vote("학생6", "학생9")
    p.apply("학생10", 2); p.vote("학생6", "학생10"); p.vote("학생9", "학생10", yes=False)
    p.apply("학생3", 3); p.apply("학생11", 4)
    p.apply("학생12", 4); p.apply("학생12", 3)
    return p


def test_medium_step_9_and_10(conn):
    p = medium_until_step_8(conn)
    # 9 관리자가 마감: 학생12의 지원은 거절. 학생3과 학생11은 팀에서 빠짐
    message = service.close(conn, admin(conn))
    assert message == "승인: 모집을 마감함(대기 지원 1건 거절, 1명뿐인 팀의 학생 2명 빠짐)"
    status = conn.execute(
        "select a.status, a.reason from tf_applications a join tf_students s on s.id = a.student_id where s.name = '학생12'"
    ).fetchone()
    assert (status["status"], status["reason"]) == ("거절", "모집 마감")
    board = load_board(conn)
    assert [m.name for m in board.unassigned] == ["학생2", "학생3", "학생4", "학생7", "학생8", "학생10", "학생11", "학생12"]
    assert [len(t.members) for t in board.teams] == [2, 2, 0, 0]
    # 10 학생2가 팀3에 지원: 막힘(마감)
    assert p.apply("학생2", 3) == "막힘: 모집이 마감됨"


def test_hard_step_14(conn):
    p = Play(conn, HARD, 4)
    p.apply("학생1", 1); p.apply("학생4", 1); p.vote("학생1", "학생4")
    p.apply("학생7", 1); p.vote("학생1", "학생7"); p.vote("학생4", "학생7")
    p.apply("학생10", 4)
    p.apply("학생13", 1); p.vote("학생1", "학생13")
    # 14 관리자가 마감: 학생13의 지원은 거절. 학생10은 팀에서 빠짐
    assert first(service.close(conn, admin(conn))) == "승인"
    board = load_board(conn)
    assert "학생13" in [m.name for m in board.unassigned] and "학생10" in [m.name for m in board.unassigned]
    assert board.pending_of(board.unassigned[0].id) is None
    assert [len(t.members) for t in board.teams] == [3, 0, 0, 0]
    # 마감 뒤 늦게 누른 투표는 그 지원의 지금 상태(거절)를 보인다
    assert p.vote("학생4", "학생13") == "거절: 이미 결과가 나온 지원임(모집 마감)"


def test_two_member_team_stays(conn):
    p = Play(conn, EASY, 3)
    p.apply("학생1", 1); p.apply("학생4", 1); p.vote("학생1", "학생4")
    service.close(conn, admin(conn))
    assert [m.name for m in load_board(conn).team_by_no(1).members] == ["학생1", "학생4"]


def test_close_twice_is_blocked(conn):
    Play(conn, EASY, 3)
    assert first(service.close(conn, admin(conn))) == "승인"
    assert service.close(conn, admin(conn)) == "막힘: 이미 마감됨"


def test_student_cannot_close(conn):
    p = Play(conn, EASY, 3)
    with pytest.raises(PermissionError):
        service.close(conn, p.user("학생1"))
    assert load_board(conn).closed is False


def test_reset_after_close_reopens(conn):
    Play(conn, EASY, 3)
    service.close(conn, admin(conn))
    Play(conn, EASY, 3)  # 명단을 다시 올림
    assert load_board(conn).closed is False
