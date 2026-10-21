# -*- coding: utf-8 -*-
# 작성일시: 2026-10-21 01:03 (KST)
"""지원과 투표의 규칙 판정(공고 2.4). DB를 모르는 순수 함수다.

막힘 = 지원을 아예 접수하지 않음(DB에 기록하지 않음).
거절 = 접수되어 대기하던 지원이 팀원의 거부, 승인 직전 검사, 모집 마감으로 떨어진 것.

아직 넣지 않은 분기(공고가 「3장의 어려운 해결」로 적은 것, 교수님 작업 순서 #14에서 더함):
- 막힘 이유 「필수 포함 역할을 맡을 학생의 자리가 모자람」
- 「승인 직전」 규칙 재검사
"""
from teamform.board import MAX_MEMBERS, Application, Board, Member, Team


def check_join(team: Team, applicant: Member) -> str | None:
    """이 팀에 이 학생을 넣어도 되는지. 막는 이유를 돌려주고, 괜찮으면 None."""
    # [공고 2.4 「팀이 꽉 참」] 4명인 팀에는 지원할 수 없음
    if len(team.members) >= MAX_MEMBERS:
        return "팀이 꽉 참"
    # [공고 2.4 「같은 주 역할」, 2.3 「주 역할 중복」] 주 역할이 중복되는 팀원이 있는 팀에는 지원할 수 없음
    if any(m.main_role == applicant.main_role for m in team.members):
        return "같은 주 역할의 팀원이 있음"
    return None


def check_apply(board: Board, applicant: Member, team: Team) -> str | None:
    """지원 단추를 누른 순간의 검사(공고 2.4 「막힌 지원」). 막는 이유를 돌려주고, 접수해도 되면 None.

    이유가 여럿 겹치면 학생 자신의 상태를 먼저 본다(PRD D-1).
    """
    # [공고 2.4 「막힌 지원」, 2.5-1] 모집이 마감되면 지원할 수 없음
    if board.closed:
        return "모집이 마감됨"
    # [공고 2.4 「이미 팀이 있음」] 다른 팀에 다시 지원할 수 없음
    if board.team_of(applicant.id) is not None:
        return "이미 팀이 있음"
    # [공고 2.4 「한 학생의 지원」] 지원한 팀의 결과가 나오기 전에는 다른 팀에 지원할 수 없음
    if board.pending_of(applicant.id) is not None:
        return "결과를 기다리는 지원이 있음"
    return check_join(team, applicant)


def vote_outcome(team: Team, application: Application) -> str:
    """지금까지의 투표로 지원의 상태를 판정한다. "거절", "승인", "대기" 가운데 하나."""
    # [공고 2.4 「팀원이 있는 팀에 지원」] 투표할 사람은 투표하는 때의 팀원이다.
    # 지원한 뒤에 다른 지원자가 먼저 승인되어 팀원이 되면, 그 사람의 찬성도 있어야 한다
    voters = [m.id for m in team.members]
    # [공고 2.4 「한 명이라도 거부」] 다른 팀원의 투표를 기다리지 않고 바로 거절
    if any(application.votes.get(v) == "거부" for v in voters):
        return "거절"
    # [공고 2.4 「모든 팀원이 찬성」] 승인되어 그 팀의 팀원이 됨
    if voters and all(application.votes.get(v) == "찬성" for v in voters):
        return "승인"
    # [공고 2.4 「아직 투표하지 않은 팀원이 있음」] 대기
    return "대기"
