# -*- coding: utf-8 -*-
# 작성일시: 2026-10-21 01:03 (KST)
"""#15 DB 연결 재사용(공고 4.2). 화면을 여러 번 다시 그려도 연결을 새로 만들지 않는지 본다."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from teamform import db
from teamform.config import get_secret
from tests.test_student_screen import reset_easy

pytestmark = pytest.mark.skipif(not get_secret("DATABASE_URL"), reason="DATABASE_URL 없음")
APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


def test_reruns_reuse_pooled_connections():
    reset_easy()  # 쉬움 명단으로 처음 상태(학생1로 로그인할 수 있게)
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_input(key="login_student_no").input("2026101")  # 쉬움 명단의 가상 학생1
    at.text_input(key="login_password").input("1234")
    at.button(key="login_submit").click().run()
    assert not at.exception

    before = db.get_pool().get_stats()
    for _ in range(5):
        at.run()
    after = db.get_pool().get_stats()

    assert after.get("requests_num", 0) - before.get("requests_num", 0) >= 5  # 화면마다 풀에서 빌림
    assert after.get("connections_num", 0) == before.get("connections_num", 0)  # 새 연결은 0개
