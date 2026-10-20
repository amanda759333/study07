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


def get_secret(name: str) -> str | None:
    """환경변수(.env 포함) → Streamlit Secrets 순으로 찾는다. 없으면 None."""
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st

        value = st.secrets.get(name)
    except Exception:  # secrets.toml이 없으면 예외가 난다
        value = None
    return str(value) if value else None


def secret_status() -> dict[str, str]:
    """비밀 값마다 "있음"/"없음"만 돌려준다. 값 자체는 절대 돌려주지 않는다."""
    return {name: "있음" if get_secret(name) else "없음" for name in SECRET_NAMES}
