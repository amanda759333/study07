# -*- coding: utf-8 -*-
# 작성일시: 2026-10-20 20:27 (KST)
"""로그인과 관리자 계정.

함수는 연결(conn)을 받아 쓰고 커밋하지 않는다. 커밋은 부르는 쪽(db.connection())이 한다.
"""
from dataclasses import dataclass

import bcrypt

ADMIN_NO = "admin"
ADMIN_NAME = "관리자"

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
