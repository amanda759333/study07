# -*- coding: utf-8 -*-
# 작성일시: 2026-10-21 01:03 (KST)
"""규칙을 지키는 배정 찾기(공고 2.5-8).

팀이 없는 학생을 한 명씩 팀에 넣어 보는 방식으로 모든 경우를 따진다. 공고 6.2-9에 따라 팀이 없는 학생은
8명을 넘지 않고 팀은 3~4개라, 막다른 길을 일찍 버리면 곧바로 끝난다.
AI를 부르기 전에 배정이 있는지 확인하고, 없으면 그 이유를 찾는다.
"""
from teamform.board import MAX_MEMBERS, Board, Member
from teamform.rules import PLANNER, WEB, can_play, required_filled


def find_assignment(board: Board) -> list[tuple[str, int]] | None:
    """공고 2.5-4의 검사 다섯 가지를 모두 지키는 배정안 하나. 없으면 None."""
    teams = {t.no: list(t.members) for t in board.teams}
    # 넣을 수 있는 팀이 적은 학생부터 정하면 막다른 길을 빨리 찾는다
    students = sorted(board.unassigned, key=lambda s: sum(_fits(teams[n], s) for n in teams))
    plan: list[tuple[str, int]] = []

    def hopeless(left: int) -> bool:
        need = sum(max(0, 2 - len(m)) for m in teams.values())  # 2명이 안 되는 팀을 채울 사람
        room = sum(MAX_MEMBERS - len(m) for m in teams.values())
        if need > left or room < left:
            return True
        # 남은 자리로 채우지 못한 필수 포함 역할을 채울 수 없는 팀
        return any(MAX_MEMBERS - len(m) < 2 - required_filled(m) for m in teams.values())

    def place(i: int) -> bool:
        if hopeless(len(students) - i):
            return False
        if i == len(students):
            return all(2 <= len(m) <= MAX_MEMBERS and required_filled(m) == 2 for m in teams.values())
        student = students[i]
        tried_empty = False
        for no, members in teams.items():
            if not _fits(members, student):
                continue
            if not members:  # 빈 팀끼리는 서로 같으므로 하나만 해 본다
                if tried_empty:
                    continue
                tried_empty = True
            members.append(student)
            plan.append((student.student_no, no))
            if place(i + 1):
                return True
            members.pop()
            plan.pop()
        return False

    return sorted(plan, key=lambda p: (p[1], p[0])) if place(0) else None


def _fits(members: list[Member], student: Member) -> bool:
    """정원과 주 역할 중복만 본 넣을 수 있는지."""
    return len(members) < MAX_MEMBERS and all(m.main_role != student.main_role for m in members)


def why_impossible(board: Board) -> list[str]:
    """배정이 없을 때 관리자에게 보일 이유. 짚이는 이유가 없으면 모든 경우를 따졌다는 안내 하나."""
    left = len(board.unassigned)
    reasons = []
    need = sum(max(0, 2 - len(t.members)) for t in board.teams)
    room = sum(MAX_MEMBERS - len(t.members) for t in board.teams)
    if need > left:
        reasons.append(f"모든 팀을 2명 이상으로 채우려면 {need}명이 필요한데 팀이 없는 학생은 {left}명임")
    if room < left:
        reasons.append(f"남은 자리는 {room}개인데 팀이 없는 학생은 {left}명임")

    for team in board.teams:
        slots = MAX_MEMBERS - len(team.members)
        joinable = [s for s in board.unassigned if _fits(team.members, s)]
        for role in (PLANNER, WEB):
            if not any(can_play(m, role) for m in team.members + joinable):
                reasons.append(f"{team.name}에 {role}를 맡을 학생이 없음")
        missing = 2 - required_filled(team.members)
        if slots < missing:
            reasons.append(f"{team.name}에 자리가 {slots}개 남았는데 채우지 못한 필수 포함 역할이 {missing}개임")

    for role in (PLANNER, WEB):
        lacking = [t for t in board.teams if not any(can_play(m, role) for m in t.members)]
        able = [s for s in board.unassigned if can_play(s, role)]
        if len(lacking) > len(able):
            reasons.append(f"{role}가 없는 팀은 {len(lacking)}개인데 {role}를 맡을 수 있는 팀이 없는 학생은 {len(able)}명임")

    return reasons or ["모든 경우를 따져도 검사 다섯 가지를 모두 지키는 배정이 없음"]
