# -*- coding: utf-8 -*-
# 작성일시: 2026-10-20 20:27 (KST)
"""로그인, 관리자 계정, 명단 올리기.

함수는 연결(conn)을 받아 쓰고 커밋하지 않는다. 커밋은 부르는 쪽(db.connection())이 한다.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import bcrypt

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
