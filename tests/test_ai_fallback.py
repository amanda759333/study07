# -*- coding: utf-8 -*-
# 작성일시: 2026-10-21 01:03 (KST)
"""#11 1차 → 2차 → 3차 폴백, 모델마다 전체 대기 시간 제한, 실패 종류(공고 2.5-5, 4.3).

실제 오픈라우터 대신 가짜 호출 함수를 넣는다(무료 한도를 쓰지 않음).
"""
import json
import time

import pytest

from teamform import ai, service
from teamform.ai import AIError, ask_models, build_prompt, parse_plan
from teamform.board import Board, Member, Team

MODELS = ("m1", "m2", "m3")
VALID = json.dumps({"assignments": [{"student_no": "S7", "team_no": 1}]})


def accept_all(plan):
    return []


def calls(*behaviours):
    """모델마다 할 일. 문자열이면 그 답을 돌려주고, 예외면 던지고, 숫자면 그만큼 잔다."""
    log = []

    def call(model, prompt, timeout):
        log.append(model)
        b = behaviours[len(log) - 1]
        if isinstance(b, (int, float)):
            time.sleep(b)
            return VALID
        if isinstance(b, Exception):
            raise b
        return b

    return call, log


def test_falls_back_through_429_and_empty_to_third():
    call, log = calls(AIError("HTTP 429", "사용량 제한"), AIError("빈 응답", "finish_reason=length"), VALID)
    result = ask_models("p", accept_all, models=MODELS, call=call)
    assert log == ["m1", "m2", "m3"]
    assert [a.outcome for a in result.attempts] == ["HTTP 429", "빈 응답", "성공"]
    assert result.model_no == 3 and result.plan == [("S7", 1)]


def test_first_success_stops():
    call, log = calls(VALID)
    result = ask_models("p", accept_all, models=MODELS, call=call)
    assert log == ["m1"] and result.model_no == 1


def test_timeout_moves_on_without_waiting_for_slow_model():
    """[공고 2.5-5] 부른 때부터 제한 시간이 넘으면 끊고 다음 모델로. 응답이 늦게 와도 기다리지 않는다."""
    call, log = calls(3.0, VALID)
    started = time.monotonic()
    result = ask_models("p", accept_all, models=MODELS, call=call, timeout=0.5, poll=0.1)
    assert time.monotonic() - started < 2.0  # 3초짜리 응답을 기다리지 않음
    assert [a.outcome for a in result.attempts] == ["시간 초과", "성공"]
    assert result.attempts[0].seconds < 1.0
    assert result.model_no == 2


def test_check_failure_moves_on():
    """[공고 2.5-5] 배정안이 검사를 통과하지 못하면 실패로 보고 다음 모델로."""
    bad = json.dumps({"assignments": [{"student_no": "S9", "team_no": 1}]})
    call, _ = calls(bad, VALID)

    def check(plan):
        return [f"{s}은 팀이 없는 학생이 아님" for s, _ in plan if s != "S7"]

    result = ask_models("p", check, models=MODELS, call=call)
    assert [a.outcome for a in result.attempts] == ["검사 실패", "성공"]
    assert result.attempts[0].detail == "S9은 팀이 없는 학생이 아님"


def test_unreadable_answer_and_unexpected_error_are_failures():
    call, _ = calls("배정할 수 없습니다.", RuntimeError("boom"), VALID)
    result = ask_models("p", accept_all, models=MODELS, call=call)
    assert [a.outcome for a in result.attempts] == ["검사 실패", "오류", "성공"]


def test_all_three_fail():
    call, log = calls(AIError("HTTP 429"), AIError("오류", "HTTP 500"), AIError("빈 응답"))
    result = ask_models("p", accept_all, models=MODELS, call=call)
    assert len(log) == 3 and result.plan is None and result.model_no is None


def test_wait_and_attempt_callbacks_show_which_model():
    """[공고 3장 「AI 대기 중 화면」] 몇 차 모델을 기다리는지 알려 준다."""
    call, _ = calls(0.3, VALID)
    waits, done = [], []
    ask_models("p", accept_all, models=MODELS, call=call, timeout=0.1, poll=0.02,
               on_wait=lambda no, model, s: waits.append(no), on_attempt=done.append)
    assert waits[0] == 1 and 2 in waits
    assert [a.no for a in done] == [1, 2]


# 답 읽기와 질문 만들기 ----------------------------------------------------------

@pytest.mark.parametrize("content", [
    '{"assignments": [{"student_no": "2026107", "team_no": 2}]}',
    '```json\n{"assignments": [{"student_no": 2026107, "team_no": "2"}]}\n```',
    '배정안입니다.\n{"assignments": [{"student_no": "2026107", "team_no": 2}]}\n끝.',
    '[{"student_no": "2026107", "team_no": 2}]',
])
def test_parse_plan_variants(content):
    assert parse_plan(content) == [("2026107", 2)]


@pytest.mark.parametrize("content", ["없음", '{"answer": 1}', '{"assignments": [{"team_no": 1}]}'])
def test_parse_plan_rejects(content):
    with pytest.raises(ValueError):
        parse_plan(content)


def board_after_close():
    pl = Member(1, "2026101", "학생1", "기획자", ("보고서 작성자",))
    s7 = Member(7, "2026107", "학생7", "프론트엔드 디자이너", ("발표자",))
    return Board([Team(1, 1, "팀1", [pl]), Team(2, 2, "팀2")], closed=True, unassigned=[s7])


def test_prompt_has_rules_teams_and_unassigned_without_names():
    prompt = build_prompt(board_after_close())
    assert "2~4명" in prompt and "서로 다른 사람으로 1명씩" in prompt and "주 역할이 동일한" in prompt
    assert "팀1 (1명): 2026101(주 역할 기획자, 보조 역할 보고서 작성자)" in prompt
    assert "팀2 (0명): 팀원 없음" in prompt
    assert "2026107: 주 역할 프론트엔드 디자이너, 보조 역할 발표자" in prompt
    assert "학생1" not in prompt and "학생7" not in prompt  # 이름은 보내지 않음


# service.propose ----------------------------------------------------------------

ADMIN = service.User(0, "admin", "관리자", None, (), True)


def test_propose_needs_close_and_admin():
    open_board = board_after_close()
    open_board.closed = False
    assert service.propose(ADMIN, open_board) == ("막힘: 모집이 마감되지 않음", None)
    with pytest.raises(PermissionError):
        service.propose(service.User(1, "2026101", "학생1", "기획자", (), False), board_after_close())


def test_propose_uses_format_check(monkeypatch):
    answers = iter([
        '{"assignments": [{"student_no": "2026101", "team_no": 2}]}',  # 이미 팀이 있는 학생을 옮김 → 검사 실패
        '{"assignments": [{"student_no": "2026107", "team_no": 9}]}',  # 없는 팀 → 검사 실패
        '{"assignments": [{"student_no": "2026107", "team_no": 1}]}',
    ])
    monkeypatch.setattr(ai, "call_model", lambda model, prompt, timeout: next(answers))
    message, result = service.propose(ADMIN, board_after_close())
    assert message == "승인: 3차 모델의 배정안이 검사를 통과함"
    assert [a.detail for a in result.attempts[:2]] == ["2026101은 팀이 없는 학생이 아님", "팀9은 없는 팀"]


def test_propose_all_fail(monkeypatch):
    def fail(model, prompt, timeout):
        raise AIError("HTTP 429", "사용량 제한")

    monkeypatch.setattr(ai, "call_model", fail)
    message, result = service.propose(ADMIN, board_after_close())
    assert message == "막힘: 3차 모델까지 실패함" and len(result.attempts) == 3
