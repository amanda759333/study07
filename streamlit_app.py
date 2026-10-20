# -*- coding: utf-8 -*-
# 작성일시: 2026-10-20 20:23 (KST)
"""팀 편성 웹 앱.

화면 요소의 key는 공고 2.7절 표(CLAUDE.md의 key 표)와 한 글자도 다르면 안 된다.
구현 순서는 docs/구현 계획.md 4절을 따른다.
"""
import streamlit as st

from teamform import db, service
from teamform.board import MAX_MEMBERS, Board, Team, load_board
from teamform.config import get_secret, secret_status
from teamform.roster import RosterError

st.set_page_config(page_title="팀 편성", page_icon="👥")


@st.cache_resource(show_spinner=False)
def prepare_admin() -> str:
    """앱이 뜰 때 한 번 관리자 계정을 만들거나 비밀번호를 갱신한다(공고 2.1)."""
    with db.connection() as conn:
        return service.ensure_admin(conn, get_secret("ADMIN_PASSWORD"))


RESULT_WORDS = ("승인", "대기", "거절", "막힘")


def set_result(message: str) -> None:
    """단추를 누른 결과 안내를 남긴다. 누른 사람의 세션에만 남으므로 그 사람 화면에만 보인다(공고 2.7).

    채점 프로그램은 첫 단어만 보므로 "승인", "대기", "거절", "막힘" 가운데 하나로 시작하지 않으면 오류를 낸다.
    """
    if not message.startswith(RESULT_WORDS):
        raise ValueError(f"결과 안내는 {', '.join(RESULT_WORDS)} 가운데 하나로 시작해야 함: {message[:20]}")
    st.session_state["result"] = message


def show_result() -> None:
    """[공고 2.7] 단추를 누른 결과 안내는 key가 result인 st.container 안에 보인다. 한 화면에 하나만 둔다."""
    with st.container(key="result"):
        message = st.session_state.get("result")
        if message:
            st.info(message)


def logout() -> None:
    for name in ("user_id", "result"):
        st.session_state.pop(name, None)


def roles_text(user: service.User) -> str:
    if user.is_admin:
        return "관리자"
    subs = ", ".join(user.sub_roles) if user.sub_roles else "없음"
    return f"주 역할 {user.main_role} · 보조 역할 {subs}"


def login_screen() -> None:
    st.title("팀 편성")
    with st.form("login_form", clear_on_submit=True):
        student_no = st.text_input("학번", key="login_student_no")
        password = st.text_input("비밀번호", type="password", key="login_password")
        submitted = st.form_submit_button("로그인", key="login_submit")
    if submitted:
        try:
            with db.connection() as conn:
                user = service.login(conn, student_no, password)
        except Exception as exc:
            set_result(f"막힘: {db.safe_error(exc)}")
        else:
            if user is None:
                set_result("막힘: 학번 또는 비밀번호가 틀림")
            else:
                st.session_state["user_id"] = user.id
                set_result(f"승인: {user.name}(으)로 로그인함")
                st.rerun()
    show_result()


def header(user: service.User) -> None:
    with st.container(key="whoami"):
        left, right = st.columns([4, 1])
        left.markdown(f"**{user.name}** ({user.student_no})  \n{roles_text(user)}")
        right.button("로그아웃", key="logout", on_click=logout)
    show_result()


def apply_block_reason(board: Board, user: service.User) -> str | None:
    """[공고 2.8] 이미 팀에 속했거나, 결과를 기다리는 지원이 있거나, 모집이 마감되었으면 지원 단추를 비활성화한다.

    그 밖에 막히는 지원(팀이 꽉 참, 같은 주 역할 등)은 단추를 누른 뒤 "막힘" 안내로 막는다(공고 2.7).
    """
    if board.closed:
        return "모집이 마감됨"
    if board.team_of(user.id):
        return "이미 팀이 있음"
    if board.pending_of(user.id):
        return "결과를 기다리는 지원이 있음"
    return None


def on_apply(user: service.User, team_no: int) -> None:
    set_result("막힘: 지원 기능은 다음 작업(#9)에서 만듦")


def team_card(team: Team, me: service.User | None = None, block: str | None = None) -> None:
    """[공고 2.7] 팀 하나의 표시. key는 team_1, team_2, … 이고 팀원의 이름이 보인다.

    me가 있으면 학생 화면이다: 지원 단추(apply_1, …)를 둔다.
    """
    with st.container(key=f"team_{team.no}", border=True):
        mine = me is not None and team.has_member(me.id)
        st.markdown(f"**{team.name}** ({len(team.members)}/{MAX_MEMBERS})" + (" · **내 팀**" if mine else ""))
        if team.members:
            st.markdown("\n".join(f"- {m.name} ({m.student_no}) — {m.roles_text()}" for m in team.members))
        else:
            st.caption("아직 팀원이 없음")
        if me is not None:
            st.button(
                f"{team.name}에 지원",
                key=f"apply_{team.no}",
                disabled=block is not None,
                help=block,
                on_click=on_apply,
                args=(me, team.no),
            )


def student_screen(user: service.User) -> None:
    with db.connection() as conn:
        board = load_board(conn)

    mine = board.team_of(user.id)
    # [공고 2.8] 로그인한 학생의 팀을 구별되게 표시하고, 팀이 없으면 "아직 팀이 없음"
    st.markdown(f"내 팀: **{mine.name}**" if mine else "아직 팀이 없음")
    waiting = board.pending_of(user.id)
    if waiting:
        team = board.team_by_id(waiting.team_id)
        yes = sum(1 for v in waiting.votes.values() if v == "찬성")
        st.caption(f"결과를 기다리는 지원: {team.name} (팀원 {len(team.members)}명 가운데 {yes}명 찬성)")
    if board.closed:
        st.caption("모집이 마감되었습니다.")

    st.subheader("팀 목록")
    block = apply_block_reason(board, user)
    for team in board.teams:
        team_card(team, me=user, block=block)


def on_admin_start(user: service.User) -> None:
    """명단으로 처음 상태 만들기 단추. 화면을 다시 그리기 전에 실행되어 result에 바로 보인다."""
    uploaded = st.session_state.get("admin_roster_file")
    if uploaded is None:
        set_result("막힘: 명단 CSV 파일을 올리지 않음")
        return
    try:
        with db.connection() as conn:
            message = service.reset_roster(conn, user, uploaded.getvalue(), int(st.session_state["admin_team_count"]))
    except RosterError as exc:
        more = f" 외 {len(exc.errors) - 1}건" if len(exc.errors) > 1 else ""
        set_result(f"막힘: {exc.errors[0]}{more}")
    except PermissionError:
        set_result("막힘: 관리자만 쓸 수 있음")
    except ValueError as exc:
        set_result(f"막힘: {exc}")
    except Exception as exc:
        set_result(f"막힘: {db.safe_error(exc)}")
    else:
        set_result(message)


def admin_screen(user: service.User) -> None:
    service.require_admin(user)  # 학생 계정이면 여기서 멈춘다(공고 6.3-11)
    st.subheader("명단 올리기")
    st.caption("올리면 지원·투표·팀원·마감 표시를 모두 지우고, 명단의 학생과 빈 팀을 새로 만듭니다. 학생 비밀번호는 모두 1234입니다.")
    st.file_uploader("명단 CSV (student_no, name, main_role, sub_roles)", type=["csv"], key="admin_roster_file")
    st.number_input("팀 수", min_value=1, max_value=20, value=3, step=1, key="admin_team_count")
    st.button("명단으로 처음 상태 만들기", key="admin_start", type="primary", on_click=on_admin_start, args=(user,))

    with db.connection() as conn:
        students = conn.execute("select count(*) as n from tf_students where not is_admin").fetchone()["n"]
        board = load_board(conn)
    st.caption(f"지금 상태: 학생 {students}명, 팀 {len(board.teams)}개, {'마감됨' if board.closed else '모집 중'}")

    st.subheader("팀 현황")
    for team in board.teams:
        team_card(team)


def main() -> None:
    status = secret_status()
    if status["DATABASE_URL"] == "없음" or status["ADMIN_PASSWORD"] == "없음":
        st.error("앱 설정이 빠졌습니다: " + ", ".join(f"{k} {v}" for k, v in status.items()))
        st.stop()
    try:
        prepare_admin()
    except Exception as exc:
        st.error(f"관리자 계정을 준비하지 못함: {db.safe_error(exc)}")
        st.stop()

    user_id = st.session_state.get("user_id")
    if user_id is None:
        login_screen()
        return

    with db.connection() as conn:
        user = service.load_user(conn, user_id)
    if user is None:  # 명단을 다시 올려 계정이 사라진 경우
        logout()
        set_result("막힘: 계정을 찾을 수 없어 로그아웃함")
        st.rerun()

    st.title("팀 편성")
    header(user)
    if user.is_admin:
        admin_screen(user)
    else:
        student_screen(user)


main()
