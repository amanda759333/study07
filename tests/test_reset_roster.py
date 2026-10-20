# -*- coding: utf-8 -*-
# 작성일시: 2026-10-20 20:37 (KST)
"""#7 명단 올리기와 초기화(공고 2.6). DB 트랜잭션은 테스트가 끝나면 되돌린다."""
import pytest

from teamform import service
from teamform.roster import RosterError

EASY = (
    "student_no,name,main_role,sub_roles\r\n"
    "2026101,학생1,기획자,보고서 작성자\r\n"
    "2026102,학생2,기획자,발표자\r\n"
    "2026103,학생3,기획자,테스터\r\n"
    "2026104,학생4,웹 프로그래머,프론트엔드 디자이너\r\n"
    "2026105,학생5,웹 프로그래머,\r\n"
    "2026106,학생6,웹 프로그래머,테스터\r\n"
    "2026107,학생7,프론트엔드 디자이너,발표자\r\n"
    "2026108,학생8,테스터,보고서 작성자;발표자\r\n"
).encode("utf-8-sig")

SMALL = "student_no,name,main_role,sub_roles\n2026001,가나다,기획자,보고서 작성자\n2026002,라마바,웹 프로그래머,\n".encode("utf-8-sig")


@pytest.fixture
def admin(conn):
    service.ensure_admin(conn, "test-admin-pass")
    return service.login(conn, "admin", "test-admin-pass")


def count(conn, table, where="true"):
    return conn.execute(f"select count(*) as n from {table} where {where}").fetchone()["n"]


def make_dirty_state(conn, admin):
    """지원·투표·팀원·마감 표시가 모두 있는 상태를 만든다."""
    service.reset_roster(conn, admin, SMALL, 2)
    ids = {r["student_no"]: r["id"] for r in conn.execute("select id, student_no from tf_students")}
    team = conn.execute("select id from tf_teams order by id limit 1").fetchone()["id"]
    conn.execute("insert into tf_members values (%s, 1, %s)", (team, ids["2026001"]))
    app = conn.execute(
        "insert into tf_applications (team_id, student_id) values (%s, %s) returning id", (team, ids["2026002"])
    ).fetchone()["id"]
    conn.execute("insert into tf_votes values (%s, %s, '찬성')", (app, ids["2026001"]))
    conn.execute("update tf_settings set value = 'true' where key = 'closed'")


def test_reset_makes_students_and_empty_teams(conn, admin):
    message = service.reset_roster(conn, admin, EASY, 3)
    assert message == "승인: 명단 8명, 팀 3개로 처음 상태를 만듦"
    assert count(conn, "tf_students", "not is_admin") == 8
    teams = [r["name"] for r in conn.execute("select name from tf_teams order by id")]
    assert teams == ["팀1", "팀2", "팀3"]
    assert count(conn, "tf_members") == 0
    assert service.is_closed(conn) is False


def test_reset_stores_roles_and_hashed_1234(conn, admin):
    service.reset_roster(conn, admin, EASY, 3)
    student = service.login(conn, "2026108", "1234")
    assert (student.name, student.main_role, student.sub_roles) == ("학생8", "테스터", ("발표자", "보고서 작성자"))
    assert service.login(conn, "2026105", "1234").sub_roles == ()
    hashes = [r["password_hash"] for r in conn.execute("select password_hash from tf_students where not is_admin")]
    assert all(h.startswith("$2") and h != "1234" for h in hashes)
    assert len(set(hashes)) == len(hashes)  # 학생마다 salt가 다름


def test_reset_clears_applications_votes_members_and_close_flag(conn, admin):
    make_dirty_state(conn, admin)
    assert count(conn, "tf_applications") == 1 and count(conn, "tf_votes") == 1 and service.is_closed(conn)

    service.reset_roster(conn, admin, EASY, 4)
    assert count(conn, "tf_applications") == 0
    assert count(conn, "tf_votes") == 0
    assert count(conn, "tf_members") == 0
    assert service.is_closed(conn) is False
    assert service.login(conn, "2026001", "1234") is None  # 옛 명단의 학생은 사라짐
    assert [r["name"] for r in conn.execute("select name from tf_teams order by id")] == ["팀1", "팀2", "팀3", "팀4"]


def test_admin_survives_reset(conn, admin):
    service.reset_roster(conn, admin, EASY, 3)
    service.reset_roster(conn, admin, SMALL, 2)
    again = service.login(conn, "admin", "test-admin-pass")
    assert again is not None and again.is_admin and again.id == admin.id


def test_student_cannot_reset(conn, admin):
    service.reset_roster(conn, admin, EASY, 3)
    student = service.login(conn, "2026101", "1234")
    with pytest.raises(PermissionError):
        service.reset_roster(conn, student, SMALL, 2)
    assert count(conn, "tf_students", "not is_admin") == 8


def test_wrong_csv_changes_nothing(conn, admin):
    service.reset_roster(conn, admin, EASY, 3)
    with pytest.raises(RosterError):
        service.reset_roster(conn, admin, "student_no,name,main_role,sub_roles\n2026001,가나다,디자이너,\n".encode(), 2)
    assert count(conn, "tf_students", "not is_admin") == 8
    assert count(conn, "tf_teams") == 3


@pytest.mark.parametrize("bad", [0, -1])
def test_team_count_must_be_positive(conn, admin, bad):
    with pytest.raises(ValueError):
        service.reset_roster(conn, admin, EASY, bad)
