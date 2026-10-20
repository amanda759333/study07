# -*- coding: utf-8 -*-
# 작성일시: 2026-10-20 20:27 (KST)
"""DB 연결.

연결은 앱이 뜰 때 연결 풀로 한 번만 만들고 화면을 그릴 때마다 다시 쓴다(공고 4.2).
질의마다 새로 연결하면 연결에만 0.5초씩 걸린다.
"""
from contextlib import contextmanager

import psycopg
import streamlit as st
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from teamform.config import get_secret


@st.cache_resource(show_spinner=False)
def get_pool() -> ConnectionPool:
    url = get_secret("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL 없음")
    return ConnectionPool(
        conninfo=url,
        min_size=1,
        max_size=4,
        kwargs={"connect_timeout": 10, "row_factory": dict_row},
        check=ConnectionPool.check_connection,  # Supabase가 끊은 연결을 빌려주지 않음
        open=True,
    )


@contextmanager
def connection():
    """풀에서 연결을 빌린다. 블록이 무사히 끝나면 커밋, 예외가 나면 되돌린다."""
    with get_pool().connection() as conn:
        yield conn


def safe_error(exc: Exception) -> str:
    """화면에 보일 DB 오류 문구. DB 주소나 비밀번호가 섞일 수 있는 원문은 보이지 않는다."""
    if isinstance(exc, psycopg.OperationalError):
        return "DB에 연결하지 못함"
    return f"DB 오류({type(exc).__name__})"
