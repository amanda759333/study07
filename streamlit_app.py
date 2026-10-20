# -*- coding: utf-8 -*-
# 작성일시: 2026-10-20 20:23 (KST)
"""팀 편성 웹 앱.

화면 요소의 key는 공고 2.7절 표(CLAUDE.md의 key 표)와 한 글자도 다르면 안 된다.
구현 순서는 docs/구현 계획.md 4절을 따른다.
"""
import streamlit as st

from teamform import db, service
from teamform.config import get_secret, secret_status

st.set_page_config(page_title="팀 편성", page_icon="👥")


@st.cache_resource(show_spinner=False)
def prepare_admin() -> str:
    """앱이 뜰 때 한 번 관리자 계정을 만들거나 비밀번호를 갱신한다(공고 2.1)."""
    with db.connection() as conn:
        return service.ensure_admin(conn, get_secret("ADMIN_PASSWORD"))


def set_result(message: str) -> None:
    """단추를 누른 결과 안내. "승인", "대기", "거절", "막힘" 가운데 하나로 시작한다(공고 2.7)."""
    st.session_state["result"] = message


def show_result() -> None:
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


def student_screen(user: service.User) -> None:
    st.subheader("팀 목록")
    st.caption("팀 목록과 지원은 다음 작업(#8, #9)에서 만든다.")


def admin_screen(user: service.User) -> None:
    service.require_admin(user)  # 학생 계정이면 여기서 멈춘다(공고 6.3-11)
    st.subheader("관리자")
    st.caption("명단 올리기는 다음 작업(#7)에서 만든다.")


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
