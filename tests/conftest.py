# -*- coding: utf-8 -*-
# 작성일시: 2026-10-20 20:27 (KST)
"""테스트 공통 준비.

DB가 필요한 테스트는 .env의 DATABASE_URL로 접속하고, 끝나면 트랜잭션을 되돌려 DB에 아무것도 남기지 않는다.
"""
import psycopg
import pytest
from psycopg.rows import dict_row

from teamform.config import get_secret


@pytest.fixture
def conn():
    url = get_secret("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL 없음")
    connection = psycopg.connect(url, connect_timeout=10, row_factory=dict_row)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()
