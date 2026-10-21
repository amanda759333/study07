# -*- coding: utf-8 -*-
# 작성일시: 2026-10-21 01:03 (KST)
"""#9 지원과 투표를 공고 부록 시나리오의 단계대로 실행한다(DB, 트랜잭션은 되돌림).

결과 안내의 첫 단어가 부록의 기대 결과와 같은지 본다.
"""
import pytest

from teamform import service
from tests.scenarios import EASY, HARD, MEDIUM, csv_bytes, numbers


class Play:
    """시나리오 단계를 실행하는 도우미. 이름은 명단의 이름(학생1, …)."""

    def __init__(self, conn, rows, team_count):
        service.ensure_admin(conn, "test-admin-pass")
        admin = service.login(conn, "admin", "test-admin-pass")
        service.reset_roster(conn, admin, csv_bytes(rows), team_count)
        self.conn, self.no, self.users = conn, numbers(rows), {}

    def user(self, name):
        if name not in self.users:
            self.users[name] = service.login(self.conn, self.no[name], "1234")
        return self.users[name]

    def apply(self, name, team_no):
        return service.apply(self.conn, self.user(name), team_no)

    def vote(self, voter, applicant, yes=True):
        return service.vote(self.conn, self.user(voter), self.no[applicant], yes)

    def count(self, table):
        return self.conn.execute(f"select count(*) as n from {table}").fetchone()["n"]


def first(message):
    return message.split(":")[0]


def test_easy_steps_1_to_5(conn):
    p = Play(conn, EASY, 3)
    # 1 학생1→팀1, 학생2→팀2, 학생3→팀3: 3명 모두 바로 승인
    assert [first(p.apply("학생1", 1)), first(p.apply("학생2", 2)), first(p.apply("학생3", 3))] == ["승인"] * 3
    # 2 학생4→팀1, 학생1 찬성: 승인
    assert first(p.apply("학생4", 1)) == "대기"
    assert first(p.vote("학생1", "학생4")) == "승인"
    # 3 학생5→팀2, 학생2 찬성: 승인
    assert first(p.apply("학생5", 2)) == "대기"
    assert first(p.vote("학생2", "학생5")) == "승인"
    # 4 학생7→팀1, 학생1 찬성, 학생4 거부: 거절
    assert first(p.apply("학생7", 1)) == "대기"
    assert p.vote("학생1", "학생7") == "대기: 팀원 2명 가운데 1명 찬성"
    assert first(p.vote("학생4", "학생7", yes=False)) == "거절"
    # 5 학생6→팀3, 학생3 찬성: 승인
    assert first(p.apply("학생6", 3)) == "대기"
    assert first(p.vote("학생3", "학생6")) == "승인"
    assert p.count("tf_members") == 6


def test_medium_steps_1_to_8(conn):
    p = Play(conn, MEDIUM, 4)
    assert first(p.apply("학생1", 1)) == "승인"                      # 1 바로 승인
    assert first(p.apply("학생5", 1)) == "대기"                      # 2
    assert first(p.vote("학생1", "학생5")) == "승인"
    apps_before = p.count("tf_applications")
    assert p.apply("학생2", 1) == "막힘: 같은 주 역할의 팀원이 있음"    # 3 막힘(주 역할 중복), 뒤의 투표는 건너뜀
    assert p.count("tf_applications") == apps_before                 # 막힘은 DB에 기록하지 않음
    assert first(p.apply("학생6", 2)) == "승인"                      # 4 바로 승인
    assert first(p.apply("학생9", 2)) == "대기"                      # 5
    assert first(p.vote("학생6", "학생9")) == "승인"
    assert first(p.apply("학생10", 2)) == "대기"                     # 6 학생6 찬성, 학생9 거부: 거절
    assert first(p.vote("학생6", "학생10")) == "대기"
    assert first(p.vote("학생9", "학생10", yes=False)) == "거절"
    assert first(p.apply("학생3", 3)) == "승인"                      # 7 2명 모두 바로 승인
    assert first(p.apply("학생11", 4)) == "승인"
    assert first(p.apply("학생12", 4)) == "대기"                     # 8 팀4 지원은 대기, 팀3 지원은 막힘
    assert p.apply("학생12", 3) == "막힘: 결과를 기다리는 지원이 있음"


def test_hard_steps_1_to_13(conn):
    p = Play(conn, HARD, 4)
    assert first(p.apply("학생1", 1)) == "승인"                      # 1
    assert first(p.apply("학생4", 1)) == "대기"                      # 2
    assert first(p.vote("학생1", "학생4")) == "승인"
    assert first(p.apply("학생7", 1)) == "대기"                      # 3
    assert first(p.vote("학생1", "학생7")) == "대기"
    assert first(p.vote("학생4", "학생7")) == "승인"
    assert first(p.apply("학생2", 2)) == "승인"                      # 4
    assert first(p.apply("학생8", 2)) == "대기"                      # 5
    assert first(p.vote("학생2", "학생8")) == "승인"
    assert first(p.apply("학생5", 2)) == "대기"                      # 6 2명 모두 대기
    assert first(p.apply("학생6", 2)) == "대기"
    assert first(p.vote("학생2", "학생5")) == "대기"                 # 7 학생2·학생8 찬성: 승인
    assert first(p.vote("학생8", "학생5")) == "승인"
    # 8 학생2·학생8·학생5가 학생6에 찬성: 거절(승인 직전 검사). 학생5가 먼저 팀원이 되어 웹 프로그래머가 겹침
    assert first(p.vote("학생2", "학생6")) == "대기"
    assert first(p.vote("학생8", "학생6")) == "대기"
    assert p.vote("학생5", "학생6") == "거절: 승인 직전 검사에서 같은 주 역할의 팀원이 있음"
    assert first(p.apply("학생11", 3)) == "승인"                     # 9
    assert first(p.apply("학생15", 3)) == "대기"                     # 10
    assert first(p.vote("학생11", "학생15")) == "승인"
    apps_before = p.count("tf_applications")
    assert p.apply("학생14", 3) == "막힘: 필수 포함 역할을 맡을 학생의 자리가 모자람"  # 11 막힘(필수 포함 역할 자리)
    assert p.count("tf_applications") == apps_before                                   # 뒤의 투표는 건너뜀
    assert first(p.apply("학생10", 4)) == "승인"                     # 12
    assert first(p.apply("학생13", 1)) == "대기"                     # 13 학생1만 찬성: 대기
    assert first(p.vote("학생1", "학생13")) == "대기"


def test_new_member_votes_on_earlier_application(conn):
    """어려움 6~7단계 뒤: 학생5가 팀원이 되었으므로 학생6의 지원에는 학생5의 투표도 있어야 한다."""
    p = Play(conn, HARD, 4)
    p.apply("학생2", 2); p.apply("학생8", 2); p.vote("학생2", "학생8")
    p.apply("학생5", 2); p.apply("학생6", 2)
    p.vote("학생2", "학생5"); p.vote("학생8", "학생5")
    assert p.vote("학생2", "학생6") == "대기: 팀원 3명 가운데 1명 찬성"
    assert p.vote("학생8", "학생6") == "대기: 팀원 3명 가운데 2명 찬성"
    assert first(p.vote("학생5", "학생6", yes=False)) == "거절"


def test_full_team_is_blocked(conn):
    p = Play(conn, HARD, 4)
    p.apply("학생1", 1)
    for name, voters in (("학생4", ["학생1"]), ("학생7", ["학생1", "학생4"]), ("학생13", ["학생1", "학생4", "학생7"])):
        p.apply(name, 1)
        for v in voters:
            p.vote(v, name)
    assert p.apply("학생11", 1) == "막힘: 팀이 꽉 참"


def test_vote_cannot_change(conn):
    p = Play(conn, EASY, 3)
    p.apply("학생1", 1); p.apply("학생4", 1); p.vote("학생1", "학생4")
    p.apply("학생7", 1)
    p.vote("학생1", "학생7")
    assert p.vote("학생1", "학생7", yes=False) == "대기: 이미 찬성함(투표는 바꿀 수 없음)"
    assert p.count("tf_votes") == 2


def test_vote_after_result_shows_current_status(conn):
    """다른 팀원의 거부로 이미 거절된 지원에 늦게 누르면 그 지원의 지금 상태(거절)를 보인다(공고 2.7)."""
    p = Play(conn, EASY, 3)
    p.apply("학생1", 1); p.apply("학생4", 1); p.vote("학생1", "학생4")
    p.apply("학생7", 1)
    p.vote("학생4", "학생7", yes=False)
    assert p.vote("학생1", "학생7") == "거절: 이미 결과가 나온 지원임(팀원이 거부함)"


def test_only_team_members_vote(conn):
    p = Play(conn, EASY, 3)
    p.apply("학생1", 1); p.apply("학생2", 2); p.apply("학생4", 1)
    assert p.vote("학생2", "학생4") == "막힘: 내 팀에 들어온 지원이 아님"
    assert p.vote("학생5", "학생4") == "막힘: 내 팀에 들어온 지원이 아님"  # 팀이 없는 학생


def test_after_rejection_can_apply_elsewhere(conn):
    """[공고 2.4 「한 학생의 지원」] 결과가 나온 뒤에는 다른 팀에 다시 지원할 수 있음."""
    p = Play(conn, EASY, 3)
    p.apply("학생1", 1); p.apply("학생4", 1); p.vote("학생1", "학생4")
    p.apply("학생7", 1); p.vote("학생4", "학생7", yes=False)
    assert first(p.apply("학생7", 2)) == "승인"


def test_closed_blocks_apply_and_vote(conn):
    """[공고 2.5-1] 마감 뒤로는 지원과 투표를 할 수 없음. (마감 때 대기 지원을 거절하는 일은 작업 #10)"""
    p = Play(conn, EASY, 3)
    p.apply("학생1", 1)
    p.apply("학생4", 1)
    conn.execute("update tf_settings set value = 'true' where key = 'closed'")
    assert p.apply("학생5", 2) == "막힘: 모집이 마감됨"
    assert p.vote("학생1", "학생4") == "막힘: 모집이 마감됨"
    assert p.count("tf_votes") == 0


def test_admin_and_bad_team(conn):
    p = Play(conn, EASY, 3)
    admin = service.login(conn, "admin", "test-admin-pass")
    assert service.apply(conn, admin, 1) == "막힘: 관리자는 지원하지 않음"
    assert p.apply("학생1", 9) == "막힘: 없는 팀"
    assert p.apply("학생1", 0) == "막힘: 없는 팀"


@pytest.mark.parametrize("yes", [True, False])
def test_messages_start_with_four_words(conn, yes):
    p = Play(conn, EASY, 3)
    messages = [p.apply("학생1", 1), p.apply("학생4", 1), p.vote("학생1", "학생4", yes), p.apply("학생1", 2)]
    assert all(first(m) in ("승인", "대기", "거절", "막힘") for m in messages)



# 승인 직전 재검사(공고 2.4 「승인 직전」, 3장 어려운 해결, 작업 #14) ----------------------

def status_of(p, name):
    return p.conn.execute(
        """select a.status, a.reason from tf_applications a join tf_students s on s.id = a.student_id
           where s.name = %s order by a.id desc limit 1""", (name,)).fetchone()


def test_order_is_by_vote_completion_not_application(conn):
    """학생5가 먼저, 학생6이 나중에 지원했지만 학생6의 투표가 먼저 끝나면 학생6이 승인되고 학생5가 거절된다."""
    p = Play(conn, HARD, 4)
    p.apply("학생2", 2); p.apply("학생8", 2); p.vote("학생2", "학생8")
    p.apply("학생5", 2)                      # 먼저 지원
    p.apply("학생6", 2)                      # 나중에 지원(같은 주 역할 웹 프로그래머)
    p.vote("학생2", "학생6")
    assert first(p.vote("학생8", "학생6")) == "승인"
    assert status_of(p, "학생5")["status"] == "대기"   # 미리 거절하지 않는다
    p.vote("학생2", "학생5")
    p.vote("학생8", "학생5")
    assert p.vote("학생6", "학생5") == "거절: 승인 직전 검사에서 같은 주 역할의 팀원이 있음"
    assert dict(status_of(p, "학생5")) == {"status": "거절", "reason": "승인 직전 검사: 같은 주 역할의 팀원이 있음"}


def test_recheck_capacity(conn):
    """팀1이 3명일 때 둘이 대기 → 먼저 끝난 쪽이 승인되어 4명이 되면 나머지는 정원으로 거절."""
    p = Play(conn, HARD, 4)
    p.apply("학생1", 1); p.apply("학생4", 1); p.vote("학생1", "학생4")
    p.apply("학생7", 1); p.vote("학생1", "학생7"); p.vote("학생4", "학생7")
    p.apply("학생13", 1)                     # 보고서 작성자
    p.apply("학생11", 1)                     # 테스터
    for v in ("학생1", "학생4", "학생7"):
        p.vote(v, "학생11")
    assert status_of(p, "학생13")["status"] == "대기"
    p.vote("학생1", "학생13"); p.vote("학생4", "학생13"); p.vote("학생7", "학생13")
    assert p.vote("학생11", "학생13") == "거절: 승인 직전 검사에서 팀이 꽉 참"


def test_recheck_required_role_seats(conn):
    """팀3(테스터)에 발표자와 보고서 작성자가 대기 → 발표자가 먼저 승인되면 남는 자리가 모자라 보고서 작성자는 거절."""
    p = Play(conn, HARD, 4)
    p.apply("학생11", 3)                     # 테스터
    p.apply("학생16", 3)                     # 발표자: 지원 때 남는 자리 2, 못 채운 역할 2 → 접수
    p.apply("학생13", 3)                     # 보고서 작성자: 지원 때 남는 자리 2, 못 채운 역할 2 → 접수
    assert first(p.vote("학생11", "학생16")) == "승인"
    p.vote("학생11", "학생13")
    assert p.vote("학생16", "학생13") == "거절: 승인 직전 검사에서 필수 포함 역할을 맡을 학생의 자리가 모자람"


def test_recheck_passes_when_rules_still_kept(conn):
    """재검사를 통과하면 그대로 승인된다(쉬움 2단계와 같은 흐름)."""
    p = Play(conn, EASY, 3)
    p.apply("학생1", 1); p.apply("학생4", 1); p.apply("학생7", 2)
    assert p.vote("학생1", "학생4") == "승인: 학생4이(가) 팀1에 들어감"
