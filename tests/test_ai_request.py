# -*- coding: utf-8 -*-
# 작성일시: 2026-10-21 01:03 (KST)
"""#11 오픈라우터 요청: reasoning effort low, 넉넉한 max_tokens, 빈 응답·429·오류 처리.

실제 오픈라우터를 부르지 않고 httpx의 가짜 전송(MockTransport)으로 응답을 꾸민다(무료 한도를 쓰지 않음).
"""
import json

import httpx
import pytest

from teamform import ai


def fake(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def ok(content, finish="stop"):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": finish}]})


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test-only")


def test_request_has_low_reasoning_and_large_max_tokens():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return ok('{"assignments": []}')

    ai.call_model(ai.MODELS[0], "배정해 줘", client=fake(handler))
    assert seen["reasoning"] == {"effort": "low"}
    assert seen["max_tokens"] == ai.MAX_TOKENS >= 8000
    assert seen["model"] == ai.MODELS[0]


def test_models_are_named_not_router():
    """[공고 4.3, 6.3-14] openrouter/free 라우터 금지. 모델 3개를 이름으로."""
    assert len(ai.MODELS) == 3 and len(set(ai.MODELS)) == 3
    assert all(m.endswith(":free") and m != "openrouter/free" and not m.startswith("openrouter/") for m in ai.MODELS)


def test_success_returns_content():
    assert ai.call_model("m", "p", client=fake(lambda r: ok('  {"a": 1}\n'))) == '{"a": 1}'


@pytest.mark.parametrize("content", ["", "   ", None])
def test_empty_response_is_failure(content):
    with pytest.raises(ai.AIError) as info:
        ai.call_model("m", "p", client=fake(lambda r: ok(content, finish="length")))
    assert info.value.kind == "빈 응답"
    assert "length" in info.value.detail


def test_http_429_is_failure():
    with pytest.raises(ai.AIError) as info:
        ai.call_model("m", "p", client=fake(lambda r: httpx.Response(429, json={"error": {"code": 429}})))
    assert info.value.kind == "HTTP 429"


def test_provider_error_in_body():
    body = {"error": {"code": 404, "message": "Provider returned error"}}
    with pytest.raises(ai.AIError) as info:
        ai.call_model("m", "p", client=fake(lambda r: httpx.Response(200, json=body)))
    assert info.value.kind == "오류" and info.value.detail == "제공사 오류 404"


def test_other_http_error():
    with pytest.raises(ai.AIError) as info:
        ai.call_model("m", "p", client=fake(lambda r: httpx.Response(500, text="boom")))
    assert (info.value.kind, info.value.detail) == ("오류", "HTTP 500")


def test_timeout():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ai.AIError) as info:
        ai.call_model("m", "p", client=fake(handler))
    assert info.value.kind == "시간 초과"


def test_error_never_contains_key():
    def handler(request):
        return httpx.Response(401, text=request.headers["Authorization"])  # 키를 되돌려 주는 고약한 서버

    with pytest.raises(ai.AIError) as info:
        ai.call_model("m", "p", client=fake(handler))
    assert "sk-or-v1" not in str(info.value)


def test_missing_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.setattr(ai, "get_secret", lambda name: None)
    with pytest.raises(ai.AIError) as info:
        ai.call_model("m", "p", client=fake(lambda r: ok("x")))
    assert info.value.detail == "OPENROUTER_API_KEY 없음"
