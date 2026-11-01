# -*- coding: utf-8 -*-
# 작성일시: 2026-11-02 03:40 (KST)
"""비밀 값 읽기: Secrets에 붙여 넣다 생긴 빈칸·따옴표를 떼어 낸다(11/2 배포에서 DB 연결 실패)."""
import pytest

from teamform import config
from teamform.config import clean_secret

URL = "postgresql://user:pw@host.example:5432/postgres"  # 테스트용 가짜 주소


@pytest.mark.parametrize("raw", [
    URL,
    f"  {URL}  ",
    f"\n{URL}\n",
    f'"{URL}"',
    f'""{URL}""',
    f"'{URL}'",
    f"“{URL}”",
    f' " {URL} " ',
])
def test_clean_secret_keeps_only_the_url(raw):
    assert clean_secret(raw) == URL


@pytest.mark.parametrize("raw", [None, "", "   ", '""'])
def test_clean_secret_empty(raw):
    assert clean_secret(raw) is None


def test_quotes_inside_value_are_kept():
    assert clean_secret('ab"cd') == 'ab"cd'
    assert clean_secret('"ab') == '"ab'  # 짝이 맞지 않으면 그대로


def test_get_secret_cleans_environment_value(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f'  "{URL}" ')
    assert config.get_secret("DATABASE_URL") == URL
