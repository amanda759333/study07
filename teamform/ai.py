# -*- coding: utf-8 -*-
# 작성일시: 2026-10-21 01:03 (KST)
"""오픈라우터 요청(공고 4.3).

추론 모델은 응답 길이 한도(max_tokens)를 생각하는 데 다 써서 빈 응답을 낼 수 있다.
빈 응답을 줄이려고 reasoning effort를 low로 주고 max_tokens를 넉넉히 준다(공고 4.3, 시범 앱과 같은 방법).
빈 응답이 와도 실패로 보고 AIError를 낸다. 1→2→3차 폴백은 작업 #11의 다음 단계에서 이 함수를 쓴다.
"""
import httpx

from teamform.config import get_secret

API_URL = "https://openrouter.ai/api/v1/chat/completions"

# [공고 4.3] 무료 텍스트 생성 모델 3개를 이름으로 직접 지정한다. 라우터 openrouter/free는 쓰지 않는다
MODELS = (
    "google/gemma-4-31b-it:free",
    "minimax/minimax-m3.1-flash:free",
    "dots-studio/dots-3-note-preview:free",
)

REASONING = {"effort": "low"}  # 생각을 짧게 해서 답을 쓸 몫을 남긴다
# 넉넉한 응답 길이 한도. 배정안 JSON은 길어야 1~2천 토큰이고, 남는 몫은 생각에 쓰인다.
# 세 모델 가운데 가장 작은 출력 한도(gemma-4-31b의 32768)보다 작게 둔다(2026-10-21 오픈라우터 모델 목록)
MAX_TOKENS = 16000


class AIError(Exception):
    """모델 호출 실패. kind는 실패 종류: "빈 응답", "HTTP 429", "오류" 등.

    detail에는 상태 코드와 짧은 설명만 담는다. 키나 응답 원문 전체는 담지 않는다(공고 4.1).
    """

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail


def build_request(model: str, prompt: str) -> dict:
    """오픈라우터 요청 본문."""
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "reasoning": REASONING,
        "max_tokens": MAX_TOKENS,
    }


def call_model(model: str, prompt: str, *, timeout: float = 120.0, client: httpx.Client | None = None) -> str:
    """모델 하나를 한 번 부르고 답의 본문을 돌려준다. 실패하면 AIError."""
    key = get_secret("OPENROUTER_API_KEY")
    if not key:
        raise AIError("오류", "OPENROUTER_API_KEY 없음")
    http = client or httpx.Client()
    try:
        response = http.post(
            API_URL,
            headers={"Authorization": f"Bearer {key}"},
            json=build_request(model, prompt),
            timeout=httpx.Timeout(timeout, connect=15.0),
        )
    except httpx.TimeoutException:
        raise AIError("시간 초과") from None
    except httpx.HTTPError as exc:
        raise AIError("오류", type(exc).__name__) from None
    finally:
        if client is None:
            http.close()

    # [공고 4.3] 사용량이 많다며 거절(HTTP 429)
    if response.status_code == 429:
        raise AIError("HTTP 429", "사용량 제한")
    if response.status_code != 200:
        raise AIError("오류", f"HTTP {response.status_code}")
    try:
        body = response.json()
    except ValueError:
        raise AIError("오류", "JSON이 아닌 응답") from None
    if "error" in body:
        code = body["error"].get("code") if isinstance(body["error"], dict) else None
        raise AIError("HTTP 429" if code == 429 else "오류", f"제공사 오류 {code}")

    choice = (body.get("choices") or [{}])[0]
    content = ((choice.get("message") or {}).get("content") or "").strip()
    # [공고 4.3] 빈 응답도 실패로 처리하고 다음 모델로 넘어간다
    if not content:
        raise AIError("빈 응답", f"finish_reason={choice.get('finish_reason')}")
    return content
