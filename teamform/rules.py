# -*- coding: utf-8 -*-
# 작성일시: 2026-10-21 01:03 (KST)
"""지원과 투표의 규칙 판정(공고 2.4). DB를 모르는 순수 함수다.

막힘 = 지원을 아예 접수하지 않음(DB에 기록하지 않음).
거절 = 접수되어 대기하던 지원이 팀원의 거부, 승인 직전 검사, 모집 마감으로 떨어진 것.

아직 넣지 않은 분기(공고가 「3장의 어려운 해결」로 적은 것, 교수님 작업 순서 #14에서 더함):
- 「승인 직전」 규칙 재검사
"""
from teamform.board import MAX_MEMBERS, Application, Board, Member, Team


def check_join(team: Team, applicant: Member) -> str | None:
    """이 팀에 이 학생을 넣어도 되는지. 정원 → 주 역할 중복 → 필수 포함 역할 자리 순으로 보고,
    막는 이유를 돌려준다. 괜찮으면 None."""
    # [공고 2.4 「팀이 꽉 참」] 4명인 팀에는 지원할 수 없음
    if len(team.members) >= MAX_MEMBERS:
        return "팀이 꽉 참"
    # [공고 2.4 「같은 주 역할」, 2.3 「주 역할 중복」] 주 역할이 중복되는 팀원이 있는 팀에는 지원할 수 없음
    if any(m.main_role == applicant.main_role for m in team.members):
        return "같은 주 역할의 팀원이 있음"
    # [공고 2.4 「막힌 지원」, 3장 「필수 포함 역할을 지킬 수 없는 팀」 어려운 해결, 「필수 포함 역할 자리 계산」]
    # 지원자가 들어간 뒤 남는 자리 수가, 그 팀에서 아직 채우지 못한 필수 포함 역할 수보다 적으면 막는다.
    # 지원자 자신도 필수 포함 역할을 채울 수 있으므로 지원자를 넣은 뒤로 센다
    after = [*team.members, applicant]
    left = MAX_MEMBERS - len(after)
    missing = 2 - required_filled(after)  # 한 학생이 둘 다 할 수 있어도 하나로만 센다
    if left < missing:
        return "필수 포함 역할을 맡을 학생의 자리가 모자람"
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


def check_plan_format(board: Board, plan: list[tuple[str, int]]) -> list[str]:
    """AI 배정안의 형식 검사: 팀이 없는 학생만, 있는 팀에 넣었는지. 어긴 것을 모두 돌려준다.

    공고 2.5-4의 검사 다섯 가지는 작업 #12에서 check_assignment로 더한다.
    """
    unassigned = {m.student_no for m in board.unassigned}
    problems = []
    for student_no, team_no in plan:
        if student_no not in unassigned:
            # [공고 2.5-3] 배정은 팀이 없는 학생만 팀에 넣으며, 이미 팀에 있는 학생은 옮기지 않음
            problems.append(f"{student_no}은 팀이 없는 학생이 아님")
        if board.team_by_no(team_no) is None:
            problems.append(f"팀{team_no}은 없는 팀")
    return problems


# 배정안 검사(공고 2.5-4) ---------------------------------------------------------

PLANNER, WEB = "기획자", "웹 프로그래머"  # [공고 2.3 「필수 포함 역할」]


def can_play(member: Member, role: str) -> bool:
    """[공고 2.3] 필수 포함 역할은 주 역할이나 보조 역할로 맡을 수 있다."""
    return member.main_role == role or role in member.sub_roles


def required_filled(members) -> int:
    """필수 포함 역할(기획자, 웹 프로그래머) 가운데 채운 수(0~2).

    [공고 3장 「필수 포함 역할 자리 계산」] 기획자와 웹 프로그래머는 서로 다른 학생이 맡아야 하므로,
    한 학생이 둘 다 할 수 있어도 하나로만 센다. 예: 기획자이면서 보조 역할이 웹 프로그래머인 학생 혼자면 1.
    """
    planners = [m for m in members if can_play(m, PLANNER)]
    webs = [m for m in members if can_play(m, WEB)]
    if any(p.id != w.id for p in planners for w in webs):
        return 2
    return 1 if planners or webs else 0


def _who(members) -> str:
    return ", ".join(m.name for m in members) or "없음"


def teams_after(board: Board, plan: list[tuple[str, int]]) -> dict[int, list[Member]]:
    """배정안대로 넣은 뒤의 팀 번호 → 팀원. 배정안에 같은 학생이 두 번 있으면 두 번 다 넣는다(검사 ②가 잡는다)."""
    by_no = {m.student_no: m for m in board.unassigned}
    after = {t.no: list(t.members) for t in board.teams}
    for student_no, team_no in plan:
        if student_no in by_no and team_no in after:
            after[team_no].append(by_no[student_no])
    return after


def check_assignment(board: Board, plan: list[tuple[str, int]]) -> list[str]:
    """배정안이 공고 2.5-4의 검사 다섯 가지를 지키는지. 어긴 항목과 이유를 모두 돌려주고, 통과하면 빈 목록."""
    problems = check_plan_format(board, plan)  # 이미 팀이 있는 학생을 옮기거나 없는 팀에 넣은 배정안
    names = {m.student_no: m.name for m in board.unassigned}
    placed: dict[str, list[int]] = {}
    for student_no, team_no in plan:
        placed.setdefault(student_no, []).append(team_no)

    # ① 팀이 없는 학생이 빠짐없이 배정됨
    for m in board.unassigned:
        if m.student_no not in placed:
            problems.append(f"① {m.name}({m.student_no})이 배정되지 않음")
    # ② 한 학생은 한 팀에만 배정됨
    for student_no, team_nos in placed.items():
        if len(team_nos) > 1:
            teams = ", ".join(f"팀{n}" for n in team_nos)
            problems.append(f"② {names.get(student_no, student_no)}({student_no})이 여러 번 배정됨({teams})")

    for team_no, members in teams_after(board, plan).items():
        # ③ 모든 팀이 2~4명 [공고 2.3 「인원」]
        if not 2 <= len(members) <= MAX_MEMBERS:
            problems.append(f"③ 팀{team_no}이 {len(members)}명임(2~4명이어야 함)")
        # ④ 팀 안에 주 역할 중복 없음 [공고 2.3 「주 역할 중복」]
        by_role: dict[str, list[Member]] = {}
        for m in members:
            by_role.setdefault(m.main_role, []).append(m)
        for role, same in by_role.items():
            if len(same) > 1:
                problems.append(f"④ 팀{team_no}에 주 역할이 {role}인 학생이 {len(same)}명({_who(same)})")
        # ⑤ 기획자와 웹 프로그래머가 서로 다른 사람으로 1명씩 [공고 2.3 「필수 포함 역할」]
        if required_filled(members) < 2:
            planners = [m for m in members if can_play(m, PLANNER)]
            webs = [m for m in members if can_play(m, WEB)]
            problems.append(
                f"⑤ 팀{team_no}에 기획자와 웹 프로그래머를 서로 다른 사람으로 둘 수 없음"
                f"(기획자 가능: {_who(planners)}, 웹 프로그래머 가능: {_who(webs)})"
            )
    return problems
