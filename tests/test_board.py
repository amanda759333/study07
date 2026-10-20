# -*- coding: utf-8 -*-
# 작성일시: 2026-10-21 01:03 (KST)
"""#8 지금의 팀 구성 읽기(load_board). DB 트랜잭션은 테스트가 끝나면 되돌린다."""
import pytest

from teamform import service
from teamform.board import load_board
from tests.scenarios import EASY, csv_bytes, numbers

NO = numbers(EASY)


@pytest.fixture
def ids(conn):
    service.ensure_admin(conn, "test-admin-pass")
    admin = service.login(conn, "admin", "test-admin-pass")
    service.reset_roster(conn, admin, csv_bytes(EASY), 3)
    return {name: conn.execute("select id from tf_students where student_no = %s", (no,)).fetchone()["id"]
            for name, no in NO.items()}


def team_id(conn, n):
    return conn.execute("select id from tf_teams order by id offset %s limit 1", (n - 1,)).fetchone()["id"]


def test_empty_board_after_reset(conn, ids):
    board = load_board(conn)
    assert [(t.no, t.name, t.members, t.pending) for t in board.teams] == [
        (1, "팀1", [], []), (2, "팀2", [], []), (3, "팀3", [], [])
    ]
    assert board.closed is False


def test_members_pending_and_votes(conn, ids):
    t1 = team_id(conn, 1)
    conn.execute("insert into tf_members values (%s, 1, %s), (%s, 2, %s)", (t1, ids["학생1"], t1, ids["학생4"]))
    app = conn.execute("insert into tf_applications (team_id, student_id) values (%s, %s) returning id",
                       (t1, ids["학생7"])).fetchone()["id"]
    conn.execute("insert into tf_votes values (%s, %s, '찬성')", (app, ids["학생1"]))

    board = load_board(conn)
    team1 = board.team_by_no(1)
    assert [m.name for m in team1.members] == ["학생1", "학생4"]
    assert team1.members[0].roles_text() == "주 역할 기획자 · 보조 역할 보고서 작성자"
    assert board.team_of(ids["학생4"]).name == "팀1"
    assert board.team_of(ids["학생7"]) is None

    waiting = board.pending_of(ids["학생7"])
    assert waiting.team_id == t1 and waiting.applicant.name == "학생7"
    assert waiting.votes == {ids["학생1"]: "찬성"}
    assert board.pending_of(ids["학생5"]) is None


def test_decided_applications_are_not_pending(conn, ids):
    t1 = team_id(conn, 1)
    conn.execute("insert into tf_applications (team_id, student_id, status) values (%s, %s, '거절')", (t1, ids["학생7"]))
    assert load_board(conn).pending_of(ids["학생7"]) is None


def test_closed_flag_and_team_lookup(conn, ids):
    conn.execute("update tf_settings set value = 'true' where key = 'closed'")
    board = load_board(conn)
    assert board.closed is True
    assert board.team_by_no(0) is None and board.team_by_no(4) is None
