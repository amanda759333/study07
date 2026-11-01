# -*- coding: utf-8 -*-
# 작성일시: 2026-10-20 20:27 (KST)
"""비밀 값 읽기.

로컬에서는 .env, 배포한 앱에서는 Streamlit Secrets에서 읽는다(공고 4.1).
값은 돌려주기만 하고 화면이나 로그에 출력하지 않는다. 확인할 때는 secret_status()로 "있음"/"없음"만 본다.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

SECRET_NAMES = ("OPENROUTER_API_KEY", "DATABASE_URL", "ADMIN_PASSWORD")

# .env는 streamlit_app.py와 같은 폴더(저장소 맨 위)에 둔다. 이미 있는 환경변수는 덮어쓰지 않는다
load_dotenv(Path(__file__).resolve().parent.parent / ".env", encoding="utf-8-sig")


QUOTE_PAIRS = {'"': '"', "'": "'", "“": "”", "‘": "’"}
QUOTE_CHARS = "\"'“”‘’"


def clean_secret(value) -> str | None:
    """붙여 넣다 생기는 실수를 떼어 낸다: 앞뒤 빈칸·줄바꿈, 값 전체를 한 번 더 감싼 따옴표(둥근 따옴표 포함).

    DATABASE_URL이 정확히 postgresql://로 시작하지 않으면 DB 연결 도구가 주소로 읽지 못하고
    'missing "=" after …' 오류를 낸다(11/2 배포에서 겪음).
    """
    if value is None:
        return None
    text = str(value).strip()
    while len(text) >= 2 and QUOTE_PAIRS.get(text[0]) == text[-1]:
        text = text[1:-1].strip()
    return text or None


def get_secret(name: str) -> str | None:
    """환경변수(.env 포함) → Streamlit Secrets 순으로 찾는다. 없으면 None."""
    value = clean_secret(os.environ.get(name))
    if value:
        return value
    try:
        import streamlit as st

        value = st.secrets.get(name)
    except Exception:  # secrets.toml이 없으면 예외가 난다
        value = None
    return clean_secret(value)


def describe_db_url(url: str | None) -> str:
    """DATABASE_URL의 모양만 설명한다(값·주소·비밀번호는 담지 않음). 배포한 앱의 연결 실패를 로그로 진단할 때 쓴다."""
    if not url:
        return "없음"
    yn = lambda ok: "예" if ok else "아니오"
    return (
        f"postgresql://로 시작={yn(url.startswith(('postgresql://', 'postgres://')))}, "
        f"빈칸·줄바꿈 있음={yn(any(ch.isspace() for ch in url))}, "
        f"따옴표 있음={yn(any(ch in url for ch in QUOTE_CHARS))}, "
        f"/postgres로 끝남={yn(url.endswith('/postgres'))}, "
        f"글자 수={len(url)}, @ 개수={url.count('@')}, : 개수={url.count(':')}"
    )


def secret_status() -> dict[str, str]:
    """비밀 값마다 "있음"/"없음"만 돌려준다. 값 자체는 절대 돌려주지 않는다."""
    return {name: "있음" if get_secret(name) else "없음" for name in SECRET_NAMES}
