"""
Claude 감독: 경기 상황을 주기적으로 Claude API 에 보내 전략(1/2/3)을 고르게 합니다.

로봇 제어는 앱이 초당 수십 번 직접 계산하고, Claude 는 몇 초에 한 번 '어떤 전략으로 뛸지'만 정합니다.
API 호출은 별도 스레드에서 하므로 화면과 로봇 제어가 멈추지 않습니다.
API 키는 설치할 때 입력한 값(%APPDATA%\\HamsterSoccer\\config.json), 앱에서 입력한 값,
또는 ANTHROPIC_API_KEY 환경 변수를 씁니다.
"""
import json
import threading
import time
from typing import Literal

import anthropic
from pydantic import BaseModel, Field

# 가격: 100만 토큰당 달러 (입력, 출력). Haiku 5.5 는 입력 10만 토큰 이하 기준
MODELS = {
    "claude-haiku-5-5": {"label": "Haiku 5.5 (가장 저렴)", "price": (0.10, 0.50)},
    "claude-sonnet-5-5": {"label": "Sonnet 5.5", "price": (2.00, 10.00)},
    "claude-opus-5-5": {"label": "Opus 5.5 (고성능)", "price": (4.00, 20.00)},
}
DEFAULT_MODEL = "claude-haiku-5-5"

SYSTEM_PROMPT = """당신은 햄스터봇 2대로 이루어진 AI 축구팀의 감독입니다.
경기장은 천장 카메라로 보고 있으며, 우리 골대는 왼쪽(x=0 쪽), 상대(사람) 골대는 오른쪽(x=1 쪽)입니다.
좌표는 경기장 크기로 나눈 0~1 값입니다.

고를 수 있는 전략:
1 = 두 대 모두 공격: 공에 가까운 로봇이 공을 몰고, 다른 로봇은 옆에서 받쳐줌. 득점 기회는 크지만 우리 골대가 빔.
2 = 1대 공격 + 1대 수비: 로봇1은 공격, 로봇2는 골키퍼. 균형형.
3 = 가까우면 몰고가기 / 멀면 수비: 공이 가까우면 몰고 가고, 공이 멀어지면 둘 다 수비로 돌아옴. 수비형.

점수 차, 남은 시간, 공의 위치와 움직임, 로봇 위치를 보고 다음 약 10초 동안 쓸 전략 하나를 고르세요.
이유는 관람객에게 보여줄 한국어 한 문장(40자 이내)으로 쓰세요."""


class CoachDecision(BaseModel):
    strategy: Literal[1, 2, 3] = Field(description="다음 약 10초 동안 쓸 전략 번호")
    reason: str = Field(description="전략을 고른 이유, 한국어 한 문장 (40자 이내)")


class ClaudeCoach:
    def __init__(self, api_key=None, model=DEFAULT_MODEL, interval_sec=5.0):
        self.api_key = api_key
        self.model = model
        self.interval_sec = interval_sec
        self.calls = 0             # 성공한 호출 수와 사용 토큰 (비용 표시용)
        self.input_tokens = 0
        self.output_tokens = 0
        self._cost = 0.0
        self.decision = None       # 가장 최근 CoachDecision
        self.decision_id = 0       # 새 결정이 올 때마다 1씩 증가
        self.error = None
        self.busy = False
        self._last_request = 0.0
        self._lock = threading.Lock()
        self._history = []         # 최근 결정 (상황 흐름을 알려주기 위해)

    def cost_usd(self):
        return self._cost

    def set_api_key(self, key):
        self.api_key = key or None
        self.error = None

    def maybe_request(self, state):
        """주기가 지났고 진행 중인 요청이 없으면 백그라운드로 감독에게 묻는다."""
        if not self.api_key:
            return
        now = time.monotonic()
        with self._lock:
            if self.busy or now - self._last_request < self.interval_sec:
                return
            self.busy = True
            self._last_request = now
        threading.Thread(target=self._ask, args=(state,), daemon=True).start()

    def _ask(self, state):
        try:
            client = anthropic.Anthropic(api_key=self.api_key, timeout=30.0, max_retries=1)
            content = ("현재 경기 상황(JSON):\n" + json.dumps(state, ensure_ascii=False)
                       + "\n\n최근 감독 결정: " + json.dumps(self._history[-3:], ensure_ascii=False))
            model = self.model
            request = dict(
                model=model,
                max_tokens=4000,
                output_config={"effort": "low"},      # 빠른 판단이 중요해 낮은 effort 사용
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
                output_format=CoachDecision,
            )
            if model == "claude-haiku-5-5":
                response = client.messages.parse(**request)   # Haiku 는 서버 측 대체 모델 기능이 없음
            else:
                # 안전 거절 시 서버가 다른 모델로 다시 시도
                response = client.beta.messages.parse(**request, betas=["server-side-fallback-2026-07-01"],
                                                      fallbacks="default")
            price_in, price_out = MODELS[model]["price"]
            self.calls += 1
            self.input_tokens += response.usage.input_tokens
            self.output_tokens += response.usage.output_tokens
            self._cost += (response.usage.input_tokens * price_in + response.usage.output_tokens * price_out) / 1e6
            if response.stop_reason == "refusal" or response.parsed_output is None:
                self.error = f"감독 응답 없음 ({response.stop_reason})"
                return
            decision = response.parsed_output
            self._history.append({"전략": decision.strategy, "이유": decision.reason})
            self._history = self._history[-5:]
            self.decision = decision
            self.decision_id += 1
            self.error = None
        except anthropic.AuthenticationError:
            self.error = "API 키가 올바르지 않습니다"
        except anthropic.PermissionDeniedError:
            self.error = "API 키 권한이 없습니다"
        except anthropic.RateLimitError:
            self.error = "요청 한도 초과 — 잠시 후 다시 시도합니다"
        except anthropic.APIStatusError as e:
            self.error = f"API 오류 ({e.status_code})"
        except anthropic.APIConnectionError:
            self.error = "인터넷 연결을 확인하세요"
        except Exception as e:  # 키 미설정 등. 경기 진행은 계속되어야 하므로 앱을 멈추지 않는다
            self.error = f"감독 오류: {e}"
        finally:
            self.busy = False
