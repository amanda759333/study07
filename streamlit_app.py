# -*- coding: utf-8 -*-
# 작성일시: 2026-10-20 20:23 (KST)
"""팀 편성 웹 앱.

화면 요소의 key는 공고 2.7절 표(CLAUDE.md의 key 표)와 한 글자도 다르면 안 된다.
구현 순서는 docs/구현 계획.md 4절을 따른다.
"""
import streamlit as st

from teamform import db, service
from teamform.ai import MODEL_TIMEOUT
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
    """팀에 지원하는 단추(apply_1, …). result에 그 지원의 결과를 보인다(공고 2.7)."""
    try:
        with db.connection() as conn:
            set_result(service.apply(conn, user, team_no))
    except Exception as exc:
        set_result(f"막힘: {db.safe_error(exc)}")


def on_vote(user: service.User, applicant_no: str, yes: bool) -> None:
    """찬성(vote_yes_학번)·거부(vote_no_학번) 단추. result에 그 지원의 지금 상태를 보인다(공고 2.7)."""
    try:
        with db.connection() as conn:
            set_result(service.vote(conn, user, applicant_no, yes))
    except Exception as exc:
        set_result(f"막힘: {db.safe_error(exc)}")


def pending_list(team: Team, me: service.User) -> None:
    """내 팀에 들어온 지원과 찬성·거부 단추."""
    if not team.pending:
        return
    st.markdown("**결과를 기다리는 지원**")
    for application in team.pending:
        a = application.applicant
        yes = sum(1 for m in team.members if application.votes.get(m.id) == "찬성")
        line = f"{a.name} ({a.student_no}) — {a.roles_text()} · 찬성 {yes}/{len(team.members)}"
        my_vote = application.votes.get(me.id)
        if my_vote:
            # [공고 2.8] 이미 투표한 지원은 단추를 숨기고 "내 투표: 찬성"처럼 보인다
            st.markdown(f"{line} · 내 투표: {my_vote}")
            continue
        left, yes_col, no_col = st.columns([4, 1, 1])
        left.markdown(line)
        yes_col.button("찬성", key=f"vote_yes_{a.student_no}", on_click=on_vote, args=(me, a.student_no, True))
        no_col.button("거부", key=f"vote_no_{a.student_no}", on_click=on_vote, args=(me, a.student_no, False))


def team_card(team: Team, me: service.User | None = None, block: str | None = None) -> None:
    """[공고 2.7] 팀 하나의 표시. key는 team_1, team_2, … 이고 팀원의 이름이 보인다.

    me가 있으면 학생 화면이다: 지원 단추(apply_1, …)를 두고, 내 팀이면 들어온 지원과 투표 단추를 둔다.
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
            if mine:
                pending_list(team, me)


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
        clear_assign()


def clear_assign() -> None:
    """상태가 바뀌었으므로 지난 AI 배정 안내와 배정안을 지운다."""
    for name in ("assign_log", "assign_note", "proposal"):
        st.session_state.pop(name, None)


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

    st.subheader("모집 마감")
    st.caption("누르면 지원·투표를 받지 않고, 대기 중인 지원은 거절되며, 1명뿐인 팀의 학생은 팀에서 빠집니다.")
    st.button("모집 마감", key="admin_close", disabled=board.closed, on_click=on_admin_close, args=(user,))

    # [공고 2.7] 팀이 없는 학생 표시. 마감 결과(1명 팀에서 빠진 학생)도 여기서 확인한다
    st.markdown("**팀이 없는 학생**")
    with st.container(key="unassigned", border=True):
        if board.unassigned:
            st.markdown("\n".join(f"- {m.name} ({m.student_no}) — {m.roles_text()}" for m in board.unassigned))
        else:
            st.markdown("팀이 없는 학생이 없음")

    assign_section(user, board)


def assign_section(user: service.User, board: Board) -> None:
    """AI 배정 단추(admin_assign)와 진행 안내(assign_status).

    AI를 기다리는 동안 화면을 붙잡고 있으므로 on_click이 아니라 이 자리에서 실행해 안내를 바로 고쳐 쓴다.
    """
    st.subheader("AI 배정")
    st.caption(f"1차 → 2차 → 3차 모델 순서로 부르고, 모델마다 {MODEL_TIMEOUT:.0f}초가 넘으면 다음 모델로 넘어갑니다.")
    clicked = st.button("AI 배정", key="admin_assign")
    with st.container(key="assign_status", border=True):
        if clicked:
            done_box, wait_box = st.container(), st.empty()

            def on_wait(no: int, model: str, elapsed: float) -> None:
                # [공고 3장 「AI 대기 중 화면」] 몇 차 모델의 응답을 기다리는 중인지 보인다
                wait_box.info(f"{no}차 모델({model})의 응답을 기다리는 중… {elapsed:.0f}초 / {MODEL_TIMEOUT:.0f}초")

            def on_attempt(attempt) -> None:
                done_box.markdown(f"- {attempt.text()}")

            try:
                message, result = service.propose(user, board, on_wait=on_wait, on_attempt=on_attempt)
            except Exception as exc:
                message, result = f"막힘: {db.safe_error(exc)}", None
            st.session_state["assign_log"] = [a.text() for a in result.attempts] if result else []
            st.session_state["assign_note"] = message
            st.session_state["proposal"] = result.plan if result and result.plan else None
            set_result(message)
            st.rerun()

        for line in st.session_state.get("assign_log", []):
            st.markdown(f"- {line}")
        note = st.session_state.get("assign_note")
        st.markdown(note if note else "아직 AI 배정을 하지 않음")


def on_admin_close(user: service.User) -> None:
    """모집 마감 단추(admin_close). 해냈으면 "승인", 못 했으면 "막힘"으로 시작한다(공고 2.7)."""
    try:
        with db.connection() as conn:
            set_result(service.close(conn, user))
        clear_assign()
    except PermissionError:
        set_result("막힘: 관리자만 쓸 수 있음")
    except Exception as exc:
        set_result(f"막힘: {db.safe_error(exc)}")


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
