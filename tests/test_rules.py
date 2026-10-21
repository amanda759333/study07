# -*- coding: utf-8 -*-
# 작성일시: 2026-10-21 01:03 (KST)
"""#9 지원과 투표 규칙 판정(공고 2.4). DB 없이 순수 함수만 시험한다."""
from teamform.board import Application, Board, Member, Team
from teamform.rules import check_apply, check_join, vote_outcome


def person(i, main, *subs):
    return Member(i, f"S{i}", f"학생{i}", main, subs)


PL, WP, FD, TT, RW, PT = "기획자", "웹 프로그래머", "프론트엔드 디자이너", "테스터", "보고서 작성자", "발표자"


def team(no, *members, pending=()):
    return Team(id=no, no=no, name=f"팀{no}", members=list(members), pending=list(pending))


# check_join ----------------------------------------------------------------

def test_full_team_blocks():
    t = team(1, person(1, PL), person(2, WP), person(3, FD), person(4, TT))
    assert check_join(t, person(5, RW)) == "팀이 꽉 참"


def test_same_main_role_blocks():
    t = team(1, person(1, PL, PT, TT), person(2, WP, TT))  # 부록 2 중간 3단계의 팀1
    assert check_join(t, person(3, PL, TT)) == "같은 주 역할의 팀원이 있음"


def test_sub_role_does_not_count_as_duplicate():
    """[공고 2.3] 보조 역할은 중복을 따지지 않는다. 팀원의 보조 역할 테스터와 지원자의 주 역할 테스터는 겹치지 않음."""
    t = team(1, person(1, PL, TT))
    assert check_join(t, person(2, TT)) is None


def test_empty_team_accepts_anyone():
    assert check_join(team(1), person(1, RW)) is None


# check_apply: 이유가 겹치면 학생 자신의 상태부터 -------------------------------

def test_closed_comes_first():
    t = team(1, person(1, PL))
    board = Board([t], closed=True)
    assert check_apply(board, person(2, PL), t) == "모집이 마감됨"


def test_already_in_team():
    t1, t2 = team(1, person(1, PL)), team(2)
    assert check_apply(Board([t1, t2], closed=False), person(1, PL), t2) == "이미 팀이 있음"


def test_waiting_application_blocks_other_team():
    """부록 2 중간 8단계: 팀4에 대기 중인 학생12가 팀3에도 지원하면 막힘."""
    s12 = person(12, PT, RW, FD)
    t3 = team(3, person(3, PL, RW))
    t4 = team(4, person(11, RW), pending=[Application(1, 4, s12)])
    assert check_apply(Board([t3, t4], closed=False), s12, t3) == "결과를 기다리는 지원이 있음"


def test_waiting_application_blocks_same_team_again():
    s = person(7, FD)
    t1 = team(1, person(1, PL), pending=[Application(1, 1, s)])
    assert check_apply(Board([t1], closed=False), s, t1) == "결과를 기다리는 지원이 있음"


def test_apply_passes_to_join_rules():
    t = team(1, person(1, PL))
    assert check_apply(Board([t], closed=False), person(2, PL), t) == "같은 주 역할의 팀원이 있음"
    assert check_apply(Board([t], closed=False), person(3, WP), t) is None


# vote_outcome --------------------------------------------------------------

def test_one_no_rejects_without_waiting():
    """부록 1 쉬움 4단계: 학생1 찬성, 학생4 거부 → 거절."""
    t = team(1, person(1, PL), person(4, WP))
    app = Application(1, 1, person(7, FD), votes={1: "찬성", 4: "거부"})
    assert vote_outcome(t, app) == "거절"
    assert vote_outcome(t, Application(2, 1, person(8, TT), votes={4: "거부"})) == "거절"


def test_all_yes_approves():
    t = team(1, person(1, PL), person(4, WP))
    assert vote_outcome(t, Application(1, 1, person(7, FD), votes={1: "찬성", 4: "찬성"})) == "승인"


def test_missing_vote_waits():
    """부록 3 어려움 13단계: 팀원 3명 가운데 학생1만 찬성 → 대기."""
    t = team(1, person(1, PL), person(4, WP), person(7, FD))
    assert vote_outcome(t, Application(1, 1, person(13, RW), votes={1: "찬성"})) == "대기"


def test_new_member_must_vote_too():
    """[공고 2.4] 내가 지원한 뒤 다른 지원자가 먼저 승인되어 팀원이 되면, 그 사람도 내 지원에 투표한다."""
    before = team(2, person(2, PL), person(8, FD))
    app = Application(1, 2, person(6, WP), votes={2: "찬성", 8: "찬성"})
    assert vote_outcome(before, app) == "승인"
    after = team(2, person(2, PL), person(8, FD), person(5, WP))  # 학생5가 먼저 승인됨
    assert vote_outcome(after, app) == "대기"


# 필수 포함 역할 자리(공고 3장 어려운 해결, 작업 #14) ----------------------------------

BLOCK = "필수 포함 역할을 맡을 학생의 자리가 모자람"


def test_seat_notice_example():
    """공고 예: 테스터와 발표자만 있는 2명 팀에 보고서 작성자가 지원 → 남는 자리 1 < 못 채운 역할 2 → 막힘."""
    assert check_join(team(1, person(1, TT), person(2, PT)), person(3, RW)) == BLOCK


def test_seat_hard_step_11():
    """부록 3 어려움 11단계: 팀3(학생11 테스터;발표자, 학생15 발표자;디자이너)에 학생14(보고서 작성자;테스터) → 막힘."""
    t3 = team(3, person(11, TT, PT), person(15, PT, FD))
    assert check_join(t3, person(14, RW, TT)) == BLOCK


def test_seat_applicant_who_can_do_both_counts_once():
    """기획자이면서 보조 역할이 웹 프로그래머인 지원자: 하나로만 세므로 못 채운 역할 1, 남는 자리 1 → 접수."""
    assert check_join(team(1, person(1, TT), person(2, PT)), person(3, PL, WP)) is None


def test_seat_boundary_equal_is_allowed():
    """부록 3 어려움 10단계: 팀3(테스터)에 발표자 → 남는 자리 2, 못 채운 역할 2 → 적지 않으므로 접수."""
    assert check_join(team(3, person(11, TT, PT)), person(15, PT, FD)) is None


def test_seat_sub_role_counts():
    """보조 역할로 기획자를 맡을 수 있는 테스터가 지원하면 못 채운 역할 1, 남는 자리 1 → 접수."""
    assert check_join(team(1, person(1, FD), person(2, PT)), person(3, TT, PL)) is None


def test_seat_last_slot_needs_both_filled():
    t = team(1, person(1, PL), person(2, FD), person(3, TT))  # 웹 프로그래머가 없는 3명 팀
    assert check_join(t, person(4, RW)) == BLOCK              # 마지막 자리에 웹 프로그래머를 못 하는 학생
    assert check_join(t, person(5, PT, WP)) is None            # 보조 역할로 웹 프로그래머를 하는 학생은 접수
