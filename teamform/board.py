# -*- coding: utf-8 -*-
# 작성일시: 2026-10-21 01:03 (KST)
"""지금의 팀 구성을 DB에서 한 번에 읽는다.

화면을 그릴 때와 지원·투표를 판정할 때 같은 모양의 데이터를 쓴다. 질의는 6번이고 연결은 db.connection()이 다시 쓴다.
"""
from dataclasses import dataclass, field

MAX_MEMBERS = 4  # [공고 2.3 「인원」, 2.4 「팀이 꽉 참」] 팀 정원


@dataclass(frozen=True)
class Member:
    """팀원, 지원자, 팀이 없는 학생 모두 이 모양이다."""

    id: int
    student_no: str
    name: str
    main_role: str
    sub_roles: tuple[str, ...]

    def roles_text(self) -> str:
        subs = ", ".join(self.sub_roles) if self.sub_roles else "없음"
        return f"주 역할 {self.main_role} · 보조 역할 {subs}"


@dataclass
class Application:
    """결과를 기다리는(대기) 지원. votes는 투표한 사람 id → '찬성'/'거부'."""

    id: int
    team_id: int
    applicant: Member
    votes: dict[int, str] = field(default_factory=dict)


@dataclass
class Team:
    id: int
    no: int  # team_1, apply_1 의 1. 명단을 올릴 때 만든 순서(id 순서)대로 1부터
    name: str
    members: list[Member] = field(default_factory=list)
    pending: list[Application] = field(default_factory=list)

    @property
    def is_full(self) -> bool:
        return len(self.members) >= MAX_MEMBERS

    def has_member(self, student_id: int) -> bool:
        return any(m.id == student_id for m in self.members)


@dataclass
class Board:
    teams: list[Team]
    closed: bool
    unassigned: list[Member] = field(default_factory=list)  # 팀이 없는 학생(관리자 제외), 학번 순

    def team_by_no(self, no: int) -> Team | None:
        return self.teams[no - 1] if 1 <= no <= len(self.teams) else None

    def team_by_id(self, team_id: int) -> Team | None:
        return next((t for t in self.teams if t.id == team_id), None)

    def team_of(self, student_id: int) -> Team | None:
        """그 학생이 팀원인 팀. 없으면 None."""
        return next((t for t in self.teams if t.has_member(student_id)), None)

    def pending_of(self, student_id: int) -> Application | None:
        """그 학생이 결과를 기다리는 지원. 없으면 None."""
        return next((a for t in self.teams for a in t.pending if a.applicant.id == student_id), None)


_STUDENT_COLUMNS = """s.id, s.student_no, s.name, s.main_role,
    array(select r.role from tf_student_sub_roles r where r.student_id = s.id order by r.role) as sub_roles"""


def _member(row) -> Member:
    return Member(row["id"], row["student_no"], row["name"], row["main_role"], tuple(row["sub_roles"]))


def load_board(conn) -> Board:
    teams = [
        Team(id=r["id"], no=r["no"], name=r["name"])
        for r in conn.execute("select id, name, row_number() over (order by id) as no from tf_teams order by id")
    ]
    by_id = {t.id: t for t in teams}

    for r in conn.execute(
        f"""select m.team_id, {_STUDENT_COLUMNS}
            from tf_members m join tf_students s on s.id = m.student_id
            order by m.team_id, m.slot_no"""
    ):
        by_id[r["team_id"]].members.append(_member(r))

    apps: dict[int, Application] = {}
    for r in conn.execute(
        f"""select a.id as app_id, a.team_id, {_STUDENT_COLUMNS}
            from tf_applications a join tf_students s on s.id = a.student_id
            where a.status = '대기'
            order by a.created_at, a.id"""
    ):
        app = Application(id=r["app_id"], team_id=r["team_id"], applicant=_member(r))
        apps[app.id] = app
        by_id[app.team_id].pending.append(app)

    for r in conn.execute(
        """select v.application_id, v.voter_id, v.vote
           from tf_votes v join tf_applications a on a.id = v.application_id
           where a.status = '대기'"""
    ):
        apps[r["application_id"]].votes[r["voter_id"]] = r["vote"]

    unassigned = [
        _member(r)
        for r in conn.execute(
            f"""select {_STUDENT_COLUMNS} from tf_students s
                where not s.is_admin and not exists (select 1 from tf_members m where m.student_id = s.id)
                order by s.student_no"""
        )
    ]

    closed = conn.execute("select value from tf_settings where key = 'closed'").fetchone()
    return Board(teams=teams, closed=closed is not None and closed["value"] == "true", unassigned=unassigned)
