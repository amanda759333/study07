# -*- coding: utf-8 -*-
# 작성일시: 2026-10-21 01:03 (KST)
"""#11 1차 → 2차 → 3차 폴백, 모델마다 전체 대기 시간 제한, 실패 종류(공고 2.5-5, 4.3).

실제 오픈라우터 대신 가짜 호출 함수를 넣는다(무료 한도를 쓰지 않음).
"""
import json
import time

import pytest

from teamform import ai, rules, service
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
    """팀1: 기획자 1명, 팀2: 기획자·웹 프로그래머. 팀이 없는 학생4(웹 프로그래머)를 팀1에 넣으면 규칙을 지킨다."""
    pl1 = Member(1, "2026101", "학생1", "기획자", ("보고서 작성자",))
    pl2 = Member(2, "2026102", "학생2", "기획자", ())
    wp5 = Member(5, "2026105", "학생5", "웹 프로그래머", ())
    wp4 = Member(4, "2026104", "학생4", "웹 프로그래머", ("프론트엔드 디자이너",))
    return Board([Team(1, 1, "팀1", [pl1]), Team(2, 2, "팀2", [pl2, wp5])], closed=True, unassigned=[wp4])


def test_prompt_has_rules_teams_and_unassigned_without_names():
    prompt = build_prompt(board_after_close())
    assert "2~4명" in prompt and "서로 다른 사람으로 1명씩" in prompt and "주 역할이 동일한" in prompt
    assert "팀1 (1명): 2026101(주 역할 기획자, 보조 역할 보고서 작성자)" in prompt
    assert "팀2 (2명): 2026102(주 역할 기획자, 보조 역할 없음); 2026105(주 역할 웹 프로그래머, 보조 역할 없음)" in prompt
    assert "2026104: 주 역할 웹 프로그래머, 보조 역할 프론트엔드 디자이너" in prompt
    assert "학생1" not in prompt and "학생4" not in prompt  # 이름은 보내지 않음


# service.propose ----------------------------------------------------------------

ADMIN = service.User(0, "admin", "관리자", None, (), True)


def test_propose_needs_close_and_admin():
    open_board = board_after_close()
    open_board.closed = False
    assert service.propose(ADMIN, open_board) == ("막힘: 모집이 마감되지 않음", None)
    with pytest.raises(PermissionError):
        service.propose(service.User(1, "2026101", "학생1", "기획자", (), False), board_after_close())


def test_propose_uses_five_checks(monkeypatch):
    answers = iter([
        '{"assignments": [{"student_no": "2026104", "team_no": 2}]}',  # 팀2에 웹 프로그래머 둘, 팀1은 1명 → 검사 실패
        '{"assignments": [{"student_no": "2026104", "team_no": 9}]}',  # 없는 팀 → 검사 실패
        '{"assignments": [{"student_no": "2026104", "team_no": 1}]}',
    ])
    monkeypatch.setattr(ai, "call_model", lambda model, prompt, timeout: next(answers))
    message, result = service.propose(ADMIN, board_after_close())
    assert message == "승인: 3차 모델의 배정안이 검사를 통과함"
    assert result.attempts[0].detail.startswith("③ 팀1이 1명임(2~4명이어야 함)")
    assert result.attempts[1].detail.startswith("팀9은 없는 팀")
    assert result.plan == [("2026104", 1)]


def test_propose_all_fail(monkeypatch):
    def fail(model, prompt, timeout):
        raise AIError("HTTP 429", "사용량 제한")

    monkeypatch.setattr(ai, "call_model", fail)
    board = board_after_close()
    message, result = service.propose(ADMIN, board)
    # [공고 2.5-6, 3장 어려운 해결] 3차까지 실패하면 앱이 모든 경우를 따져 배정한다
    assert message == "승인: 3차 모델까지 실패해 앱이 모든 경우를 따져 배정함(검사 다섯 가지 통과)"
    assert len(result.attempts) == 3 and result.by_app and result.model_no is None
    assert result.plan == [("2026104", 1)]
    assert rules.check_assignment(board, result.plan) == []


def test_impossible_board_does_not_call_ai(monkeypatch):
    """[공고 2.5-8] 규칙을 지키는 배정이 없으면 AI를 부르지 않고 이유를 보인다."""
    def must_not_call(model, prompt, timeout):
        raise AssertionError("AI를 부르면 안 됨")

    monkeypatch.setattr(ai, "call_model", must_not_call)
    board = board_after_close()
    board.teams[1].members.pop()  # 팀2에서 웹 프로그래머가 빠짐 → 웹 프로그래머가 팀 둘 다 필요한데 학생4 한 명뿐
    message, result = service.propose(ADMIN, board)
    assert message.startswith("막힘: 규칙을 지키는 배정이 없음: ") and result is None
    assert "웹 프로그래머가 없는 팀은 2개인데 웹 프로그래머를 맡을 수 있는 팀이 없는 학생은 1명임" in message


def test_attempt_markdown_keeps_free_suffix():
    """화면용 줄은 모델 이름을 코드 서식으로 감싸 ":free:"가 이모지로 바뀌지 않게 한다(10/31 캡처에서 발견)."""
    attempt = ai.Attempt(1, "google/gemma-4-31b-it:free", "HTTP 429", 0.7, "사용량 제한")
    assert attempt.markdown() == "1차 `google/gemma-4-31b-it:free`: HTTP 429 (0.7초) — 사용량 제한"
    assert attempt.text() == "1차 google/gemma-4-31b-it:free: HTTP 429 (0.7초) — 사용량 제한"  # 로그는 그대로
