# -*- coding: utf-8 -*-
# 작성일시: 2026-10-21 01:03 (KST)
"""오픈라우터 요청(공고 4.3).

추론 모델은 응답 길이 한도(max_tokens)를 생각하는 데 다 써서 빈 응답을 낼 수 있다.
빈 응답을 줄이려고 reasoning effort를 low로 주고 max_tokens를 넉넉히 준다(공고 4.3, 시범 앱과 같은 방법).
빈 응답이 와도 실패로 보고 AIError를 낸다. ask_models는 1차 → 2차 → 3차 순서로 이 함수를 부른다.
"""
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Callable

import httpx

from teamform.board import Board
from teamform.config import get_secret

log = logging.getLogger(__name__)

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


# AI 배정: 1차 → 2차 → 3차 ------------------------------------------------------

# [공고 2.5-5, 3장 「AI 응답이 늦을 때」 어려운 해결] 모델 하나를 부른 때부터 응답을 받을 때까지 120초가 넘으면
# 끊고 다음 모델로 넘어간다. 요청은 작업 스레드에서 보내고, 시계로 전체 시간을 잰다.
# 응답이 천천히 조금씩 와도 120초에서 기다리기를 그만둔다(시간 제한 값만 주면 120초를 넘길 수 있음)
MODEL_TIMEOUT = 120.0
_pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="openrouter")


@dataclass
class Attempt:
    """모델 한 번 부른 기록. outcome: 성공, 시간 초과, 빈 응답, HTTP 429, 오류, 검사 실패."""

    no: int
    model: str
    outcome: str
    seconds: float
    detail: str = ""

    def text(self) -> str:
        detail = f" — {self.detail}" if self.detail else ""
        return f"{self.no}차 {self.model}: {self.outcome} ({self.seconds:.1f}초){detail}"


@dataclass
class AssignResult:
    plan: list[tuple[str, int]] | None  # (학번, 팀 번호). 검사를 통과한 배정안만. 모두 실패하면 None
    model_no: int | None  # 몇 차 모델의 배정안인지
    attempts: list[Attempt] = field(default_factory=list)
    by_app: bool = False  # 3차 모델까지 실패해 앱이 스스로 만든 배정안이면 True(공고 2.5-6)


RULES_TEXT = """- 팀 수는 정해져 있다(팀1, 팀2, …). 배정한 뒤 모든 팀이 2~4명이어야 한다(빈 팀 없음).
- 주 역할이 동일한 학생이 한 팀에 2명 이상이면 안 된다.
- 모든 팀에는 기획자 역할 학생과 웹 프로그래머 역할 학생이 서로 다른 사람으로 1명씩 있어야 한다. 주 역할이나 보조 역할로 맡을 수도 있다.
- 주 역할은 팀 안의 중복을 따지는 기준이고, 보조 역할은 필수 포함 역할을 맡을 수 있는지 따질 때만 쓴다.
- 팀이 없는 학생만 팀에 넣는다. 이미 팀에 있는 학생은 옮기지 않는다."""


def _roles(m) -> str:
    subs = ", ".join(m.sub_roles) if m.sub_roles else "없음"
    return f"주 역할 {m.main_role}, 보조 역할 {subs}"


def build_prompt(board: Board) -> str:
    """[공고 2.5-3] 지금의 팀 구성, 팀이 없는 학생과 그 역할, 2.3절의 규칙을 보낸다. 이름 대신 학번만 보낸다."""
    teams = []
    for t in board.teams:
        members = "; ".join(f"{m.student_no}({_roles(m)})" for m in t.members) or "팀원 없음"
        teams.append(f"- 팀{t.no} ({len(t.members)}명): {members}")
    students = "\n".join(f"- {m.student_no}: {_roles(m)}" for m in board.unassigned)
    example = ", ".join(f'{{"student_no": "{m.student_no}", "team_no": 1}}' for m in board.unassigned[:2])
    return f"""팀 프로젝트의 팀 편성을 돕는다. 아래 규칙을 모두 지키도록, 팀이 없는 학생을 한 명도 빠짐없이 한 팀씩 배정하라.

규칙:
{RULES_TEXT}

지금의 팀 구성(팀 {len(board.teams)}개):
{chr(10).join(teams)}

팀이 없는 학생({len(board.unassigned)}명):
{students}

설명 없이 JSON 하나로만 답하라. 팀이 없는 학생 모두가 정확히 한 번씩 들어가야 한다.
형식: {{"assignments": [{example}, ...]}}"""


def parse_plan(content: str) -> list[tuple[str, int]]:
    """모델의 답에서 배정안을 꺼낸다. 코드 블록이나 앞뒤 설명이 붙어 있어도 첫 JSON을 읽는다. 못 읽으면 ValueError."""
    match = re.search(r"\{.*\}|\[.*\]", content, re.DOTALL)
    if not match:
        raise ValueError("JSON을 찾지 못함")
    data = json.loads(match.group(0))
    items = data.get("assignments") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("assignments 목록이 없음")
    plan = []
    for item in items:
        try:
            plan.append((str(item["student_no"]).strip(), int(item["team_no"])))
        except (KeyError, TypeError, ValueError):
            raise ValueError("student_no·team_no를 읽지 못함") from None
    return plan


def ask_models(
    prompt: str,
    check: Callable[[list[tuple[str, int]]], list[str]],
    *,
    models: tuple[str, ...] = MODELS,
    timeout: float = MODEL_TIMEOUT,
    call: Callable[..., str] | None = None,
    on_wait: Callable[[int, str, float], None] | None = None,
    on_attempt: Callable[[Attempt], None] | None = None,
    poll: float = 1.0,
) -> AssignResult:
    """1차 → 2차 → 3차 순서로 부르고, 검사를 통과한 첫 배정안을 돌려준다.

    [공고 2.5-5] 응답 없음(120초 초과), 빈 응답, HTTP 429, 그 밖의 오류, 검사 불통과를 모두 실패로 보고 다음 모델로 간다.
    on_wait(몇 차, 모델, 지난 초)는 기다리는 동안 poll초마다, on_attempt(기록)는 시도 하나가 끝날 때마다 불린다
    (assign_status 안내용).
    """
    call = call or call_model
    result = AssignResult(plan=None, model_no=None)
    for no, model in enumerate(models, start=1):
        start = time.monotonic()
        future = _pool.submit(call, model, prompt, timeout=timeout)
        while True:
            elapsed = time.monotonic() - start
            if on_wait:  # 부르자마자 한 번, 그 뒤 poll초마다 알린다(곧바로 답해도 몇 차인지 보이게)
                on_wait(no, model, min(elapsed, timeout))
            if future.done() or elapsed >= timeout:
                break
            wait([future], timeout=min(poll, timeout - elapsed))
        seconds = time.monotonic() - start

        def record(outcome: str, detail: str = "") -> None:
            attempt = Attempt(no, model, outcome, seconds, detail)
            result.attempts.append(attempt)
            log.info("AI 배정 %s", attempt.text())  # 키나 응답 원문은 남기지 않는다
            if on_attempt:
                on_attempt(attempt)

        if not future.done():
            future.cancel()  # 이미 보낸 요청은 스레드에서 끝나도록 두고 더는 기다리지 않는다
            record("시간 초과", f"{timeout:.0f}초 안에 응답 없음")
            continue
        try:
            content = future.result()
        except AIError as exc:
            record(exc.kind, exc.detail)
            continue
        except Exception as exc:  # 예상하지 못한 오류도 실패로 보고 넘어간다
            record("오류", type(exc).__name__)
            continue
        try:
            plan = parse_plan(content)
        except (ValueError, json.JSONDecodeError) as exc:
            record("검사 실패", f"배정안을 읽지 못함({exc})")
            continue
        problems = check(plan)
        if problems:
            more = f" 외 {len(problems) - 1}건" if len(problems) > 1 else ""
            record("검사 실패", problems[0] + more)
            continue
        record("성공")
        result.plan, result.model_no = plan, no
        return result
    return result
