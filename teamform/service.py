# -*- coding: utf-8 -*-
# 작성일시: 2026-10-20 20:27 (KST)
"""로그인, 관리자 계정, 명단 올리기.

함수는 연결(conn)을 받아 쓰고 커밋하지 않는다. 커밋은 부르는 쪽(db.connection())이 한다.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import bcrypt

from teamform import ai, rules, solver
from teamform.board import MAX_MEMBERS, Member, load_board
from teamform.roster import ADMIN_NO, parse_roster

ADMIN_NAME = "관리자"
STUDENT_PASSWORD = "1234"  # [공고 2.2] 학생의 비밀번호는 모두 1234

# 없는 학번으로 로그인할 때도 bcrypt 비교를 한 번 해서, 응답 시간으로 학번이 있는지 알 수 없게 한다
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt()).decode()


@dataclass(frozen=True)
class User:
    id: int
    student_no: str
    name: str
    main_role: str | None
    sub_roles: tuple[str, ...]
    is_admin: bool


def hash_password(password: str) -> str:
    """[공고 3장 끝, 6.3-10] 비밀번호를 bcrypt 해시로 바꾼다. 평문은 저장하지 않는다."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """입력한 비밀번호를 같은 방법으로 바꿔 저장된 해시와 비교한다."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:  # 해시 형식이 깨진 경우
        return False


def ensure_admin(conn, admin_password: str | None) -> str:
    """[공고 2.1] 학번 admin 계정을 ADMIN_PASSWORD로 만들거나 비밀번호를 갱신한다.

    돌려주는 값: "만듦", "갱신함", "그대로"
    """
    if not admin_password:
        raise ValueError("ADMIN_PASSWORD 없음")
    created = conn.execute(
        """insert into tf_students (student_no, name, main_role, password_hash, is_admin)
           values (%s, %s, null, %s, true)
           on conflict (student_no) do nothing
           returning id""",
        (ADMIN_NO, ADMIN_NAME, hash_password(admin_password)),
    ).fetchone()
    if created:
        return "만듦"
    row = conn.execute(
        "select password_hash, is_admin from tf_students where student_no = %s for update",
        (ADMIN_NO,),
    ).fetchone()
    if row["is_admin"] and verify_password(admin_password, row["password_hash"]):
        return "그대로"
    conn.execute(
        "update tf_students set password_hash = %s, is_admin = true where student_no = %s",
        (hash_password(admin_password), ADMIN_NO),
    )
    return "갱신함"


def _load(conn, where: str, value) -> tuple[User, str] | None:
    row = conn.execute(
        f"""select id, student_no, name, main_role, is_admin, password_hash
            from tf_students where {where} = %s""",
        (value,),
    ).fetchone()
    if row is None:
        return None
    subs = conn.execute(
        "select role from tf_student_sub_roles where student_id = %s order by role",
        (row["id"],),
    ).fetchall()
    user = User(
        id=row["id"],
        student_no=row["student_no"],
        name=row["name"],
        main_role=row["main_role"],
        sub_roles=tuple(s["role"] for s in subs),
        is_admin=row["is_admin"],
    )
    return user, row["password_hash"]


def login(conn, student_no: str, password: str) -> User | None:
    """[공고 2.1, 6.3-12] 학번과 비밀번호가 둘 다 맞아야 로그인된다. 틀리면 None."""
    found = _load(conn, "student_no", (student_no or "").strip())
    if found is None:
        verify_password(password or "", _DUMMY_HASH)
        return None
    user, password_hash = found
    if not verify_password(password or "", password_hash):
        return None
    return user


def load_user(conn, user_id: int) -> User | None:
    """세션에 들고 있는 id로 지금의 사용자 정보를 DB에서 다시 읽는다.

    명단을 다시 올려 계정이 사라졌으면 None이다. 관리자 여부도 매번 DB 기준으로 본다.
    """
    found = _load(conn, "id", user_id)
    return found[0] if found else None


def require_admin(user: User | None) -> None:
    """[공고 6.3-11] 관리자 기능의 맨 앞에서 부른다. 학생 계정이면 막는다."""
    if user is None or not user.is_admin:
        raise PermissionError("관리자만 쓸 수 있음")


def is_closed(conn) -> bool:
    """[공고 2.5-1] 모집이 마감되었는지."""
    row = conn.execute("select value from tf_settings where key = 'closed'").fetchone()
    return row is not None and row["value"] == "true"


def reset_roster(conn, user: User | None, csv_bytes: bytes, team_count: int) -> str:
    """[공고 2.6] 명단 CSV와 팀 수로 앱 상태를 처음으로 되돌린다.

    지원·투표·팀원·마감 표시를 모두 지우고, 명단의 학생과 팀 수만큼의 빈 팀(팀1, 팀2, …)을 만든다.
    관리자 계정은 남긴다(공고 2.1). CSV가 틀리면 아무것도 지우지 않고 RosterError를 낸다.
    """
    require_admin(user)
    if team_count < 1:
        raise ValueError("팀 수는 1 이상이어야 함")
    rows = parse_roster(csv_bytes)

    # [공고 2.2] 비밀번호 1234를 학생마다 다른 salt로 해시한다. bcrypt는 느리므로 여러 스레드로 나눈다
    with ThreadPoolExecutor(max_workers=8) as pool:
        hashes = list(pool.map(lambda _: hash_password(STUDENT_PASSWORD), rows))

    # 지원·투표·마감과 동시에 일어나지 않게 마감 표시 행을 잠근다
    conn.execute("select value from tf_settings where key = 'closed' for update")
    conn.execute("delete from tf_votes")
    conn.execute("delete from tf_applications")
    conn.execute("delete from tf_members")
    conn.execute("delete from tf_teams")
    conn.execute("delete from tf_students where not is_admin")  # 보조 역할은 함께 지워짐(cascade)
    conn.execute(
        """insert into tf_settings (key, value) values ('closed', 'false')
           on conflict (key) do update set value = excluded.value"""
    )

    with conn.cursor() as cur:
        cur.executemany(
            "insert into tf_students (student_no, name, main_role, password_hash) values (%s, %s, %s, %s)",
            [(r.student_no, r.name, r.main_role, h) for r, h in zip(rows, hashes)],
        )
        ids = {
            r["student_no"]: r["id"]
            for r in conn.execute("select id, student_no from tf_students where not is_admin")
        }
        cur.executemany(
            "insert into tf_student_sub_roles (student_id, role) values (%s, %s)",
            [(ids[r.student_no], role) for r in rows for role in r.sub_roles],
        )
        # 팀 번호(team_1의 1)는 id 순서로 매기므로 팀1부터 차례로 넣는다
        cur.executemany("insert into tf_teams (name) values (%s)", [(f"팀{n}",) for n in range(1, team_count + 1)])

    return f"승인: 명단 {len(rows)}명, 팀 {team_count}개로 처음 상태를 만듦"


# 지원과 투표 -----------------------------------------------------------------
# 결과 안내는 "승인", "대기", "거절", "막힘" 가운데 하나로 시작하고 이유를 붙인다(공고 2.4, 2.7).
# 같은 팀에 대한 지원·투표가 동시에 들어와도 차례로 처리되도록 마감 표시 → 지원자 → 팀 순서로 행을 잠근다.


def _as_member(user: User) -> Member:
    return Member(user.id, user.student_no, user.name, user.main_role, user.sub_roles)


def _lock(conn, applicant_id: int, team_id: int) -> None:
    conn.execute("select value from tf_settings where key = 'closed' for share")  # 마감(close)과 엇갈리지 않게
    conn.execute("select id from tf_students where id = %s for update", (applicant_id,))
    conn.execute("select id from tf_teams where id = %s for update", (team_id,))


def _add_member(conn, team_id: int, student_id: int) -> bool:
    """빈 자리 가운데 가장 앞 번호에 넣는다. 자리가 없으면 False(DB의 slot_no 1~4 제약과 같은 기준)."""
    used = {r["slot_no"] for r in conn.execute("select slot_no from tf_members where team_id = %s", (team_id,))}
    free = [n for n in range(1, MAX_MEMBERS + 1) if n not in used]
    if not free:
        return False
    conn.execute("insert into tf_members (team_id, slot_no, student_id) values (%s, %s, %s)", (team_id, free[0], student_id))
    return True


def apply(conn, user: User, team_no: int) -> str:
    """팀에 지원한다(공고 2.4). 결과 안내를 돌려준다."""
    if user.is_admin:
        return "막힘: 관리자는 지원하지 않음"
    team_row = conn.execute(
        "select id from tf_teams order by id offset %s limit 1", (max(team_no, 1) - 1,)
    ).fetchone()
    if team_no < 1 or team_row is None:
        return "막힘: 없는 팀"
    _lock(conn, user.id, team_row["id"])
    board = load_board(conn)  # 잠근 뒤의 상태로 판정한다
    team = board.team_by_id(team_row["id"])
    me = _as_member(user)

    # [공고 2.4 「막힌 지원」] 단추를 누른 순간 규칙을 검사해 지원을 접수하지 않는다. DB에 기록하지 않는다
    reason = rules.check_apply(board, me, team)
    if reason:
        return f"막힘: {reason}"

    # [공고 2.4 「빈 팀에 지원」] 투표할 팀원이 없으므로 바로 승인
    if not team.members:
        conn.execute(
            "insert into tf_applications (team_id, student_id, status, reason) values (%s, %s, '승인', '빈 팀')",
            (team.id, me.id),
        )
        _add_member(conn, team.id, me.id)
        return f"승인: {team.name}에 들어감"

    # [공고 2.4 「팀원이 있는 팀에 지원」] 대기. 그 팀의 팀원 모두가 투표한다
    conn.execute("insert into tf_applications (team_id, student_id) values (%s, %s)", (team.id, me.id))
    return f"대기: {team.name}의 팀원 {len(team.members)}명이 투표해야 함"


def vote(conn, voter: User, applicant_no: str, yes: bool) -> str:
    """내 팀에 들어온 지원에 찬성 또는 거부를 누른다. 결과 안내는 그 지원의 지금 상태로 시작한다(공고 2.7)."""
    if voter.is_admin:
        return "막힘: 관리자는 투표하지 않음"
    applicant = conn.execute("select id, name from tf_students where student_no = %s", (applicant_no,)).fetchone()
    my_team = conn.execute("select team_id from tf_members where student_id = %s", (voter.id,)).fetchone()
    if applicant is None or my_team is None:
        return "막힘: 내 팀에 들어온 지원이 아님"
    _lock(conn, applicant["id"], my_team["team_id"])
    board = load_board(conn)
    team = board.team_of(voter.id)
    # [공고 2.4 「팀원이 있는 팀에 지원」] 투표하는 사람은 투표하는 때의 팀원이다
    if team is None or team.id != my_team["team_id"]:
        return "막힘: 내 팀에 들어온 지원이 아님"

    latest = conn.execute(
        """select id, status, reason from tf_applications
           where student_id = %s and team_id = %s order by created_at desc, id desc limit 1""",
        (applicant["id"], team.id),
    ).fetchone()
    if latest is None:
        return "막힘: 내 팀에 들어온 지원이 아님"
    if latest["status"] != "대기":
        # 다른 팀원의 거부 등으로 이미 결과가 나온 지원. 그 지원의 지금 상태를 보인다(공고 2.7)
        return f"{latest['status']}: 이미 결과가 나온 지원임({latest['reason'] or '이유 없음'})"
    # [공고 2.5-1] 마감 뒤로는 투표할 수 없음
    if board.closed:
        return "막힘: 모집이 마감됨"

    application = next(a for a in team.pending if a.id == latest["id"])
    # [공고 2.4 「투표 바꾸기」] 한 번 투표하면 바꿀 수 없음
    if voter.id in application.votes:
        return f"대기: 이미 {application.votes[voter.id]}함(투표는 바꿀 수 없음)"

    choice = "찬성" if yes else "거부"
    conn.execute("insert into tf_votes (application_id, voter_id, vote) values (%s, %s, %s)", (application.id, voter.id, choice))
    application.votes[voter.id] = choice

    outcome = rules.vote_outcome(team, application)
    if outcome == "거절":
        # [공고 2.4 「한 명이라도 거부」] 다른 팀원의 투표를 기다리지 않고 바로 거절
        conn.execute("update tf_applications set status = '거절', reason = '팀원이 거부함' where id = %s", (application.id,))
        return f"거절: 팀원이 거부함({voter.name})"
    if outcome == "승인":
        # [공고 2.4 「모든 팀원이 찬성」] 승인되어 그 팀의 팀원이 됨
        # (승인 직전 규칙 재검사는 공고 3장의 어려운 해결로, 작업 #14에서 이 자리에 더한다)
        if not _add_member(conn, team.id, application.applicant.id):
            # 자리가 없으면 DB 제약(slot_no 1~4)이 다섯 번째 팀원을 막는다
            conn.execute("update tf_applications set status = '거절', reason = '팀이 꽉 참' where id = %s", (application.id,))
            return "거절: 팀이 꽉 참"
        conn.execute("update tf_applications set status = '승인', reason = '모든 팀원 찬성' where id = %s", (application.id,))
        return f"승인: {application.applicant.name}이(가) {team.name}에 들어감"
    # [공고 2.4 「아직 투표하지 않은 팀원이 있음」] 대기
    yes_count = sum(1 for m in team.members if application.votes.get(m.id) == "찬성")
    return f"대기: 팀원 {len(team.members)}명 가운데 {yes_count}명 찬성"


# 모집 마감 -------------------------------------------------------------------


def close(conn, user: User | None) -> str:
    """[공고 2.5-1, 2.5-2] 모집을 마감한다. 결과 안내를 돌려준다.

    마감 뒤로는 지원과 투표를 할 수 없다. 대기 중인 지원은 거절되고,
    그다음 1명뿐인 팀의 학생은 팀에서 빠져 "팀이 없는 학생"이 된다.
    """
    require_admin(user)
    # 지원·투표(for share)가 끝나기를 기다렸다가 마감한다
    row = conn.execute("select value from tf_settings where key = 'closed' for update").fetchone()
    if row is not None and row["value"] == "true":
        return "막힘: 이미 마감됨"
    conn.execute(
        """insert into tf_settings (key, value) values ('closed', 'true')
           on conflict (key) do update set value = excluded.value"""
    )
    # [공고 2.5-2, 2.4 「막힘과 거절의 차이」] 마감 때 대기 중인 지원은 거절
    rejected = conn.execute(
        "update tf_applications set status = '거절', reason = '모집 마감' where status = '대기'"
    ).rowcount
    # [공고 2.5-2] 1명뿐인 팀의 학생은 팀에서 빠짐
    removed = conn.execute(
        """delete from tf_members m
           where (select count(*) from tf_members x where x.team_id = m.team_id) = 1"""
    ).rowcount
    return f"승인: 모집을 마감함(대기 지원 {rejected}건 거절, 1명뿐인 팀의 학생 {removed}명 빠짐)"


# AI 배정 ---------------------------------------------------------------------


def propose(user: User | None, board, *, on_wait=None, on_attempt=None) -> tuple[str, "ai.AssignResult | None"]:
    """[공고 2.5-3~8] AI에게 배정안을 받는다. (결과 안내, 결과)를 돌려준다.

    AI를 기다리는 동안 DB 연결을 붙잡지 않도록, 지금 상태(board)는 부르는 쪽이 먼저 읽어 넘긴다.
    3차까지 실패하면 앱이 스스로 배정하기(공고 2.5-6)는 작업 #14에서 더한다.
    """
    require_admin(user)
    # [공고 2.5-3] 마감 뒤 남은 학생을 배정한다
    if not board.closed:
        return "막힘: 모집이 마감되지 않음", None
    # [공고 2.5-8] 규칙을 모두 지키는 배정이 없으면 배정안을 만들지 않고 이유를 보인다. 이때는 AI를 부르지 않는다
    if solver.find_assignment(board) is None:
        return "막힘: 규칙을 지키는 배정이 없음: " + "; ".join(solver.why_impossible(board)), None
    if not board.unassigned:
        return "막힘: 팀이 없는 학생이 없음", None
    # [공고 2.5-4, 2.5-5] 검사 다섯 가지를 통과하지 못한 배정안은 실패로 보고 다음 모델로 넘어간다
    result = ai.ask_models(
        ai.build_prompt(board),
        lambda plan: rules.check_assignment(board, plan),
        on_wait=on_wait,
        on_attempt=on_attempt,
    )
    if result.plan is None:
        return "막힘: 3차 모델까지 실패함", result
    return f"승인: {result.model_no}차 모델의 배정안이 검사를 통과함", result


def confirm(conn, user: User | None, plan: list[tuple[str, int]] | None) -> str:
    """[공고 2.5-7] 관리자가 확정한 배정안을 DB에 저장한다.

    배정안을 받은 뒤 상태가 바뀌었을 수 있으므로 지금 상태로 검사 다섯 가지를 한 번 더 한다(PRD D-6).
    """
    require_admin(user)
    if not plan:
        return "막힘: 확정할 배정안이 없음"
    conn.execute("select value from tf_settings where key = 'closed' for update")  # 명단 올리기와 엇갈리지 않게
    conn.execute("select id from tf_teams order by id for update")
    board = load_board(conn)
    if not board.closed:
        return "막힘: 모집이 마감되지 않음"
    problems = rules.check_assignment(board, plan)
    if problems:
        return f"막힘: 배정안이 지금 상태와 맞지 않음({problems[0]})"
    by_no = {m.student_no: m for m in board.unassigned}
    for student_no, team_no in plan:
        if not _add_member(conn, board.team_by_no(team_no).id, by_no[student_no].id):
            # 검사를 통과했으므로 일어나지 않는다. 일어나면 예외로 트랜잭션 전체를 되돌린다(일부만 저장하지 않음)
            raise RuntimeError("배정안을 저장하다 자리가 모자람")
    return f"승인: 배정안을 확정함({len(plan)}명)"
